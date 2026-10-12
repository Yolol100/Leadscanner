"""One-time, source-read-only historical website re-review.

The historical list is *not* a new-lead queue. Every source email must match
the existing independent HMAC-v2 exclusions. Site research and mail validation
are independent of historical copy, and no campaign or SMTP surface is used.

Only anonymous fixed counters leave the runner. This file and its workflows
are disposable after successful complete reconciliation.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
import sys

from _once_historical_source_diagnose import (
    EXPECTED, FATAL_KEYS, classify, read_source,
)
from cold_stages import (
    PUBLIC_MAIL_DOMAINS, research_candidates, verify_candidates,
)
from dedupe_preflight import match_candidate, normalize_domain, normalize_email
from historical_v2 import token
from leadscanner_core import fetch_registry
from outreach_stages import (
    finding_excerpt, generate_one_mail, review_findings, select_one_reason,
    value_action_for,
)
from review_draft_stages import audit_exact_readback, prepare_review_batch
from url_safety import is_public_http_url

BATCH_SIZE = 100
MIN_FINDINGS = 4
MAX_FINDINGS = 6
STATUSES = (
    "excluded_history", "hold_source_status", "hold_missing_website",
    "hold_duplicate_website", "hold_website_verification",
    "hold_website_research", "hold_insufficient_findings",
    "hold_unverified_contact", "hold_mail_validation",
    "hold_duplicate_recipient", "ready_for_review",
)


def _string(value: object) -> str:
    return str(value or "").strip()


def _source_payload(row: dict) -> dict:
    value = row.get("payload")
    if not isinstance(value, dict):
        value = row.get("custom_variables")
    return value if isinstance(value, dict) else {}


def _public_site(value: object) -> str:
    raw = _string(value)
    if not raw or len(raw) > 1500:
        return ""
    url = raw if "://" in raw else "https://" + raw
    return url if is_public_http_url(url) and normalize_domain(url) else ""


def historical_site(row: dict) -> str:
    """Historical hints are untrusted until current live site verification."""
    payload = _source_payload(row)
    for prefix in ("leadscanner_site_refresh_", "leadscanner_site_candidate_"):
        if _string(payload.get(prefix + "source_type")) != "official_site":
            continue
        domain = normalize_domain(payload.get(prefix + "official_domain"))
        evidence = _public_site(payload.get(prefix + "evidence_url"))
        if domain and evidence and normalize_domain(evidence) == domain:
            return _public_site(domain)
    for item in (
        row.get("website"), payload.get("website"), payload.get("companyWebsite"),
        payload.get("leadscanner_website"),
    ):
        site = _public_site(item)
        if site:
            return site
    company_domain = _string(row.get("company_domain"))
    if company_domain and normalize_domain(company_domain) not in PUBLIC_MAIL_DOMAINS:
        return _public_site(company_domain)
    return ""


def historical_name(row: dict) -> str:
    payload = _source_payload(row)
    # Never infer a business name from an email local part.
    return (_string(row.get("company_name"))
            or _string(payload.get("companyName"))
            or _string(payload.get("company_name")))[:180]


def excluded_history(row: dict) -> bool:
    """Previous contact, opt-out, bounce and replies stay excluded."""
    status = row.get("status")
    if status in (-1, -2, -3, 2, 3):
        return True
    for field in (
        "timestamp_last_contact", "timestamp_last_reply",
        "last_step_timestamp_executed", "timestamp_last_touch",
    ):
        if _string(row.get(field)):
            return True
    summary = row.get("status_summary")
    if isinstance(summary, dict):
        last = summary.get("lastStep")
        if isinstance(last, dict) and _string(last.get("timestamp_executed")):
            return True
    try:
        if int(row.get("email_reply_count") or 0) > 0:
            return True
    except (ValueError, TypeError):
        return True
    try:
        if int(row.get("lt_interest_status") or 0) < 0:
            return True
    except (ValueError, TypeError):
        return True
    return False


def build_batch(
    *, offset: int, rows: list[dict], history: dict,
    verifier=verify_candidates, researcher=research_candidates,
) -> tuple[dict, dict]:
    """Return safe counters and in-memory review rows; do not write anything."""
    if offset not in range(0, EXPECTED, BATCH_SIZE):
        raise RuntimeError("offset_out_of_bounds")
    summary = classify(rows)
    if len(rows) != EXPECTED or any(summary[k] for k in FATAL_KEYS):
        raise RuntimeError("source_integrity_hold")
    if (history.get("status") != "historical_v2_suppression"
            or not isinstance(history.get("v2_key"), bytes)
            or len(history.get("v2_emails") or ()) != EXPECTED):
        raise RuntimeError("historical_suppression_incomplete")

    # A complete source inventory is required before slicing a batch. Prevent
    # separate historical IDs from creating duplicate outreach for one site.
    indexed = sorted(rows, key=lambda row: _string(row.get("id")).casefold())
    home_owner = {}
    for index, row in enumerate(indexed):
        domain = normalize_domain(historical_site(row))
        if domain and domain not in home_owner:
            home_owner[domain] = index

    window = indexed[offset:offset + BATCH_SIZE]
    expected_size = min(BATCH_SIZE, EXPECTED - offset)
    if len(window) != expected_size:
        raise RuntimeError("batch_incomplete")

    counts = Counter()
    states = {}
    verify_rows = []
    for pos, row in enumerate(window, offset):
        counts["checked"] += 1
        email = normalize_email(row.get("email"))
        matched = match_candidate({"email": email}, [history])
        if not matched or "historical_v2_email" not in matched["matched_by"]:
            raise RuntimeError("historical_suppression_missing")
        counts["historical_email_excluded"] += 1
        if excluded_history(row):
            states[pos] = "excluded_history"
            continue
        if row.get("status") != 1:
            states[pos] = "hold_source_status"
            continue
        site = historical_site(row)
        company = historical_name(row)
        if not site or not company:
            states[pos] = "hold_missing_website"
            continue
        if home_owner.get(normalize_domain(site)) != pos:
            states[pos] = "hold_duplicate_website"
            continue
        verify_rows.append({
            "historical_position": pos,
            "name_hint": company,
            "website_hint": site,
            "category_hint": "",
        })

    verified_rows = []
    if verify_rows:
        verification = verifier(
            {"candidates": verify_rows},
            limit=len(verify_rows), max_workers=8,
        )
        verified_rows = verification.get("candidates") or []
        if len(verified_rows) != len(verify_rows):
            raise RuntimeError("batch_incomplete")
    to_research = []
    for candidate in verified_rows:
        pos = candidate["historical_position"]
        counts["websites_checked"] += 1
        if not candidate.get("ready_for_research"):
            states[pos] = "hold_website_verification"
            continue
        counts["websites_verified"] += 1
        to_research.append(candidate)

    researched_rows = []
    if to_research:
        research = researcher(
            {"candidates": to_research},
            limit=len(to_research), max_workers=6,
        )
        researched_rows = research.get("candidates") or []
        if len(researched_rows) != len(to_research):
            raise RuntimeError("batch_incomplete")

    ready_candidates = []
    selected_domains, selected_emails = set(), set()
    for candidate in researched_rows:
        pos = candidate["historical_position"]
        counts["webpages_fetched"] += int(candidate.get("research_pages_fetched") or 0)
        if candidate.get("research_status") != "ready":
            states[pos] = "hold_website_research"
            continue
        counts["websites_researched"] += 1
        ranked = select_one_reason(candidate)
        findings = ranked.get("selected_findings") or []
        if ranked.get("outreach_status") != "ready" or not MIN_FINDINGS <= len(findings) <= MAX_FINDINGS:
            states[pos] = "hold_insufficient_findings"
            continue
        counts["websites_with_four_to_six_findings"] += 1
        if (candidate.get("contact_status") != "verified_official_site"
                or not _string(candidate.get("public_business_email"))
                or not _string(candidate.get("email_source_url"))):
            states[pos] = "hold_unverified_contact"
            continue
        domain = normalize_domain(candidate.get("official_domain"))
        contact = normalize_email(candidate.get("public_business_email"))
        if (domain in selected_domains or contact in selected_emails):
            states[pos] = "hold_duplicate_recipient"
            continue
        # Review evidence and renderer/validator before IMAP is even available.
        valid = review_findings(findings, domain)
        valued = value_action_for(ranked)
        generated = generate_one_mail(valued)
        counts["mail_quality_evaluated"] += 1
        text_body = _string(generated.get("body"))
        if (generated.get("mail_status") != "ready_for_human_review"
                or generated.get("copy_validation_status") != "green"
                or len(valid) != len(findings)
                or any(finding_excerpt(item) not in text_body for item in valid)):
            states[pos] = "hold_mail_validation"
            continue
        selected_domains.add(domain)
        selected_emails.add(contact)
        ready_candidates.append(generated)
        states[pos] = "ready_for_review"

    if set(states) != set(range(offset, offset + expected_size)):
        raise RuntimeError("batch_incomplete")
    counts.update(states.values())
    if sum(counts[status] for status in STATUSES) != expected_size:
        raise RuntimeError("batch_incomplete")
    review_batch = prepare_review_batch({"candidates": ready_candidates})
    if len(review_batch["rows"]) != counts["ready_for_review"]:
        raise RuntimeError("batch_incomplete")

    # Opaque deterministic IDs for this *historical* rebuild; no new leads
    # are registered. Old IMAP drafts retain their old IDs, are never changed.
    key = history["v2_key"]
    for record in review_batch["rows"]:
        record["lead_id"] = "growth-" + token(
            key, "email", _string(record["email"]).casefold()
        )[:20]
    if len({r["lead_id"] for r in review_batch["rows"]}) != len(review_batch["rows"]):
        raise RuntimeError("batch_incomplete")

    public = {
        "schema": "historical-site-redraft/1.0",
        "offset": offset, "size": expected_size, "expected_total": EXPECTED,
        "counts": {
            **{k: int(counts[k]) for k in STATUSES},
            **{k: int(counts[k]) for k in (
                "checked", "historical_email_excluded", "websites_checked",
                "websites_verified", "websites_researched",
                "webpages_fetched", "websites_with_four_to_six_findings",
                "mail_quality_evaluated",
            )},
        },
        "emails_sent": 0,
        "registry_mutated": False,
        "provider_mutated": False,
        "drafts_replaced": 0,
        "source_leaks": False,
    }
    return public, review_batch


def run(offset: int, mode: str) -> dict:
    if mode not in {"audit", "drafts"}:
        raise RuntimeError("unsupported_mode")
    if offset not in range(0, EXPECTED, BATCH_SIZE):
        raise RuntimeError("offset_out_of_bounds")
    rows, _pages = read_source()
    registry = fetch_registry()
    history_rows = [r for r in registry
                    if r.get("status") == "historical_v2_suppression"]
    if len(history_rows) != 1:
        raise RuntimeError("historical_suppression_incomplete")
    report, review_batch = build_batch(offset=offset, rows=rows, history=history_rows[0])
    report["mode"] = mode
    report["drafts_created"] = 0
    report["drafts_exact_existing"] = 0
    if mode == "drafts" and review_batch["rows"]:
        if (os.getenv("LEADSCANNER_TRUSTED_HISTORICAL_WRITE") != "true"
                or not os.getenv("OUTREACH_MAIL_PASSWORD")):
            raise RuntimeError("trusted_main_required")
        from myhost_draft import create_drafts
        saved = create_drafts(review_batch, reject_changed_existing=True)
        proof = audit_exact_readback(review_batch, saved)
        if (proof.get("status") != "green"
                or proof.get("replaced_count") != 0
                or proof.get("draft_count") != len(review_batch["rows"])):
            raise RuntimeError("imap_readback_incomplete")
        report["drafts_created"] = proof["created_count"]
        report["drafts_exact_existing"] = proof["existing_count"]
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, required=True)
    parser.add_argument("--mode", choices=("audit", "drafts"), required=True)
    args = parser.parse_args()
    try:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            report = run(args.offset, args.mode)
    except Exception as error:
        # Never expose arbitrary exceptions; they may contain site/IMAP data.
        fixed = {
            "source_integrity_hold", "batch_incomplete", "offset_out_of_bounds",
            "historical_suppression_incomplete", "historical_suppression_missing",
            "trusted_main_required", "imap_readback_incomplete",
        }
        code = str(error) if str(error) in fixed else "private_failure_hold"
        print("HISTORICAL_SITE_REBUILD=red stage=" + code + " details_suppressed")
        return 1
    print("HISTORICAL_SITE_REBUILD=green "
          + json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
