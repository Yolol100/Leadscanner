"""One-off existing-only redraft: 509 old mijn.host Drafts, 50 per cohort.

Always research the current first-party website; draft 3-6 sourced improvement
points or quarantine the old unqualified Draft. Copy all original raw messages
to a private rollback folder BEFORE any changes. No sends, no new lead IDs,
no recipient changes and no raw PII or messages in public runner logs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
from email.utils import getaddresses
from io import StringIO
import json
import os
import sys

from _once_historical_source_diagnose import EXPECTED, FATAL_KEYS, classify, read_source
from _once_myhost_existing_rewrite import (
    EXPECTED_TAGGED_DRAFTS, _original_snapshot, _ordinary_hold,
    inventory_existing, rewrite_copy, source_hint,
)
from _once_myhost_safe_hold import (
    HOLD_FOLDER, _one_uid, _raw_uid, ensure_hold_folder, move_to_hold,
    validate_hold_inventory,
)
from cold_stages import research_candidates, verify_candidates
from dedupe_preflight import normalize_domain, normalize_email
from leadscanner_core import fetch_registry
from myhost_draft import (
    build_message, connect_imap, create_drafts, exact_message_matches,
    fetch_message_uid, find_drafts_folder, plain_body, require_draft_flag,
    require_uidplus, select_folder,
)

TOTAL_ACTIVE = 509
TOTAL_HELD = 664
EXPECTED_BACKUPS = TOTAL_ACTIVE
STEP = 50
BACKUP_FOLDER = "Leadscanner_Originals_20261013_Before509Redraft"
SENDER = "info@andrewbaeten.nl"
HOLD_REASONS = (
    "source_identity_or_history", "site_unverified", "contact_unverified",
    "insufficient_three_to_six_facts", "changed_since_snapshot",
)


def _one_address(msg, key):
    addresses = getaddresses(msg.get_all(key, []))
    return normalize_email(addresses[0][1]) if len(addresses) == 1 else ""


def _open_inventory(client, *, strict_initial=False):
    drafts = find_drafts_folder(client)
    active, held = validate_hold_inventory(
        client, drafts, HOLD_FOLDER, inventory_existing, EXPECTED_TAGGED_DRAFTS
    )
    if strict_initial and (len(active), len(held)) != (TOTAL_ACTIVE, TOTAL_HELD):
        raise RuntimeError("initial_inventory_509_664_changed")
    if {x["lead_id"] for x in active} & {x["lead_id"] for x in held}:
        raise RuntimeError("unexpected_active_hold_overlap")
    return drafts, active, held


def _source_context():
    records, _ = read_source()
    if len(records) != EXPECTED or any(classify(records)[k] for k in FATAL_KEYS):
        raise RuntimeError("historical_source_integrity_failed")
    sources = {normalize_email(x.get("email")): x for x in records}
    if len(sources) != EXPECTED:
        raise RuntimeError("source_email_identity_collision")
    registry = fetch_registry()
    history = [x for x in registry if x.get("status") == "historical_v2_suppression"]
    if len(history) != 1 or len(history[0].get("v2_emails") or ()) != EXPECTED:
        raise RuntimeError("historical_contact_suppression_missing")
    ordinary = [x for x in registry if x.get("status") != "historical_v2_suppression"]
    return sources, history[0], ordinary


def _research_window(window, sources, history, ordinary):
    """Source + public website evidence. No IMAP writes or raw output."""
    decisions = {}
    hints = []
    for record in window:
        lead = record["lead_id"]
        site, name, reason = source_hint(record, sources, history, ordinary)
        if reason:
            decisions[lead] = ("hold", "source_identity_or_history", None)
            continue
        hints.append({
            "lead_id": lead,
            "name_hint": name,
            "website_hint": site,
            "category_hint": "",
            "original_recipient": record["recipient"],
        })
    if hints:
        verified = verify_candidates(
            {"candidates": hints}, limit=len(hints), max_workers=8
        )["candidates"]
    else:
        verified = []
    eligible = []
    for cand in verified:
        if cand.get("ready_for_research"):
            eligible.append(cand)
        else:
            decisions[cand["lead_id"]] = ("hold", "site_unverified", None)
    if eligible:
        researched = research_candidates(
            {"candidates": eligible}, limit=len(eligible), max_workers=6
        )["candidates"]
    else:
        researched = []
    for cand in researched:
        lead = cand["lead_id"]
        recipient = next(item["recipient"] for item in window if item["lead_id"] == lead)
        if (cand.get("research_status") != "ready"
                or cand.get("contact_status") != "verified_official_site"
                or normalize_email(cand.get("public_business_email")) != recipient):
            decisions[lead] = ("hold", "contact_unverified", None)
            continue
        subject, body = rewrite_copy(cand)
        if not subject or not body:
            decisions[lead] = ("hold", "insufficient_three_to_six_facts", None)
            continue
        draft = {
            "lead_id": lead, "email": recipient, "company": cand.get("name_hint"),
            "website": cand.get("official_url"), "subject": subject, "body": body,
            "status": "review_draft", "contact_basis_status": "review_required",
            "automatic_send": False,
        }
        _, expected_msg = build_message(draft)
        if (len([line for line in body.splitlines()
                 if line.lstrip().startswith(tuple(f"{n}. " for n in range(1, 7)))]) < 3
                or body.count("Verbeteridee:") + body.count("Suggested improvement:") < 3):
            decisions[lead] = ("hold", "insufficient_three_to_six_facts", None)
            continue
        decisions[lead] = ("rewrite", "source_supported", (draft, expected_msg))
    if set(decisions) != {item["lead_id"] for item in window}:
        raise RuntimeError("research_window_did_not_cover_all")
    return decisions


def _find_backup_folder(client, drafts, *, create=False):
    if drafts.casefold() == BACKUP_FOLDER.casefold():
        raise RuntimeError("backup_folder_cannot_equal_drafts")
    try:
        select_folder(client, BACKUP_FOLDER, readonly=True)
    except RuntimeError:
        if not create:
            raise
        status, _ = client.create('"' + BACKUP_FOLDER + '"')
        if status != "OK":
            raise RuntimeError("original_backup_folder_create_failed")
        select_folder(client, BACKUP_FOLDER, readonly=True)
    return BACKUP_FOLDER


def _backup_inventory(client, *, expected):
    backup = inventory_existing(client, BACKUP_FOLDER, expected_total=expected)
    select_folder(client, BACKUP_FOLDER, readonly=True)
    status, rows = client.search(None, "ALL")
    if status != "OK" or len((rows[0] if rows else b"").split()) != len(backup):
        raise RuntimeError("backup_contains_unrelated_messages")
    return backup


def _backup_all():
    """Copy every original UID byte-for-byte; no active draft is changed."""
    client = connect_imap()
    try:
        drafts, active, held = _open_inventory(client, strict_initial=True)
        require_uidplus(client, "one-off 509 Draft recovery backup")
        _find_backup_folder(client, drafts, create=True)
        existing = _backup_inventory(client, expected=None)
        active_ids = {item["lead_id"] for item in active}
        original_ids = {item["lead_id"] for item in existing}
        if not original_ids.issubset(active_ids):
            raise RuntimeError("partial_backup_unrelated_originals")
        # A cancelled COPY may have left recoverable originals. Only reuse
        # a copy when its raw bytes still exactly equal the live Draft.
        reused = 0
        copied = 0
        for item in active:
            lead = item["lead_id"]
            original_uid = _one_uid(client, drafts, lead, require_draft=True)
            if original_uid is None:
                raise RuntimeError("original_draft_missing")
            select_folder(client, drafts, readonly=True)
            original_raw = _raw_uid(client, original_uid)
            if lead in original_ids:
                saved_uid = _one_uid(client, BACKUP_FOLDER, lead)
                if saved_uid is None:
                    raise RuntimeError("partial_backup_missing")
                select_folder(client, BACKUP_FOLDER, readonly=True)
                if _raw_uid(client, saved_uid) != original_raw:
                    raise RuntimeError("partial_backup_content_changed")
                reused += 1
                continue
            select_folder(client, drafts, readonly=False)
            if _raw_uid(client, original_uid) != original_raw:
                raise RuntimeError("original_changed_during_backup")
            status, _ = client.uid("copy", original_uid.decode("ascii"),
                                   '"' + BACKUP_FOLDER + '"')
            if status != "OK":
                raise RuntimeError("original_uid_copy_failed")
            saved_uid = _one_uid(client, BACKUP_FOLDER, lead)
            if saved_uid is None:
                raise RuntimeError("backup_copy_not_found")
            select_folder(client, BACKUP_FOLDER, readonly=True)
            if _raw_uid(client, saved_uid) != original_raw:
                raise RuntimeError("backup_exact_bytes_mismatch")
            copied += 1
        verified = _backup_inventory(client, expected=EXPECTED_BACKUPS)
        if {x["lead_id"] for x in verified} != {x["lead_id"] for x in active}:
            raise RuntimeError("backup_identity_coverage_mismatch")
        _open_inventory(client, strict_initial=True)
        return {"originals_backed_up": len(verified), "reused_exact_backups": reused,
                "new_exact_backups": copied, "active": len(active),
                "held": len(held), "total": EXPECTED_TAGGED_DRAFTS,
                "mail_sent": 0, "mail_replaced": 0}
    finally:
        client.logout()


def _eligible_window(client, *, offset):
    drafts, active, held = _open_inventory(client)
    _find_backup_folder(client, drafts)
    backup = _backup_inventory(client, expected=EXPECTED_BACKUPS)
    backup_ids = {x["lead_id"] for x in backup}
    if len(backup_ids) != EXPECTED_BACKUPS:
        raise RuntimeError("backup_duplicate_id")
    original_members = {x["lead_id"] for x in active + held}
    if not backup_ids.issubset(original_members):
        raise RuntimeError("original_backup_cohort_lost")
    if offset < 0 or offset % STEP or offset >= TOTAL_ACTIVE:
        raise RuntimeError("cohort_offset_invalid")
    return drafts, active, held, backup[offset:offset + STEP]


def _same_backup(client, drafts, lead):
    original_uid = _one_uid(client, drafts, lead, require_draft=True)
    if original_uid is None:
        return False
    select_folder(client, drafts, readonly=True)
    original_raw = _raw_uid(client, original_uid)
    backup_uid = _one_uid(client, BACKUP_FOLDER, lead)
    if backup_uid is None:
        raise RuntimeError("original_backup_missing")
    select_folder(client, BACKUP_FOLDER, readonly=True)
    return _raw_uid(client, backup_uid) == original_raw


def _run_window(offset, *, write=False):
    client = connect_imap()
    try:
        drafts, active, held, cohort = _eligible_window(client, offset=offset)
        active_ids = {x["lead_id"] for x in active}
        targets = [x for x in cohort if x["lead_id"] in active_ids]
        if write and len(targets) != len(cohort):
            raise RuntimeError("batch_replay_or_external_mailbox_change")
        sources, history, ordinary = _source_context()
        decisions = _research_window(targets, sources, history, ordinary)
        counts = Counter({"checked": len(targets)})
        if not write:
            for action, reason, _ in decisions.values():
                counts["ready_for_rewrite" if action == "rewrite" else reason] += 1
            return {"offset": offset, "mode": "preview", "counts": dict(counts),
                    "active": len(active), "held": len(held),
                    "all_sources_researched": True, "mailbox_writes": False,
                    "emails_sent": 0, "created_new_leads": 0}
        require_uidplus(client, "existing-only 50 Draft redraft")
        ensure_hold_folder(client, drafts)
        if normalize_email(os.getenv("OUTREACH_SENDER_EMAIL") or SENDER) != SENDER:
            raise RuntimeError("expected_sender_changed")
        for item in targets:
            lead = item["lead_id"]
            if not _same_backup(client, drafts, lead):
                counts["hold_concurrent_or_user_edit"] += 1
                continue
            original = _original_snapshot(client, drafts, lead)
            if (_one_address(original, "To") != item["recipient"]
                    or _one_address(original, "From") != item["sender"]
                    or item["sender"] != SENDER):
                counts["hold_identity_mismatch"] += 1
                continue
            action, reason, payload = decisions[lead]
            if action == "hold":
                if move_to_hold(client, drafts, HOLD_FOLDER, lead,
                                item["recipient"], SENDER, original):
                    counts["archived_for_recovery"] += 1
                    counts[reason] += 1
                else:
                    counts["hold_user_edited"] += 1
                continue
            row, expected_msg = payload
            fresh_registry = fetch_registry()
            fresh_hist = [x for x in fresh_registry if x.get("status") ==
                          "historical_v2_suppression"]
            if len(fresh_hist) != 1 or fresh_hist[0].get("v2_key") != history.get("v2_key"):
                raise RuntimeError("dedupe_registry_changed_during_write")
            fresh_ordinary = [x for x in fresh_registry if x.get("status") !=
                              "historical_v2_suppression"]
            if _ordinary_hold(item["recipient"], lead, row["website"], fresh_ordinary):
                counts["blocked_by_updated_registry"] += 1
                continue
            if exact_message_matches(original, expected_msg):
                counts["already_matching_new_copy"] += 1
                continue
            result = create_drafts({"rows": [row]}, rewrite_existing_only=True,
                                   reject_changed_existing=False)
            if result.get("created_count") != 0 or result.get("replaced_count") != 1:
                raise RuntimeError("unexpected_existing_only_replace_result")
            current = _original_snapshot(client, drafts, lead)
            if not exact_message_matches(current, expected_msg):
                raise RuntimeError("post_replace_readback_not_exact")
            counts["rewritten_existing"] += 1
        active_after, held_after = validate_hold_inventory(
            client, drafts, HOLD_FOLDER, inventory_existing, EXPECTED_TAGGED_DRAFTS
        )
        _backup_inventory(client, expected=EXPECTED_BACKUPS)
        if len(active_after) + len(held_after) != EXPECTED_TAGGED_DRAFTS:
            raise RuntimeError("batch_final_inventory_not_reconciled")
        return {"offset": offset, "mode": "rewrite", "counts": dict(sorted(counts.items())),
                "active_after": len(active_after), "held_after": len(held_after),
                "originals_backed_up": EXPECTED_BACKUPS,
                "emails_sent": 0, "new_leads": 0,
                "drafts_created_additional": 0, "reversible": True}
    finally:
        client.logout()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "backup", "rewrite"), required=True)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    if not os.getenv("OUTREACH_MAIL_PASSWORD"):
        print("MYHOST_REDRAFT50=red details_suppressed")
        return 1
    if args.mode in ("backup", "rewrite") and (
        os.getenv("LEADSCANNER_AUTHORIZED_509_REDRAFT") != "true"
    ):
        print("MYHOST_REDRAFT50=red write_not_authorized")
        return 1
    try:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            if args.mode == "backup":
                result = _backup_all()
            elif args.mode == "preview":
                # Preview needs no backup; check the original stable 509 cohort.
                client = connect_imap()
                try:
                    drafts, active, held = _open_inventory(client, strict_initial=True)
                    if not (0 <= args.offset < TOTAL_ACTIVE and args.offset % STEP == 0):
                        raise RuntimeError("invalid_readonly_preview_cohort_offset")
                    cohort = active[args.offset:args.offset + STEP]
                    sources, history, ordinary = _source_context()
                    decisions = _research_window(cohort, sources, history, ordinary)
                    counts = Counter()
                    for action, reason, _ in decisions.values():
                        counts["ready_for_rewrite" if action == "rewrite" else reason] += 1
                    result = {"mode": "preview", "offset": args.offset,
                              "checked": len(cohort),
                              "counts": dict(sorted(counts.items())),
                              "active": len(active), "held": len(held),
                              "total": EXPECTED_TAGGED_DRAFTS,
                              "source_evidence_researched_as_available": True,
                              "emails_sent": 0, "mailbox_writes": False}
                finally:
                    client.logout()
            else:
                if os.getenv("LEADSCANNER_AUTHORIZED_509_REDRAFT") != "true":
                    raise RuntimeError("redraft_write_not_authorized")
                result = _run_window(args.offset, write=True)
    except Exception:
        print("MYHOST_REDRAFT50=red stage=" + args.mode + " details_suppressed")
        return 1
    print("MYHOST_REDRAFT50=green " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
