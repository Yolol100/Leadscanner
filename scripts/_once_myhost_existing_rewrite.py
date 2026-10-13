"""One-time, explicitly authorized, evidence-first rewrite of EXISTING mijn.host Drafts.

This workflow never discovers a new lead, creates a missing prospect draft,
sends an email, changes its To address, or exports sensitive content.
Every change requires live first-party website evidence and UID-exact readback.
Only anonymous aggregate counters leave the private Actions runner.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
from email.parser import BytesParser
from email.policy import default
from email.utils import getaddresses
from io import StringIO
import json
import os
import re
import sys

from _once_historical_source_diagnose import EXPECTED, FATAL_KEYS, classify, read_source
from _once_historical_site_redraft import (
    excluded_history, historical_brand_hint, historical_name, historical_site,
)
from cold_stages import (
    PUBLIC_MAIL_DOMAINS, research_candidates, verify_candidates,
)
from dedupe_preflight import match_candidate, normalize_domain, normalize_email
from leadscanner_core import fetch_registry
from myhost_draft import (
    connect_imap, create_drafts, exact_message_matches, fetch_message,
    find_drafts_folder, find_message_ids, lead_id_from_message,
    normalize_text, require_draft_flag, review_status_from_message,
    select_folder, uid_for_message_id, build_message,
    LEAD_ID_HEADERS, LEAD_ID_RE,
)
from outreach_stages import (
    generate_one_mail, select_one_reason, value_action_for,
)

BATCH_SIZE = 100
EXPECTED_TAGGED_DRAFTS = 1173
MAX_MESSAGES = 2000
VALID_CONCEPT_STATES = {"concept", "draft", "review_draft"}


def _address(msg, field="To") -> str:
    parsed = getaddresses(msg.get_all(field, []))
    if len(parsed) != 1:
        return ""
    return normalize_email(parsed[0][1])


def inventory_existing(client, folder: str) -> list[dict]:
    """Stable lead-id ordering: replacement changes UID, not the batch slot."""
    select_folder(client, folder, readonly=True)
    ids = set()
    for header in LEAD_ID_HEADERS:
        status, data = client.search(None, "HEADER", header, '"growth-"')
        if status != "OK":
            raise RuntimeError("imap_inventory_search_failed")
        ids.update((data[0] if data else b"").split())
    if not 1 <= len(ids) <= MAX_MESSAGES:
        raise RuntimeError("imap_inventory_count_invalid")
    records = []
    ordered = sorted(ids, key=int)
    for start in range(0, len(ordered), 40):
        sequences = b",".join(ordered[start:start+40]).decode("ascii")
        status, payload = client.fetch(
            sequences,
            "(BODY.PEEK[HEADER.FIELDS (TO FROM X-Leadscanner-Lead-ID "
            "X-Webactueel-Lead-ID X-Leadscanner-Review-Required "
            "X-Webactueel-Review-Required)])",
        )
        if status != "OK":
            raise RuntimeError("imap_inventory_fetch_failed")
        for part in payload or []:
            if not isinstance(part, tuple) or len(part) < 2 or not isinstance(part[1], bytes):
                continue
            msg = BytesParser(policy=default).parsebytes(part[1])
            lead = lead_id_from_message(msg)
            if not LEAD_ID_RE.fullmatch(lead):
                raise RuntimeError("imap_noncanonical_tagged_draft")
            records.append({
                "lead_id": lead,
                "recipient": _address(msg),
                "sender": _address(msg, "From"),
                "review": review_status_from_message(msg),
            })
    if len(records) != len(ids):
        raise RuntimeError("imap_inventory_incomplete")
    records.sort(key=lambda item: item["lead_id"])
    if len(records) != EXPECTED_TAGGED_DRAFTS:
        raise RuntimeError("imap_tagged_baseline_changed")
    if len({row["lead_id"] for row in records}) != len(records):
        raise RuntimeError("imap_duplicate_lead_id")
    return records


def _ordinary_hold(recipient: str, lead: str, site: str, ordinary: list[dict]) -> bool:
    if not ordinary:
        return False
    identity = {"email": recipient, "lead_id": lead}
    if site:
        identity["website"] = site
    for item in ordinary:
        matched = match_candidate(identity, [item])
        if matched and str(matched.get("registry_status") or "").casefold() not in VALID_CONCEPT_STATES:
            return True
    return False


def source_hint(
    record: dict, sources: dict[str, dict], history: dict,
    ordinary: list[dict],
) -> tuple[str, str, str]:
    """Never infer a website from a shared-provider email or draft marketing copy."""
    recipient, lead = record["recipient"], record["lead_id"]
    if not recipient or recipient.count("@") != 1 or not lead:
        return "", "", "invalid_target_identity"
    row = sources.get(recipient)
    if row is not None:
        if excluded_history(row) or row.get("status") != 1:
            return "", "", "historically_contacted_or_blocked"
        if not match_candidate({"email": recipient}, [history]):
            raise RuntimeError("original_source_suppression_missing")
        site = historical_site(row)
        name = historical_name(row)
        if site and not name:
            name = historical_brand_hint(row, site, history)
        if not site or not name:
            return "", "", "original_site_or_identity_unresolved"
    else:
        email_domain = normalize_domain(recipient.rsplit("@", 1)[1])
        if not email_domain or email_domain in PUBLIC_MAIL_DOMAINS:
            return "", "", "no_verified_shared_mail_provider_site"
        site = "https://" + email_domain
        # Domain stem is just a research hint; live verified homepage MUST
        # corroborate real business identity before any body is generated.
        name = email_domain.split(".", 1)[0].replace("-", " ").strip()
        if not 3 <= len(name) <= 80:
            return "", "", "unknown_corporate_brand"
    if _ordinary_hold(recipient, lead, site, ordinary):
        return "", "", "excluded_concept_or_contact"
    return site, name, ""


def rewrite_copy(candidate: dict) -> tuple[str, str]:
    """One first-party observation, single suggested improvement and soft CTA."""
    ranked = select_one_reason(candidate)
    findings = ranked.get("selected_findings") or []
    if ranked.get("outreach_status") != "ready" or not findings:
        return "", ""
    top = findings[0]
    if (top.get("source_type") != "official_site" or
            normalize_domain(top.get("source_url")) !=
            normalize_domain(candidate.get("official_domain"))):
        return "", ""
    ranked["selected_findings"] = [top]
    ranked["verified_observation"] = top["observation"]
    ranked["verified_observation_source_url"] = top["source_url"]
    ranked["verified_observation_source_type"] = "official_site"
    proposed = value_action_for(ranked)
    completed = generate_one_mail(proposed)
    if (completed.get("mail_status") != "ready_for_human_review" or
            completed.get("copy_validation_status") != "green"):
        return "", ""
    subject = str(completed["subject"])
    body = str(completed["body"])
    lang = completed.get("language")
    if lang == "nl" and body.endswith("Groet,\nAndrew Baeten"):
        body = body[:-len("Groet,\nAndrew Baeten")] + "Met vriendelijke groeten,\nAndrew"
    elif lang == "en" and body.endswith("Best,\nAndrew Baeten"):
        body = body[:-len("Best,\nAndrew Baeten")] + "Kind regards,\nAndrew"
    else:
        return "", ""
    if (len(subject.split()) > 8 or len(body.split()) > 155
            or body.count("?") - str(top["observation"]).count("?") != 1
            or top["observation"] not in body or not body.endswith("\nAndrew")
            or any(value in body for value in ("{{", "}}", "{%", "%}", "\x00"))):
        return "", ""
    return subject, body


def _original_snapshot(client, folder: str, lead: str):
    ids = find_message_ids(client, folder, lead)
    if len(ids) != 1:
        raise RuntimeError("imap_existing_target_not_unique")
    original = fetch_message(client, ids[0])
    uid = uid_for_message_id(client, ids[0])
    require_draft_flag(client, uid)
    return original


def run(offset: int, *, write: bool) -> dict:
    if offset < 0 or offset % BATCH_SIZE or offset >= EXPECTED_TAGGED_DRAFTS:
        raise RuntimeError("offset_out_of_bounds")
    if write and (os.getenv("LEADSCANNER_TRUSTED_REWRITE") != "true"
                  or not os.getenv("OUTREACH_MAIL_PASSWORD")):
        raise RuntimeError("trusted_main_required")
    rows, _ = read_source()
    summary = classify(rows)
    if len(rows) != EXPECTED or any(summary[k] for k in FATAL_KEYS):
        raise RuntimeError("historical_source_invalid")
    sources = {normalize_email(row.get("email")): row for row in rows}
    if len(sources) != EXPECTED:
        raise RuntimeError("historical_source_duplicates")
    registry = fetch_registry()
    history_rows = [r for r in registry if r.get("status") == "historical_v2_suppression"]
    if len(history_rows) != 1 or len(history_rows[0].get("v2_emails") or ()) != EXPECTED:
        raise RuntimeError("historical_registry_invalid")
    history = history_rows[0]
    ordinary = [r for r in registry if r.get("status") != "historical_v2_suppression"]
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        all_drafts = inventory_existing(client, folder)
        window = all_drafts[offset:offset + BATCH_SIZE]
        if len(window) != min(BATCH_SIZE, EXPECTED_TAGGED_DRAFTS - offset):
            raise RuntimeError("batch_size_unstable")
        counters = Counter({"checked": len(window)})
        hints = []
        snapshots = {}
        sender = normalize_email(os.environ.get(
            "OUTREACH_SENDER_EMAIL", "info@andrewbaeten.nl"))
        for item in window:
            lead = item["lead_id"]
            if not item["recipient"] or item["sender"] != sender:
                counters["hold_invalid_existing_sender_or_recipient"] += 1
                continue
            site, company, reason = source_hint(item, sources, history, ordinary)
            if reason:
                counters["hold_identity_or_history"] += 1
                continue
            try:
                original = _original_snapshot(client, folder, lead)
            except Exception:
                counters["hold_invalid_existing_draft"] += 1
                continue
            if (_address(original) != item["recipient"] or
                    _address(original, "From") != sender):
                counters["hold_identity_drift"] += 1
                continue
            snapshots[lead] = original
            hints.append({
                "lead_id": lead, "name_hint": company, "website_hint": site,
                "category_hint": "", "original_recipient": item["recipient"],
            })

        verified = verify_candidates(
            {"candidates": hints}, limit=len(hints), max_workers=8,
        )["candidates"] if hints else []
        eligible = []
        for candidate in verified:
            if candidate.get("ready_for_research"):
                eligible.append(candidate)
            else:
                counters["hold_site_verification"] += 1
        researched = research_candidates(
            {"candidates": eligible}, limit=len(eligible), max_workers=6,
        )["candidates"] if eligible else []
        for candidate in researched:
            lead = candidate["lead_id"]
            counters["researched"] += 1
            expected_to = candidate["original_recipient"]
            if (candidate.get("research_status") != "ready"
                    or candidate.get("contact_status") != "verified_official_site"
                    or normalize_email(candidate.get("public_business_email")) != expected_to):
                counters["hold_contact_not_currently_published"] += 1
                continue
            subject, body = rewrite_copy(candidate)
            if not subject or not body:
                counters["hold_insufficient_evidence_or_copy"] += 1
                continue
            target = {
                "lead_id": lead, "email": expected_to,
                "company": candidate.get("name_hint"),
                "website": candidate.get("official_url"),
                "subject": subject, "body": body,
                "status": "review_draft", "contact_basis_status": "review_required",
                "automatic_send": False,
            }
            _, expected_msg = build_message(target)
            original = snapshots.get(lead)
            if original is None:
                raise RuntimeError("original_snapshot_missing")
            if exact_message_matches(original, expected_msg):
                counters["already_correct"] += 1
                continue
            counters["ready_to_rewrite"] += 1
            if not write:
                continue

            # Re-read the private suppression registry and the exact original
            # immediately before any IMAP write. No race may change a blocked
            # person/recipient or a user-edited Draft silently.
            current_registry = fetch_registry()
            fresh_hist = [r for r in current_registry if r.get("status") ==
                          "historical_v2_suppression"]
            if len(fresh_hist) != 1 or fresh_hist[0].get("v2_key") != history.get("v2_key"):
                raise RuntimeError("historical_registry_changed")
            fresh_ordinary = [r for r in current_registry if r.get("status") !=
                              "historical_v2_suppression"]
            if _ordinary_hold(expected_to, lead, candidate.get("official_url") or "",
                              fresh_ordinary):
                counters["hold_new_exclusion"] += 1
                continue
            current = _original_snapshot(client, folder, lead)
            if (not exact_message_matches(current, original)
                    or review_status_from_message(current) !=
                    review_status_from_message(original)):
                counters["hold_concurrent_draft_edit"] += 1
                continue
            # No blank new prospect Drafts: explicitly existing-only, with
            # target UIDPLUS replacement and full IMAP final readback.
            result = create_drafts(
                {"rows": [target]}, rewrite_existing_only=True,
                reject_changed_existing=False,
            )
            if result.get("created_count") != 0 or result.get("existing_count") != 0 \
                    or result.get("replaced_count") != 1:
                raise RuntimeError("unexpected_draft_write_outcome")
            counters["rewritten"] += 1
        if sum(counters[k] for k in (
            "hold_invalid_existing_sender_or_recipient", "hold_identity_or_history",
            "hold_invalid_existing_draft", "hold_identity_drift",
            "hold_site_verification", "hold_contact_not_currently_published",
            "hold_insufficient_evidence_or_copy", "already_correct",
            "ready_to_rewrite",
        )) != len(window):
            raise RuntimeError("batch_accounting_incomplete")
        return {
            "status": "green",
            "mode": "rewrite" if write else "review",
            "offset": offset,
            "total_tagged": len(all_drafts),
            "counts": dict(sorted(counters.items())),
            "emails_sent": 0,
            "drafts_created": 0,
            "drafts_removed_unrelated": 0,
            "sensitive_data_logged": False,
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, required=True)
    parser.add_argument("--mode", choices=("review", "rewrite"), required=True)
    args = parser.parse_args()
    try:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            result = run(args.offset, write=args.mode == "rewrite")
    except Exception as exc:
        # Fail closed: never publish provider exception messages, URLs, email
        # addresses, contact IDs, copies, source evidence or stack frames.
        print("MYHOST_100_REWRITE=red stage=private_hold details_suppressed")
        return 1
    print("MYHOST_100_REWRITE=green " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
