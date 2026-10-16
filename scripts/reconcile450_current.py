"""One-off, user-authorized, targeted Mijn.Host Drafts reconciliation.

Only the 450 historical draft IDs are in scope. Replacement messages are
read back and verified before any old UID can be removed. No SMTP or sending.
No prospect details, hashes, UID lists or message bodies are logged.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import redirect_stdout, redirect_stderr
from email.utils import parseaddr
from io import StringIO
import os
import re
import sys

import review450 as historical
import replace450 as legacy
import replace450_fast as transport
from dedupe_preflight import match_candidate
from myhost_draft import _mailbox_arg, _matches, build_message, connect_imap, find_drafts_folder
from private_candidate_handoff import authorized_writer
from registry_readonly import load_suppressions

TASK = "review450-20261016"
DRAFT_RE = re.compile(r"draft-[a-f0-9]{32}\Z")
CANDIDATE_STATUSES = {"VOOR_MENSELIJKE_EINDCONTROLE", "VOORSTEL_HANDMATIGE_EINDCHECK"}
EXPECTED_ELIGIBLE = 412
EXPECTED_EXCLUDED = 38
OPT = "Liever geen e-mails meer? Antwoord met 'nee', dan laat ik het hierbij."


def load_private_scope(session):
    original = historical.load_rows(session)
    current = historical.read(session, historical.SID, "QA450Actueel!A2:P451")
    if len(original) != 450 or len(current) != 450:
        raise RuntimeError("private_450_scope_invalid")
    expected = {}
    for index, (old, row) in enumerate(zip(original, current), start=1):
        if len(row) != 16 or row[0] != str(index):
            raise RuntimeError("private_450_row_invalid")
        key = row[1]
        if (
            not DRAFT_RE.fullmatch(key) or key in expected
            or old["draft_id"] != key or old["company"] != row[2]
            or old["email"].casefold() != row[3].casefold()
            or old["subject"] != row[4] or not row[5] or not row[6]
            or OPT not in row[6] or len(row[6].split()) > 110
            or not row[8].startswith(("https://", "http://"))
            or not row[13]
        ):
            raise RuntimeError("private_450_identity_or_copy_invalid")
        new = {
            "draft_id": key, "company": row[2], "email": row[3],
            "source_url": row[8], "subject": row[5], "body": row[6],
        }
        expected[key] = {
            "old": old, "new": new,
            "eligible": row[13] in CANDIDATE_STATUSES,
        }
    if (sum(v["eligible"] for v in expected.values()) != EXPECTED_ELIGIBLE
            or sum(not v["eligible"] for v in expected.values()) != EXPECTED_EXCLUDED):
        raise RuntimeError("eligibility_snapshot_changed")
    return expected


def verify_suppressions(session, expected):
    suppression = load_suppressions(session=session)
    for value in expected.values():
        if not value["eligible"]:
            continue
        row = value["new"]
        if match_candidate({
            "name_hint": row["company"], "website_hint": row["source_url"],
            "email": row["email"],
        }, suppression) is not None:
            raise RuntimeError("historically_suppressed_before_draft")


def classify(inventory, expected):
    """Classify only exact original or verified new drafts by stable ID."""
    grouped = defaultdict(lambda: {"old": [], "new": []})
    unrelated = []
    for uid, record in inventory.items():
        key = record["draft_id"]
        if key not in expected:
            unrelated.append(uid)
            continue
        if (not record["draft_flag"] or b"\\DELETED" in record["flags"]
                or parseaddr(record["message"].get("From", ""))[1].casefold() != legacy.USER):
            raise RuntimeError("review_draft_flag_or_sender_changed")
        item = expected[key]
        is_new = item["eligible"] and _matches(
            build_message(item["new"]), record["message"]
        )
        is_old = _matches(build_message(item["old"]), record["message"])
        if is_new:
            grouped[key]["new"].append(uid)
        elif is_old:
            grouped[key]["old"].append(uid)
        else:
            raise RuntimeError("existing_review_draft_edited_or_unrecognized")
    if unrelated:
        raise RuntimeError("unrelated_drafts_present_preserve_them")
    for key, state in grouped.items():
        if len(state["old"]) > 1 or len(state["new"]) > 1:
            raise RuntimeError("duplicate_review_draft_version")
    for key, item in expected.items():
        state = grouped[key]
        if item["eligible"] and not state["old"] and not state["new"]:
            raise RuntimeError("expected_review_draft_missing")
        if not item["eligible"] and state["new"]:
            raise RuntimeError("excluded_draft_has_new_version")
    return grouped


def verify_new_complete(groups, expected):
    for key, item in expected.items():
        if item["eligible"] and len(groups[key]["new"]) != 1:
            raise RuntimeError("new_draft_not_verified")
        if not item["eligible"] and groups[key]["new"]:
            raise RuntimeError("excluded_draft_not_rejected")


def reconcile():
    legacy.target_guard()
    conn = authorized_writer()
    expected = load_private_scope(conn)
    verify_suppressions(conn, expected)
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        validity = legacy.select(client, folder, readonly=True)
        if not legacy.uidplus(client):
            raise RuntimeError("targeted_uid_expunge_not_supported")
        inventory = transport.scan(client)
        initial = classify(inventory, expected)
        pending = [key for key, item in expected.items()
                   if item["eligible"] and not initial[key]["new"]]
        created = 0
        # Each bounded append checkpoint has full, same-folder \Draft readback.
        for start in range(0, len(pending), 100):
            verify_suppressions(conn, expected)
            for key in pending[start:start+100]:
                msg = build_message(expected[key]["new"])
                if client.append(_mailbox_arg(folder), "(\\Draft)", None, msg.as_bytes())[0] != "OK":
                    raise RuntimeError("imap_append_unverified")
                created += 1
            fresh = transport.scan(client)
            checkpoint = classify(fresh, expected)
            for key in pending[:start+100]:
                if len(checkpoint[key]["new"]) != 1:
                    raise RuntimeError("new_draft_batch_readback_mismatch")
        ready = transport.scan(client)
        staged = classify(ready, expected)
        verify_new_complete(staged, expected)
        old_uids = {u for g in staged.values() for u in g["old"]}
        old_hash = {uid: ready[uid]["sha256"] for uid in old_uids}
        verify_suppressions(conn, expected)
        # Re-read all messages with a writable selection before targeted remove.
        if legacy.select(client, folder, readonly=False) != validity:
            raise RuntimeError("uidvalidity_changed")
        before = transport.scan(client)
        if set(before) != set(ready):
            raise RuntimeError("mailbox_changed_before_remove")
        again = classify(before, expected)
        verify_new_complete(again, expected)
        if {u for g in again.values() for u in g["old"]} != old_uids:
            raise RuntimeError("old_uid_scope_changed")
        if any(before[uid]["sha256"] != old_hash[uid] for uid in old_uids):
            raise RuntimeError("original_draft_changed")
        removed = 0
        for start in range(0, len(old_uids), 100):
            group = sorted(old_uids, key=int)[start:start+100]
            for uid in group:
                live = legacy.fetch_message(client, uid)
                if live["sha256"] != old_hash[uid] or not live["draft_flag"]:
                    raise RuntimeError("old_draft_changed_do_not_remove")
            uid_list = ",".join(group)
            if client.uid("STORE", uid_list, "+FLAGS.SILENT", "(\\Deleted)")[0] != "OK":
                raise RuntimeError("targeted_old_draft_mark_failed")
            if client.uid("EXPUNGE", uid_list)[0] != "OK":
                raise RuntimeError("targeted_old_draft_remove_failed")
            if set(group) & legacy.uidset(client):
                raise RuntimeError("old_draft_remove_readback_failed")
            removed += len(group)
        final = transport.scan(client)
        final_groups = classify(final, expected)
        verify_new_complete(final_groups, expected)
        if any(group["old"] for group in final_groups.values()):
            raise RuntimeError("stale_drafts_remain")
        if len(final) != EXPECTED_ELIGIBLE:
            raise RuntimeError("final_draft_count_invalid")
        return {"eligible": EXPECTED_ELIGIBLE, "excluded": EXPECTED_EXCLUDED,
                "created": created, "removed": removed, "remaining": len(final)}
    finally:
        try:
            client.logout()
        except Exception:
            pass


def main():
    if os.environ.get("MAILBOX450_UPGRADE_TASK") != TASK:
        print("MYHOST_450_UPGRADE=blocked reason=unauthorized_task sent=0")
        return 1
    try:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            output = reconcile()
        print("MYHOST_450_UPGRADE=green " + " ".join(
            f"{key}={value}" for key, value in output.items()
        ) + " sent=0")
        return 0
    except Exception:
        print("MYHOST_450_UPGRADE=blocked reason=private_preflight_or_imap_failed sent=0")
        return 1


if __name__ == "__main__":
    sys.exit(main())
