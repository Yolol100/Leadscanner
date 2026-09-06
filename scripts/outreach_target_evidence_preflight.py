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
from prospect_discovery import BoundedHttpClient, DiscoveryError, host_key, match_terms, normalize_url, parse_page, root_url
from prospect_target_policy import DEFAULT_AGENCY_EXCLUDE_TERMS, canonical_country, is_excluded_domain

EVIDENCE_PREFIX = "website_scan:"
POSTAL_PLACEHOLDER = "{{OUTREACH_POSTAL_ADDRESS}}"
LIVE_CANDIDATE_STATUSES = {"approved"}
UK_CORPORATE_SUFFIX_RE = re.compile(r"(?i)\b(?:ltd\.?|limited|llp|plc)\b")


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _same_domain(left: str, right: str) -> bool:
    left_url = normalize_url(left, require_path=True)
    right_url = normalize_url(right, require_path=True)
    return bool(left_url and right_url and host_key(left_url) == host_key(right_url))


def parse_evidence_source(raw: object) -> dict[str, str]:
    value = str(raw or "").strip()
    if not value.startswith(EVIDENCE_PREFIX):
        raise ValueError("source must start with website_scan:")
    payload = value[len(EVIDENCE_PREFIX):].strip()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("website_scan source must contain valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("website_scan source payload must be an object")
    return {str(key): str(item or "").strip() for key, item in data.items()}


def metadata_errors(row: dict[str, str], *, postal_address: str = "") -> list[str]:
    errors: list[str] = []
    country = canonical_country(row.get("country", ""))
    website = row.get("website", "")
    if not normalize_url(website, require_path=True):
        errors.append("missing or invalid official website")
        return errors
    if is_excluded_domain(website):
        errors.append("Webactueel/self domain is excluded from prospect outreach")
    try:
        evidence = parse_evidence_source(row.get("source", ""))
    except ValueError as exc:
        errors.append(str(exc))
        return errors

    evidence_url = evidence.get("evidence_url", "")
    fact = _text(evidence.get("fact", ""))
    idea = _text(evidence.get("idea", ""))
    body_text = _text(row.get("body", ""))
    if not evidence_url or not _same_domain(website, evidence_url):
        errors.append("website_scan evidence_url must be on the official prospect domain")
    if len(fact) < 15:
        errors.append("website_scan fact must contain a concise evidence-bound company fact")
    elif fact.casefold() not in body_text.casefold():
        errors.append("mail body must contain the exact website_scan fact")
    if len(idea) < 20:
        errors.append("website_scan idea must contain a concrete evidence-bound improvement")
    elif idea.casefold() not in body_text.casefold():
        errors.append("mail body must contain the exact website_scan idea")

    analysis_type = evidence.get("analysis_type", "").casefold()
    if analysis_type not in {"website", "webshop"}:
        errors.append("website_scan analysis_type must be website or webshop")

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
    try:
        page = parse_page(client.fetch_text(website), website)
    except DiscoveryError as exc:
        return [f"official website target check failed: {exc}"]
    haystack = f"{page.title} {page.site_name} {page.text}"
    accepted, _ = match_terms(haystack, (), DEFAULT_AGENCY_EXCLUDE_TERMS)
    if not accepted:
        return ["target appears to be a web/design/development/app/software/UX/marketing/advertising/SEO/digital agency or comparable provider"]
    return []


def process() -> int:
    settings = Settings.from_env()
    service = build_sheets_service()
    headers, rows = rows_from_values(get_values(service, settings.spreadsheet_id, QUEUE_SHEET))
    ensure_expected_headers(headers, QUEUE_HEADERS + ["compliance_basis"], QUEUE_SHEET)

    client = BoundedHttpClient(
        timeout=8.0,
        max_bytes=524_288,
        min_interval=0.25,
    )
    postal_address = os.getenv("OUTREACH_POSTAL_ADDRESS", "")
    errors: list[str] = []
    checked = 0
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
        for error in row_errors:
            errors.append(f"{QUEUE_SHEET} row {row_number}: {error}")

    if errors:
        for error in errors[:50]:
            print("target_evidence_error=" + error)
        print(f"OUTREACH_TARGET_EVIDENCE_PREFLIGHT=blocked checked={checked} invalid={len(errors)}")
        return 2
    print(f"OUTREACH_TARGET_EVIDENCE_PREFLIGHT=green checked={checked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(process())
