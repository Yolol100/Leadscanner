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
from ipaddress import ip_address
from urllib.parse import urlparse
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
MIN_FINDINGS = 2
MAX_FINDINGS = 3
# Exact per-100-contact approval ceilings from the read-only twelve-batch
# audit (11 baseline jobs + the separately proven repaired batch 11).
# New findings after re-crawling never expand the user-approved 53 drafts.
AUDITED_REVIEW_CEILINGS = {
    0: 0, 100: 1, 200: 1, 300: 3, 400: 9, 500: 7,
    600: 3, 700: 4, 800: 10, 900: 4, 1000: 8, 1100: 3,
}
STATUSES = (
    "excluded_history", "hold_source_status", "hold_missing_website",
    "hold_missing_business_identity", "hold_duplicate_website", "hold_website_verification",
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
    """Pure site-hint filter. DNS/robots checks happen at the actual request.

    Enumerating all 1,128 source rows twelve times must not perform tens of
    thousands of preflight DNS queries. The normal website crawler still calls
    is_public_http_url on every requested/redirected URL and enforces robots.
    """
    raw = _string(value)
    if not raw or len(raw) > 1500:
        return ""
    url = raw if "://" in raw else "https://" + raw
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").strip().casefold().rstrip(".")
        port = parsed.port
        if (parsed.scheme.casefold() not in {"http", "https"}
                or parsed.username is not None or parsed.password is not None
                or not host or "%" in host
                or port not in {None, 80, 443}
                or host == "localhost"
                or host.endswith((".localhost", ".local", ".internal", ".lan",
                                  ".home", ".home.arpa"))
                or not normalize_domain(url)):
            return ""
        try:
            address = ip_address(host)
        except ValueError:
            address = None
        if address is not None:
            return url if address.is_global else ""
        if "." not in host or any(not x for x in host.split(".")):
            return ""
        host.encode("idna")
    except (ValueError, UnicodeError, TypeError):
        return ""
    # NO network request at this point. verify_candidate.safe_fetch_html()
    # independently validates public DNS answers before opening any URL.
    return url


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


def historical_brand_hint(row: dict, site: str, history: dict | None = None) -> str:
    """Bounded website-research hint when a provider company label is absent.

    The historical source must independently link this exact domain to its
    contact (verified first-party snapshot, or matching corporate mail domain).
    The *current* page must still corroborate the brand in visible content.
    This is not evidence of a new person, recipient or business to acquire.
    """
    domain = normalize_domain(site)
    if not domain:
        return ""
    payload = _source_payload(row)
    old_official = False
    for prefix in ("leadscanner_site_refresh_", "leadscanner_site_candidate_"):
        evidence = _public_site(payload.get(prefix + "evidence_url"))
        if (_string(payload.get(prefix + "source_type")) == "official_site"
                and normalize_domain(payload.get(prefix + "official_domain")) == domain
                and evidence and normalize_domain(evidence) == domain):
            old_official = True
            break
    original_email = normalize_email(row.get("email"))
    mail_domain = original_email.rsplit("@", 1)[-1] if original_email else ""
    company_domain = normalize_domain(row.get("company_domain"))
    same_corporate_domain = mail_domain == company_domain == domain
    # The public HMAC-v2 registry already classifies exactly 146 historical
    # business domains independently. All other provider domains (including
    # previously unseen shared mailbox services) must remain held.
    known_corporate = bool(
        history and isinstance(history.get("v2_key"), bytes)
        and token(history["v2_key"], "corporate", domain)
        in (history.get("v2_corporate") or set())
    )
    if not old_official and not (same_corporate_domain and known_corporate):
        return ""
    label = domain.split(".", 1)[0].replace("-", " ").strip()
    if label.casefold() in {"www", "shop", "store", "online", "portal", "contact", "website"}:
        return ""
    return label if 5 <= len(label) <= 70 and any(c.isalpha() for c in label) else ""


def excluded_history(row: dict) -> bool:
    """Previous contact, opt-out, bounce and replies stay excluded."""
    status = row.get("status")
    if status in (-1, -2, -3, 2, 3):
        return True
    for field in (
        "timestamp_last_contact", "timestamp_last_reply",
        "timestamp_last_open", "timestamp_last_click",
        "last_step_timestamp_executed", "timestamp_last_touch",
    ):
        if _string(row.get(field)):
            return True
    summary = row.get("status_summary")
    if isinstance(summary, dict):
        last = summary.get("lastStep")
        if isinstance(last, dict) and _string(last.get("timestamp_executed")):
            return True
    subseq = row.get("status_summary_subseq")
    if isinstance(subseq, dict) and _string(subseq.get("timestampExecuted")):
        return True
    # Opens/clicks and non-zero interest states imply that mail or a reply
    # happened, even when the provider omits the last-contact timestamp.
    for field in ("email_open_count", "email_reply_count", "email_click_count"):
        try:
            if int(row.get(field) or 0) > 0:
                return True
        except (ValueError, TypeError):
            return True
    for field in ("email_opened_step", "email_replied_step", "email_clicked_step"):
        if row.get(field) is not None:
            return True
    try:
        if int(row.get("lt_interest_status") or 0) != 0:
            return True
    except (ValueError, TypeError):
        return True
    return False


def historical_registry_hold(identity: dict, ordinary: list[dict], *, original_email: str = "") -> bool:
    """Keep all non-draft historical registry states excluded.

    Only prior *concept* entries can be reviewed for replacement proposals.
    This does not turn them into new leads or permit prior sent/opt-out contacts.
    """
    if not ordinary:
        return False
    for row in ordinary:
        matched = match_candidate(identity, [row])
        if not matched:
            continue
        status = _string(matched.get("registry_status")).casefold()
        if ("email" in (matched.get("matched_by") or [])
                and original_email
                and normalize_email(identity.get("email")) != original_email):
            return True
        if status not in {"concept", "review_draft", "draft"}:
            return True
    return False


def build_batch(
    *, offset: int, rows: list[dict], history: dict,
    ordinary: list[dict] | None = None,
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

    ordinary = ordinary or []
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
        if (excluded_history(row)
                or historical_registry_hold(
                    {"email": email, "website": historical_site(row),
                     "company": historical_name(row)}, ordinary,
                    original_email=email,
                )):

            states[pos] = "excluded_history"
            continue
        if row.get("status") != 1:
            states[pos] = "hold_source_status"
            continue
        site = historical_site(row)
        company = historical_name(row)
        derived_brand = False
        if site and not company:
            company = historical_brand_hint(row, site, history)
            derived_brand = bool(company)
        if not site:
            states[pos] = "hold_missing_website"
            continue
        if not company:
            states[pos] = "hold_missing_business_identity"
            continue
        if home_owner.get(normalize_domain(site)) != pos:
            states[pos] = "hold_duplicate_website"
            continue
        verify_rows.append({
            "historical_position": pos,
            "name_hint": company,
            "website_hint": site,
            "category_hint": "",
            "historical_brand_derived": derived_brand,
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
        if candidate.get("historical_brand_derived"):
            # A brand inferred from the domain is not independently verified
            # by that same domain. Require fresh, visible first-party text.
            evidence = candidate.get("identity_evidence") or []
            if not any(str(reason).startswith((
                "full_company_name_on_site", "brand_tokens_on_site"
            )) for reason in evidence):
                states[pos] = "hold_website_verification"
                continue
            counts["derived_brand_confirmed_live"] += 1
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
        counts["websites_with_two_to_three_findings"] += 1
        if (candidate.get("contact_status") != "verified_official_site"
                or not _string(candidate.get("public_business_email"))
                or not _string(candidate.get("email_source_url"))):
            states[pos] = "hold_unverified_contact"
            continue
        domain = normalize_domain(candidate.get("official_domain"))
        contact = normalize_email(candidate.get("public_business_email"))
        original_email = normalize_email(indexed[pos].get("email"))
        another_historical_identity = (
            contact != original_email
            and token(history["v2_key"], "email", contact)
            in history["v2_emails"]
        )
        if (another_historical_identity
                or historical_registry_hold(
                    {"email": contact, "website": candidate.get("official_url"),
                     "company": candidate.get("name_hint")}, ordinary,
                    original_email=original_email,
                )):
            states[pos] = "excluded_history"
            continue
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
        generated["_historical_source_email_token"] = token(
            history["v2_key"], "email",
            normalize_email(indexed[pos].get("email"))
        )
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
    original_tokens = {
        normalize_email(candidate["public_business_email"]):
        candidate["_historical_source_email_token"]
        for candidate in ready_candidates
    }
    for record in review_batch["rows"]:
        address = normalize_email(record["email"])
        record["lead_id"] = "growth-" + token(
            key, "email", address
        )[:20]
        record["_historical_source_email_token"] = original_tokens[address]
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
                "webpages_fetched", "websites_with_two_to_three_findings",
                "mail_quality_evaluated", "derived_brand_confirmed_live",
            )},
        },
        "emails_sent": 0,
        "registry_mutated": False,
        "provider_mutated": False,
        "drafts_replaced": 0,
        "source_leaks": False,
    }
    return public, review_batch


def require_fresh_registry_before_imap(
    batch: dict, previous_history: dict, fresh_registry: list[dict],
) -> None:
    """Fail closed if a blocked identity changed while sites were crawled."""
    historical = [
        row for row in fresh_registry
        if row.get("status") == "historical_v2_suppression"
    ]
    if (len(historical) != 1
            or historical[0].get("v2_key") != previous_history.get("v2_key")
            or len(historical[0].get("v2_emails") or ()) != EXPECTED):
        raise RuntimeError("fresh_historical_registry_changed")
    fresh = historical[0]
    ordinary = [
        row for row in fresh_registry
        if row.get("status") != "historical_v2_suppression"
    ]
    for row in batch.get("rows") or []:
        if row.get("status") != "review_draft" or row.get("automatic_send") is not False:
            raise RuntimeError("fresh_draft_status_invalid")
        source_hash = _string(row.get("_historical_source_email_token"))
        if not source_hash or source_hash not in fresh["v2_emails"]:
            raise RuntimeError("fresh_original_email_missing")
        selected_email = normalize_email(row.get("email"))
        fresh_email_hash = token(fresh["v2_key"], "email", selected_email)
        if fresh_email_hash in fresh["v2_emails"] and fresh_email_hash != source_hash:
            raise RuntimeError("fresh_other_historical_recipient")
        identity = {
            "email": selected_email,
            "website": row.get("website"),
            "company": row.get("company"),
            "official_domain": row.get("official_domain"),
        }
        for entry in ordinary:
            found = match_candidate(identity, [entry])
            if not found:
                continue
            old_status = _string(found.get("registry_status")).casefold()
            if old_status not in {"concept", "review_draft", "draft"}:
                raise RuntimeError("fresh_registry_existing_exclusion")
            if ("email" in (found.get("matched_by") or [])
                    and fresh_email_hash != source_hash):
                raise RuntimeError("fresh_other_existing_concept")


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
    report, review_batch = build_batch(
        offset=offset, rows=rows, history=history_rows[0],
        ordinary=[r for r in registry if r.get("status") != "historical_v2_suppression"],
    )
    report["mode"] = mode
    report["drafts_created"] = 0
    report["drafts_exact_existing"] = 0
    if mode == "drafts":
        cap = AUDITED_REVIEW_CEILINGS.get(offset)
        if (cap is None or len(review_batch["rows"]) > cap
                or report["counts"]["ready_for_review"] > cap):
            raise RuntimeError("historical_approved_count_exceeded")
    if mode == "drafts" and review_batch["rows"]:
        if (os.getenv("LEADSCANNER_TRUSTED_HISTORICAL_WRITE") != "true"
                or not os.getenv("OUTREACH_MAIL_PASSWORD")):
            raise RuntimeError("trusted_main_required")
        # Current dedupe may have changed during website research. Read it
        # again immediately before any mailbox write; never trust stale holds.
        require_fresh_registry_before_imap(
            review_batch, history_rows[0], fetch_registry()
        )
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


def safe_failure_marker(error: BaseException) -> str:
    """Return ONLY source-code identifiers, never exception text or traceback.

    Exception messages and locals may contain recipient names, URLs or email
    copy. This allows debugging a failed historical batch on a public runner
    without publishing any such data.
    """
    safe_modules = {
        "_once_historical_site_redraft.py": "history",
        "_once_historical_source_diagnose.py": "source",
        "leadscanner_core.py": "registry",
        "historical_v2.py": "dedupe",
        "dedupe_preflight.py": "matching",
        "cold_stages.py": "website",
        "first_party_contacts.py": "contact",
        "site_crawl.py": "robots",
        "url_safety.py": "url_policy",
        "outreach_stages.py": "copy",
        "review_draft_stages.py": "draft_validation",
    }
    safe_types = {
        "ValueError": "value_error", "KeyError": "missing_key",
        "TypeError": "type_error", "AttributeError": "attribute_error",
        "IndexError": "index_error", "RuntimeError": "runtime_error",
        "AssertionError": "assertion_error", "OverflowError": "overflow_error",
        "UnicodeError": "unicode_error",
    }
    origin = "unclassified"
    trace = error.__traceback__
    while trace is not None:
        filename = str(trace.tb_frame.f_code.co_filename).replace("\\\\", "/").rsplit("/", 1)[-1]
        if filename in safe_modules:
            lineno = trace.tb_lineno
            origin = (safe_modules[filename] + "_line_" + str(lineno)
                      if isinstance(lineno, int) and 0 < lineno < 5000
                      else safe_modules[filename])
        trace = trace.tb_next
    return "origin=" + origin + " type=" + safe_types.get(
        type(error).__name__, "other_failure"
    )


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
            "fresh_historical_registry_changed", "fresh_draft_status_invalid",
            "fresh_original_email_missing", "fresh_other_historical_recipient",
            "fresh_registry_existing_exclusion", "fresh_other_existing_concept",
            "historical_approved_count_exceeded",
        }
        code = str(error) if str(error) in fixed else "private_failure_hold"
        print("HISTORICAL_SITE_REBUILD=red stage=" + code + " " + safe_failure_marker(error) + " details_suppressed")
        return 1
    print("HISTORICAL_SITE_REBUILD=green "
          + json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
