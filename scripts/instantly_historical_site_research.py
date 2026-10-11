"""Bounded first-party research of historical, isolated Instantly draft contacts.

Email domain is a discovery hint, never proof of company identity or permission.
Only a website visibly publishing the *exact* recipient address may produce a
candidate observation. Results are held for human review in separate custom
variables; existing reviewed mail, live merge variables and legal basis do not
change. Public command artifacts contain aggregate counts only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from instantly_site_crawl import PoliteSiteSession
from cold_stages import (
    CONTACT_HINTS, broad_research_links, evidence_sentences,
    PUBLIC_MAIL_DOMAINS, extract_emails, internal_links, normalize_domain, page_type_for_url,
    parse_html, safe_fetch_html,
)
from instantly_language_campaigns import inspect_lead_language, read_imported_leads
from instantly_language_route import HOLD_FREE_MAIL
from instantly_signature_repair import _campaigns_still_quiet
from myhost_instantly_import import TARGET_LIST_ID
from outreach_stages import select_one_reason, value_action_for, draft_for_review

EXPECTED_SOURCE_COUNT = 1128
BATCH_SIZE = 100
MAX_WORKERS = 100
UUID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
REVIEW_KEYS = (
    "leadscanner_site_candidate_findings",
    "leadscanner_site_candidate_observation",
    "leadscanner_site_candidate_value_action",
    "leadscanner_site_candidate_subject",
    "leadscanner_site_candidate_body",
    "leadscanner_site_candidate_evidence_url",
    "leadscanner_site_candidate_source_type",
    "leadscanner_site_candidate_signal_type",
    "leadscanner_site_candidate_contact_url",
    "leadscanner_site_candidate_official_domain",
    "leadscanner_site_candidate_checked_date",
    "leadscanner_site_research_status",
)
LIVE_KEYS = (
    "leadscanner_observation", "leadscanner_value_action",
    "leadscanner_evidence_url", "leadscanner_evidence_source_type",
)
ILLEGAL_MARKUP = ("{{", "}}", "{%", "%}", "\x00")


def _text(value: object) -> str:
    return str(value or "").strip()


def _custom(row: dict) -> dict:
    raw = row.get("payload")
    if not isinstance(raw, dict):
        raw = row.get("custom_variables")
    if not isinstance(raw, dict):
        raise RuntimeError("site_research_missing_source_variables")
    return raw


def _source_rows(client, expected_count: int) -> list[dict]:
    list_id, rows = read_imported_leads(client)
    if list_id != TARGET_LIST_ID or len(rows) != expected_count:
        raise RuntimeError("site_research_source_count_or_identity_changed")
    unique_ids = set()
    for row in rows:
        lead_id = _text(row.get("id"))
        if (
            not UUID.fullmatch(lead_id) or lead_id in unique_ids
            or row.get("list_id") != TARGET_LIST_ID
        ):
            raise RuntimeError("site_research_source_identity_invalid")
        unique_ids.add(lead_id)
    return sorted(rows, key=lambda row: row["id"])


def _email_and_domain(row: dict) -> tuple[str, str] | None:
    email = _text(row.get("email")).casefold()
    if email.count("@") != 1 or any(c.isspace() for c in email):
        return None
    domain = email.rsplit("@", 1)[1]
    if not domain or domain.startswith(".") or domain.endswith("."):
        return None
    if not re.fullmatch(r"[a-z0-9.-]{4,255}", domain) or "." not in domain:
        return None
    return email, domain


def _fetch_home(session, domain: str, website_hint: str) -> tuple[str | None, str | None]:
    # Only trust an explicitly supplied URL if it is on the same email domain.
    # Cross-domain website hints would need separate independent identity proof.
    candidate = "https://" + domain + "/"
    if website_hint and normalize_domain(website_hint) == normalize_domain(candidate):
        parsed = urlparse(website_hint if "://" in website_hint else "https://" + website_hint)
        if parsed.scheme in {"https", "http"} and not parsed.username and not parsed.password:
            candidate = parsed.geturl()
    expected = normalize_domain(candidate)
    for url in (candidate, "http://" + domain + "/"):
        html, final_url, _ = safe_fetch_html(session, url, expected)
        if html and final_url:
            return html, final_url
    return None, None


def _scan_site(row: dict) -> dict:
    values = _custom(row)
    address = _email_and_domain(row)
    if address is None:
        return {"status": "invalid_email"}
    email, domain = address
    if domain in HOLD_FREE_MAIL | PUBLIC_MAIL_DOMAINS:
        return {"status": "personal_email_domain"}
    if (
        values.get("leadscanner_import_origin") != "myhost_drafts"
        or values.get("leadscanner_contact_basis") != "review_required"
        or row.get("campaign") is not None
    ):
        return {"status": "source_not_review_required"}
    if any(_text(values.get(key)) for key in LIVE_KEYS):
        return {"status": "existing_live_observation_hold"}
    if any(_text(values.get(key)) for key in REVIEW_KEYS):
        return {"status": "existing_research_hold"}

    hint = _text(row.get("website") or values.get("website"))
    with requests.Session() as raw_session:
        session = PoliteSiteSession(raw_session, domain)
        html, url = _fetch_home(session, domain, hint)
        if not html or not url:
            return {"status": "unreachable_website"}
        parsed = parse_html(html)
        confirmed_page = url if email in extract_emails(parsed) else None
        contact_parsed = []
        home_domain = normalize_domain(url)
        if not confirmed_page:
            for link in internal_links(parsed, url, home_domain, CONTACT_HINTS, limit=10):
                linked_html, linked_url, _ = safe_fetch_html(session, link, home_domain)
                if not linked_html or not linked_url:
                    continue
                linked_parsed = parse_html(linked_html)
                contact_parsed.append((linked_url, linked_parsed))
                if email in extract_emails(linked_parsed):
                    confirmed_page = linked_url
                    break
        if not confirmed_page:
            return {"status": "recipient_not_confirmed_on_website"}

        # Read a bounded, diverse set of public pages before prioritizing observations.
        evidence = []
        for link in broad_research_links(parsed, url, home_domain, limit=15):
            linked_html, linked_url, _ = safe_fetch_html(session, link, home_domain)
            if linked_html and linked_url:
                linked = parse_html(linked_html)
                evidence.extend(evidence_sentences(
                    linked.get("text") or "", linked_url, page_type_for_url(linked_url),
                ))
        for contact_url, contact in contact_parsed:
            evidence.extend(evidence_sentences(contact.get("text") or "", contact_url, "process"))
        evidence.extend(evidence_sentences(parsed.get("text") or "", url, "home"))
        result = select_one_reason({
            "research_status": "ready" if evidence else "hold_no_evidence",
            "official_domain": home_domain,
            "evidence_candidates": evidence,
        })
        if result.get("outreach_status") != "ready":
            return {"status": "no_specific_first_party_signal"}
        # Never make an NL email based on an EN site observation, or vice versa.
        if inspect_lead_language(row) != result.get("language"):
            return {"status": "observation_language_mismatch"}
        proposal = value_action_for(result)
        if proposal.get("value_action_status") != "proposed":
            return {"status": "no_relevant_action"}
        observation = _text(proposal.get("verified_observation"))
        action = _text(proposal.get("value_first_action"))
        evidence_url = _text(proposal.get("verified_observation_source_url"))
        if (
            not observation or not action or not evidence_url
            or len(observation) > 280 or len(action) > 200
            or any(fragment in observation + action for fragment in ILLEGAL_MARKUP)
            or normalize_domain(evidence_url) != home_domain
            or normalize_domain(confirmed_page) != home_domain
        ):
            return {"status": "unsafe_or_unbound_candidate"}
        findings = result.get("selected_findings") or []
        subject, body = draft_for_review(
            observation, action, _text(proposal.get("signal_type")),
            _text(result.get("language")), findings,
        )
        if not subject or not body:
            return {"status": "draft_quality_hold"}
        return {
            "status": "candidate",
            "proposal": {
                "leadscanner_site_candidate_findings": json.dumps(findings, ensure_ascii=False, separators=(",", ":")),
                "leadscanner_site_candidate_observation": observation,
                "leadscanner_site_candidate_value_action": action,
                "leadscanner_site_candidate_subject": subject,
                "leadscanner_site_candidate_body": body,
                "leadscanner_site_candidate_evidence_url": evidence_url,
                "leadscanner_site_candidate_source_type": "official_site",
                "leadscanner_site_candidate_signal_type": _text(proposal.get("signal_type")),
                "leadscanner_site_candidate_contact_url": confirmed_page,
                "leadscanner_site_candidate_official_domain": home_domain,
                "leadscanner_site_candidate_checked_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "leadscanner_site_research_status": "candidate_review_required",
            },
        }


def _save_candidate(client, row: dict, proposal: dict, *, sleep_fn=time.sleep) -> None:
    lead_id = row["id"]
    before = client.get_lead(lead_id)
    if (
        not isinstance(before, dict)
        or _text(before.get("id")) != lead_id
        or _text(before.get("email")).casefold() != _text(row.get("email")).casefold()
        or before.get("list_id") != TARGET_LIST_ID
        or before.get("campaign") is not None
    ):
        raise RuntimeError("site_research_prewrite_lead_identity_changed")
    original = _custom(row)
    actual = _custom(before)
    if actual != original:
        raise RuntimeError("site_research_prewrite_variables_changed")
    if (
        actual.get("leadscanner_contact_basis") != "review_required"
        or any(_text(actual.get(key)) for key in REVIEW_KEYS + LIVE_KEYS)
    ):
        raise RuntimeError("site_research_prewrite_review_state_changed")
    new_variables = dict(actual)
    new_variables.update(proposal)
    # Never retry a write with an uncertain response. The provider owns the data.
    try:
        client._request("PATCH", "/leads/" + lead_id, json={"custom_variables": new_variables})
    except Exception:
        raise RuntimeError("site_research_patch_outcome_unknown_reconcile_before_retry") from None
    for attempt in range(7):
        after = client.get_lead(lead_id)
        if not isinstance(after, dict) or (
            after.get("id") != lead_id
            or _text(after.get("email")).casefold() != _text(row.get("email")).casefold()
            or after.get("list_id") != TARGET_LIST_ID or after.get("campaign") is not None
        ):
            raise RuntimeError("site_research_postwrite_recipient_changed")
        if (
            _custom(after) == new_variables
            and after.get("status") == before.get("status")
            and after.get("lt_interest_status") == before.get("lt_interest_status")
        ):
            return
        if attempt < 6:
            sleep_fn((0.4, 0.6, 1, 1.5, 2, 3)[attempt])
    raise RuntimeError("site_research_postwrite_readback_unconfirmed")


def research_imported_sites_batch(
    client, *, offset: int, expected_count: int = EXPECTED_SOURCE_COUNT,
    save_candidates: bool = False, workers: int = MAX_WORKERS,
    scanner=_scan_site,
) -> dict:
    if type(offset) is not int or offset < 0 or offset % BATCH_SIZE:
        raise ValueError("site_research_offset_must_be_multiple_of_100")
    if type(expected_count) is not int or expected_count != EXPECTED_SOURCE_COUNT:
        raise ValueError("site_research_expected_source_count_invalid")
    if type(workers) is not int or not 1 <= workers <= MAX_WORKERS:
        raise ValueError("site_research_worker_limit_invalid")
    if type(save_candidates) is not bool:
        raise ValueError("site_research_save_flag_invalid")
    _campaigns_still_quiet(client)
    rows = _source_rows(client, expected_count)
    if offset >= len(rows):
        raise ValueError("site_research_offset_outside_source")
    batch = rows[offset:offset + BATCH_SIZE]

    # Network reads in bounded parallel; never expose unsafe provider/site exceptions.
    def scan_one(row: dict) -> dict:
        try:
            return scanner(row)
        except Exception:
            return {"status": "site_scan_exception"}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(scan_one, batch))
    counts = Counter()
    saved = 0
    allowed_statuses = frozenset({
        "candidate", "invalid_email", "personal_email_domain",
        "source_not_review_required", "existing_live_observation_hold",
        "existing_research_hold", "unreachable_website",
        "recipient_not_confirmed_on_website", "no_specific_first_party_signal",
        "observation_language_mismatch", "no_relevant_action",
        "unsafe_or_unbound_candidate", "draft_quality_hold", "site_scan_exception", "invalid_scan",
    })
    for row, outcome in zip(batch, outcomes):
        status = _text(outcome.get("status")) if isinstance(outcome, dict) else "invalid_scan"
        if status not in allowed_statuses:
            raise RuntimeError("site_research_unknown_scanner_status")
        if status == "candidate":
            proposal = outcome.get("proposal") if isinstance(outcome, dict) else None
            expected_keys = set(REVIEW_KEYS)
            legacy_keys = expected_keys - {"leadscanner_site_candidate_findings"}
            if not isinstance(proposal, dict) or set(proposal) not in (expected_keys, legacy_keys):
                raise RuntimeError("site_research_candidate_contract_invalid")
            counts["candidates_found"] += 1
            if save_candidates:
                _save_candidate(client, row, proposal)
                saved += 1
        else:
            counts[status or "invalid_scan"] += 1
    _campaigns_still_quiet(client)
    return {
        "schema_version": "leadscanner-historical-site-research/1.0",
        "source_count": len(rows),
        "source_list_id": TARGET_LIST_ID,
        "batch_offset": offset,
        "batch_size": len(batch),
        "network_checked_count": len(batch) - counts["personal_email_domain"] - counts["invalid_email"] - counts["source_not_review_required"] - counts["existing_live_observation_hold"] - counts["existing_research_hold"],
        "candidate_count": counts["candidates_found"],
        "saved_candidate_count": saved,
        "holds": {key: value for key, value in sorted(counts.items()) if key != "candidates_found"},
        "save_candidates": save_candidates,
        "contact_basis_changes": 0,
        "reviewed_copy_changes": 0,
        "live_merge_field_changes": 0,
        "campaign_lead_changes": 0,
        "campaign_sender_changes": 0,
        "automatic_send": False,
        "prospect_addresses_or_evidence_in_public_result": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, required=True)
    parser.add_argument("--expected-count", type=int, default=EXPECTED_SOURCE_COUNT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--save-candidates", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    key = os.environ.get("INSTANTLY_API_KEY", "")
    if not key:
        raise SystemExit("site_research_instantly_key_missing")
    from instantly_client import InstantlyClient
    from instantly_control import _redact_sensitive
    try:
        result = research_imported_sites_batch(
            InstantlyClient(key), offset=args.offset, expected_count=args.expected_count,
            workers=args.workers, save_candidates=args.save_candidates,
        )
    except Exception:
        # The true exception may contain private provider or prospect data.
        raise SystemExit("site_research_batch_failed_reconciliation_required") from None
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_redact_sensitive(result), sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("SITE_RESEARCH_BATCH=green "
          f"offset={args.offset} checked={result['batch_size']} "
          f"candidate={result['candidate_count']} saved={result['saved_candidate_count']} "
          f"hold={sum(result['holds'].values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
