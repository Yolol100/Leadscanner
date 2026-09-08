from __future__ import annotations

import json
import os
import re

from outreach_sender import (
    QUEUE_HEADERS,
    QUEUE_SHEET,
    Settings,
    build_sheets_service,
    ensure_expected_headers,
    get_values,
    rows_from_values,
)
from prospect_discovery import (
    BoundedHttpClient,
    DiscoveryError,
    HARD_MAX_BYTES,
    host_key,
    match_terms,
    normalize_url,
    parse_page,
    root_url,
)
from prospect_target_policy import DEFAULT_AGENCY_EXCLUDE_TERMS, canonical_country, is_excluded_domain

LEGACY_EVIDENCE_PREFIX = "website_scan:"
AGENT_EVIDENCE_PREFIX = "agent_offer:"
POSTAL_PLACEHOLDER = "{{OUTREACH_POSTAL_ADDRESS}}"
LIVE_CANDIDATE_STATUSES = {"approved"}
UK_CORPORATE_SUFFIX_RE = re.compile(r"(?i)\b(?:ltd\.?|limited|llp|plc)\b")
TARGET_FETCH_ATTEMPTS = 3
APPROVED_AGENT_TYPES = {
    "front_desk_sales", "lead_reactivation", "review_concierge",
    "customer_support", "commerce", "quote_intake",
}


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _same_domain(left: str, right: str) -> bool:
    left_url = normalize_url(left, require_path=True)
    right_url = normalize_url(right, require_path=True)
    return bool(left_url and right_url and host_key(left_url) == host_key(right_url))


def parse_evidence_source(raw: object) -> dict[str, str]:
    value = str(raw or "").strip()
    if value.startswith(AGENT_EVIDENCE_PREFIX):
        kind, payload = "agent_offer", value[len(AGENT_EVIDENCE_PREFIX):].strip()
    elif value.startswith(LEGACY_EVIDENCE_PREFIX):
        kind, payload = "website_scan", value[len(LEGACY_EVIDENCE_PREFIX):].strip()
    else:
        raise ValueError("source must start with agent_offer: or website_scan:")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{kind} source must contain valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{kind} source payload must be an object")
    output = {str(key): str(item or "").strip() for key, item in data.items()}
    output["_evidence_kind"] = kind
    return output


def metadata_errors(row: dict[str, str], *, postal_address: str = "") -> list[str]:
    errors: list[str] = []
    country = canonical_country(row.get("country", ""))
    website = row.get("website", "")
    if not normalize_url(website, require_path=True):
        return ["missing or invalid official website"]
    if is_excluded_domain(website):
        errors.append("Webactueel/self domain is excluded from prospect outreach")
    try:
        evidence = parse_evidence_source(row.get("source", ""))
    except ValueError as exc:
        errors.append(str(exc))
        return errors

    kind = evidence.get("_evidence_kind", "")
    evidence_url = evidence.get("evidence_url", "")
    fact = _text(evidence.get("fact", ""))
    idea = _text(evidence.get("idea", ""))
    body_text = _text(row.get("body", ""))
    if not evidence_url or not _same_domain(website, evidence_url):
        errors.append(f"{kind} evidence_url must be on the official prospect domain")
    if len(fact) < 15:
        errors.append(f"{kind} fact must contain a concise evidence-bound company fact")
    elif fact.casefold() not in body_text.casefold():
        errors.append(f"mail body must contain the exact {kind} fact")
    if len(idea) < 20:
        errors.append(f"{kind} idea must contain a concrete evidence-bound improvement")
    elif idea.casefold() not in body_text.casefold():
        errors.append(f"mail body must contain the exact {kind} idea")

    if kind == "website_scan":
        analysis_type = evidence.get("analysis_type", "").casefold()
        if analysis_type not in {"website", "webshop"}:
            errors.append("website_scan analysis_type must be website or webshop")
    elif kind == "agent_offer":
        if evidence.get("offer_family", "").casefold() != "ai_agent":
            errors.append("agent_offer offer_family must be ai_agent")
        if evidence.get("agent_type", "").casefold() not in APPROVED_AGENT_TYPES:
            errors.append("agent_offer agent_type must be one of the six approved Webactueel agents")
        if len(_text(evidence.get("business_process", ""))) < 8:
            errors.append("agent_offer must contain an evidence-bound business_process")
        if len(_text(evidence.get("kpi_candidate", ""))) < 8:
            errors.append("agent_offer must contain a KPI candidate")

    if country == "GB":
        subscriber_type = evidence.get("subscriber_type", "").casefold()
        if subscriber_type != "corporate" or not UK_CORPORATE_SUFFIX_RE.search(row.get("company", "")):
            errors.append("UK unsolicited email requires a verified corporate subscriber; sole traders/uncertain entities stay blocked")

    if country == "US":
        address = _text(postal_address)
        body = str(row.get("body", ""))
        if not address:
            errors.append("US commercial email requires configured OUTREACH_POSTAL_ADDRESS")
        if POSTAL_PLACEHOLDER not in body:
            errors.append("US commercial email body must contain the private postal placeholder")
        if address and address.casefold() in body.casefold():
            errors.append("US private postal address must not be persisted in OutreachQueue")
        if "commercial message" not in body.casefold() and "advertisement" not in body.casefold():
            errors.append("US commercial email must clearly identify the message as commercial/advertising")

    return errors


def website_target_errors(row: dict[str, str], client: BoundedHttpClient) -> list[str]:
    website = root_url(row.get("website", ""))
    if not website:
        return ["invalid website for target check"]
    if is_excluded_domain(website):
        return ["Webactueel/self domain is excluded from prospect outreach"]
    page = None
    last_error: DiscoveryError | None = None
    for _attempt in range(TARGET_FETCH_ATTEMPTS):
        try:
            page = parse_page(client.fetch_text(website), website)
            break
        except DiscoveryError as exc:
            last_error = exc
    if page is None:
        return [f"official website target check failed after {TARGET_FETCH_ATTEMPTS} attempts: {last_error}"]
    haystack = f"{page.title} {page.site_name} {page.text}"
    accepted, _ = match_terms(haystack, (), DEFAULT_AGENCY_EXCLUDE_TERMS)
    if not accepted:
        return ["target appears to be a web/design/development/app/software/UX/marketing/advertising/SEO/digital agency or comparable provider"]
    return []


def _quarantine_live_rows(service, spreadsheet_id: str, failures: list[tuple[int, list[str]]]) -> None:
    data = []
    for row_number, row_errors in failures:
        reason = "live target preflight blocked: " + "; ".join(row_errors)
        data.extend([
            {"range": f"{QUEUE_SHEET}!N{row_number}", "values": [["manual_review"]]},
            {"range": f"{QUEUE_SHEET}!O{row_number}", "values": [["target_recheck_blocked"]]},
            {"range": f"{QUEUE_SHEET}!Y{row_number}", "values": [[reason[:2000]]]},
        ])
    if data:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "RAW", "data": data},
        ).execute()


def process() -> int:
    settings = Settings.from_env()
    service = build_sheets_service()
    headers, rows = rows_from_values(get_values(service, settings.spreadsheet_id, QUEUE_SHEET))
    ensure_expected_headers(headers, QUEUE_HEADERS + ["compliance_basis"], QUEUE_SHEET)
    client = BoundedHttpClient(timeout=8.0, max_bytes=HARD_MAX_BYTES, min_interval=0.25)
    postal_address = os.getenv("OUTREACH_POSTAL_ADDRESS", "")
    live_mode = os.getenv("OUTREACH_MODE", "validate").strip().casefold() == "live"
    errors: list[str] = []
    failures: list[tuple[int, list[str]]] = []
    checked = valid = 0
    for row_number, row in enumerate(rows, start=2):
        if str(row.get("status", "")).strip().casefold() not in LIVE_CANDIDATE_STATUSES:
            continue
        checked += 1
        if checked > 50:
            errors.append("OutreachQueue approved target preflight exceeds hard cap of 50 rows")
            break
        row_errors = metadata_errors(row, postal_address=postal_address)
        if not row_errors:
            row_errors.extend(website_target_errors(row, client))
        if row_errors:
            failures.append((row_number, row_errors))
            errors.extend(f"{QUEUE_SHEET} row {row_number}: {error}" for error in row_errors)
        else:
            valid += 1
    if checked > 50:
        for error in errors[:50]: print("target_evidence_error=" + error)
        print(f"OUTREACH_TARGET_EVIDENCE_PREFLIGHT=blocked checked={checked} invalid={len(errors)}")
        return 2
    if failures and live_mode:
        _quarantine_live_rows(service, settings.spreadsheet_id, failures)
        for error in errors[:50]: print("target_evidence_quarantined=" + error)
        if valid < 1:
            print(f"OUTREACH_TARGET_EVIDENCE_PREFLIGHT=blocked checked={checked} quarantined={len(failures)} valid=0")
            return 2
        print(f"OUTREACH_TARGET_EVIDENCE_PREFLIGHT=green checked={checked} quarantined={len(failures)} valid={valid}")
        return 0
    if errors:
        for error in errors[:50]: print("target_evidence_error=" + error)
        print(f"OUTREACH_TARGET_EVIDENCE_PREFLIGHT=blocked checked={checked} invalid={len(errors)}")
        return 2
    print(f"OUTREACH_TARGET_EVIDENCE_PREFLIGHT=green checked={checked} valid={valid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(process())