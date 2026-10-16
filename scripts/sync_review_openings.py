"""Owner-authorized value-first replacement: 404 live drafts; preserve 8 holds.

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
DIAGNOSTIC_STAGE = "entry"
REGISTRY_DIAGNOSTIC_STAGE = "idle"
DRAFT_RE = re.compile(r"draft-[a-f0-9]{32}\Z")
CANDIDATE_STATUSES = {"VOOR_MENSELIJKE_EINDCONTROLE", "VOORSTEL_HANDMATIGE_EINDCHECK"}
EXPECTED_ELIGIBLE = 404
EXPECTED_HOLD = 8
EXPECTED_EXCLUDED = 38
EXPECTED_MAILBOX = 412
OPT = "Liever geen e-mails meer? Antwoord met 'nee', dan laat ik het hierbij."


def load_private_scope(session):
    original = historical.load_rows(session)
    current = historical.read(session, historical.SID, "QA450Actueel!A2:P451")
    revised = historical.read(session, historical.SID, "OpeningenReview20261016!A2:Q451")
    if len(original) != 450 or len(current) != 450 or len(revised) != 450:
        raise RuntimeError("private_450_scope_invalid")
    expected = {}
    for number, (baseline, row, raw) in enumerate(zip(original, current, revised), 1):
        review = (raw + [""] * 17)[:17]
        if len(row) != 16 or len(raw) > 17 or row[0] != str(number):
            raise RuntimeError("private_450_row_invalid")
        key = row[1]
        if (not DRAFT_RE.fullmatch(key) or key in expected
                or baseline["draft_id"] != key
                or baseline["company"] != row[2]
                or baseline["email"].casefold() != row[3].casefold()
                or review[0] != row[0] or review[1] != key
                or review[2] != row[2] or review[4] != row[8]
                or not row[5] or not row[6] or OPT not in row[6]
                or len(row[6].split()) > 110
                or not row[8].startswith(("https://", "http://"))):
            raise RuntimeError("private_450_identity_or_copy_invalid")
        old = {"draft_id":key, "company":row[2], "email":row[3],
               "source_url":row[8], "subject":row[5], "body":row[6]}
        active = row[13] in CANDIDATE_STATUSES
        human = active and review[10] == "MENSELIJKE_EINDCONTROLE"
        hold = active and (review[10].startswith("HOLD")
                           or review[10] == "BRONCHECK_VOOR_VERZENDING")
        if active and not (human or hold):
            raise RuntimeError("unclassified_source_hold")
        if not active and (review[8] != "NIET AANPASSEN" or review[7]):
            raise RuntimeError("original_exclusion_changed")
        if active:
            if (not review[7] or not review[3] or not review[6]
                    or not review[14].startswith("FASE ")
                    or not review[12]):
                raise RuntimeError("review_copy_incomplete")
            try:
                score = float(review[12])
            except (ValueError, TypeError):
                raise RuntimeError("review_score_invalid")
            if not 9 <= score <= 10:
                raise RuntimeError("review_score_below_nine")
            content = review[7]
            parts = content.split("\n\n")
            if (len(parts) != 5 or parts[0] not in {"Goedendag,", "Hoi,"}
                    or parts[1] != review[6]
                    or not parts[2].startswith(("Zal ", "Mag ", "Zou "))
                    or parts[2].count("?") != 1
                    or parts[3] != OPT
                    or parts[4] != "Groet,\nAndrew"
                    or content.count(OPT) != 1
                    or len(content.split()) > 110
                    or not 5 <= len(review[3]) <= 160
                    or any(v in content + review[3] for v in ("{{", "}}", "\x00"))
                    or any(v in content for v in ("https://", "http://", "www."))):
                raise RuntimeError("review_body_invalid")
        if human and (not review[15].startswith("ALLEEN CONCEPT")
                      or (review[3], review[7]) == (row[5], row[6])):
            raise RuntimeError("human_copy_or_gate_invalid")
        if hold and not review[15].startswith(("NIET VERSTUREN", "ALLEEN CONCEPT")):
            raise RuntimeError("hold_gate_invalid")
        updated = {**old,"subject":review[3],"body":review[7]} if human else old
        expected[key] = {"old":old,"new":updated,"eligible":human,"hold":hold}
    if (len(expected) != 450 or
            sum(x["eligible"] for x in expected.values()) != 404 or
            sum(x["hold"] for x in expected.values()) != 8 or
            sum(not (x["eligible"] or x["hold"]) for x in expected.values()) != 38):
        raise RuntimeError("eligibility_snapshot_changed")
    return expected

def verify_suppressions(session, expected):
    global REGISTRY_DIAGNOSTIC_STAGE
    REGISTRY_DIAGNOSTIC_STAGE = "load"
    # Read each source with the same service account before the full guarded read.
    from registry_readonly import REGISTRY_ID, REGISTRY_TAB, read_values
    from historical_v2 import VAULT_SHEET_ID, VAULT_TAB, TAB_NAME
    for label, sid, tab in (
        ("dedupe", REGISTRY_ID, REGISTRY_TAB),
        ("vault", VAULT_SHEET_ID, VAULT_TAB),
        ("historical", REGISTRY_ID, TAB_NAME),
    ):
        REGISTRY_DIAGNOSTIC_STAGE = label
        try:
            read_values(session, sid, tab)
        except Exception:
            raise RuntimeError("registry_" + label + "_unreadable") from None
    REGISTRY_DIAGNOSTIC_STAGE = "load"
    suppression = load_suppressions(session=session)
    REGISTRY_DIAGNOSTIC_STAGE = "match"
    for value in expected.values():
        if not value["eligible"] and not value["hold"]:
            continue
        row = value["new"]
        if match_candidate({
            "name_hint": row["company"], "website_hint": row["source_url"],
            "email": row["email"],
        }, suppression) is not None:
            raise RuntimeError("historically_suppressed_before_draft")


def classify(inventory, expected, *, held_cleared=False):
    """Recognize exact source or reviewed copy only; fail on external edits."""
    grouped = defaultdict(lambda: {"old": [], "new": []})
    for uid, record in inventory.items():
        key = record["draft_id"]
        if key not in expected:
            raise RuntimeError("unrelated_drafts_present_preserve_them")
        if (not record["draft_flag"] or b"\\DELETED" in record["flags"]
                or parseaddr(record["message"].get("From", ""))[1].casefold() != legacy.USER):
            raise RuntimeError("review_draft_flag_or_sender_changed")
        item = expected[key]
        is_new = item["eligible"] and _matches(build_message(item["new"]), record["message"])
        is_old = _matches(build_message(item["old"]), record["message"])
        if is_new and is_old:
            raise RuntimeError("ambiguous_draft_versions")
        if is_new:
            grouped[key]["new"].append(uid)
        elif is_old:
            grouped[key]["old"].append(uid)
        else:
            raise RuntimeError("existing_review_draft_edited_or_unrecognized")
    for key, item in expected.items():
        state = grouped[key]
        if len(state["old"]) > 1 or len(state["new"]) > 1:
            raise RuntimeError("duplicate_review_draft_version")
        if item["eligible"] and not state["old"] and not state["new"]:
            raise RuntimeError("expected_review_draft_missing")
        if item["hold"] and (len(state["old"]) != (0 if held_cleared else 1) or state["new"]):
            raise RuntimeError("held_draft_changed_or_missing")
        if not item["eligible"] and not item["hold"] and (state["old"] or state["new"]):
            raise RuntimeError("excluded_draft_present")
    return grouped

def verify_new_complete(groups, expected, *, held_cleared=False):
    for key, item in expected.items():
        state = groups[key]
        if item["eligible"] and len(state["new"]) != 1:
            raise RuntimeError("new_draft_not_verified")
        if item["hold"] and (len(state["old"]) != (0 if held_cleared else 1) or state["new"]):
            raise RuntimeError("held_draft_changed")
        if not item["eligible"] and not item["hold"] and (state["old"] or state["new"]):
            raise RuntimeError("excluded_draft_not_rejected")

def audit():
    """Independent read-only pass, reusable before and after a sync."""
    global DIAGNOSTIC_STAGE
    DIAGNOSTIC_STAGE = "target"
    legacy.target_guard()
    DIAGNOSTIC_STAGE = "credential"
    conn = authorized_writer()
    DIAGNOSTIC_STAGE = "sheet"
    expected = load_private_scope(conn)
    DIAGNOSTIC_STAGE = "registry"
    verify_suppressions(conn, expected)
    DIAGNOSTIC_STAGE = "connect"
    client = connect_imap()
    try:
        DIAGNOSTIC_STAGE = "folder"
        folder = find_drafts_folder(client)
        DIAGNOSTIC_STAGE = "select"
        validity = legacy.select(client, folder, readonly=True)
        DIAGNOSTIC_STAGE = "scan"
        records = transport.scan(client)
        DIAGNOSTIC_STAGE = "classify"
        held_cleared = len(records) == EXPECTED_ELIGIBLE
        groups = classify(records, expected, held_cleared=held_cleared)
        if not validity or len(records) not in {EXPECTED_MAILBOX, EXPECTED_ELIGIBLE}:
            raise RuntimeError("audit_mailbox_inventory_invalid")
        DIAGNOSTIC_STAGE = "complete"
        return {"total": len(records), "source_copy":sum(len(g["old"]) for k,g in groups.items() if expected[k]["eligible"]),
                "review_copy":sum(len(g["new"]) for k,g in groups.items() if expected[k]["eligible"]),
                "holds":sum(len(g["old"]) for k,g in groups.items() if expected[k]["hold"])}
    finally:
        try:
            client.logout()
        except Exception:
            pass


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
        old_uids = {u for key,item in expected.items() if item["eligible"] or item["hold"]
                    for u in staged[key]["old"]}
        if len(old_uids) != EXPECTED_MAILBOX:
            raise RuntimeError("old_scope_not_exact_412")
        old_hash = {uid: ready[uid]["sha256"] for uid in old_uids}
        if load_private_scope(conn) != expected:
            raise RuntimeError("private_review_changed_before_remove")
        verify_suppressions(conn, expected)
        # Re-read all messages with a writable selection before targeted remove.
        if legacy.select(client, folder, readonly=False) != validity:
            raise RuntimeError("uidvalidity_changed")
        before = transport.scan(client)
        if set(before) != set(ready):
            raise RuntimeError("mailbox_changed_before_remove")
        again = classify(before, expected)
        verify_new_complete(again, expected)
        if {u for key,item in expected.items() if item["eligible"] or item["hold"]
                for u in again[key]["old"]} != old_uids:
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
        final_groups = classify(final, expected, held_cleared=True)
        verify_new_complete(final_groups, expected, held_cleared=True)
        if any(final_groups[key]["old"] for key,item in expected.items() if item["eligible"] or item["hold"]):
            raise RuntimeError("stale_drafts_remain")
        if len(final) != EXPECTED_ELIGIBLE:
            raise RuntimeError("final_draft_count_invalid")
        return {"rewritten": EXPECTED_ELIGIBLE, "cleared_unverified": EXPECTED_HOLD,
                "excluded": EXPECTED_EXCLUDED, "created": created,
                "removed": removed, "remaining": len(final)}
    finally:
        try:
            client.logout()
        except Exception:
            pass


def main():
    mode = os.environ.get("MAILBOX_VALUEFIRST_MODE", "")
    if os.environ.get("MAILBOX_VALUEFIRST_TASK") != TASK or mode not in {"audit", "sync"}:
        print("MYHOST_VALUEFIRST=blocked reason=unauthorized_task sent=0")
        return 1
    try:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            output = audit() if mode == "audit" else reconcile()
        label = "audit_green" if mode == "audit" else "sync_green"
        print("MYHOST_VALUEFIRST=" + label + " " + " ".join(
            f"{key}={value}" for key,value in output.items()) + " sent=0")
        return 0
    except Exception as exc:
        # Show only fixed internal error codes, never any provider exception text.
        safe = {
            "private_450_scope_invalid", "private_450_row_invalid",
            "private_450_identity_or_copy_invalid", "review_identity_or_source_changed",
            "review_copy_incomplete", "review_score_invalid", "review_score_below_nine",
            "review_body_invalid", "human_copy_or_gate_invalid", "hold_gate_invalid",
            "original_exclusion_changed", "eligibility_snapshot_changed",
            "unclassified_source_hold", "historically_suppressed_before_draft",
            "suppression_changed_since_review", "existing_review_draft_edited_or_unrecognized",
            "expected_review_draft_missing", "held_draft_changed_or_missing",
            "unrelated_drafts_present_preserve_them", "excluded_draft_present",
            "review_draft_flag_or_sender_changed", "ambiguous_draft_versions",
            "duplicate_review_draft_version", "audit_mailbox_inventory_invalid",
            "imap_drafts_select_failed", "imap_uid_search_failed",
            "imap_batch_metadata_incomplete", "imap_batch_body_failed",
            "imap_batch_readback_incomplete", "private_sheet_read_failed",
            "private_sheet_shape_invalid", "review_row_invalid",
            "private_batch_headers_invalid", "review_source_not_verified"
        }
        code = str(exc)
        safe.update({"registry_read_failed", "registry_credentials_missing",
                     "historical_suppression_unavailable", "historical_v2_headers_missing",
                     "historical_v2_incomplete", "historical_v2_bad_hash_key_or_domain",
                     "historical_v2_duplicate_identity", "historical_v2_source_overflow",
                     "historical_v2_vault_unavailable_or_modified", "historical_v2_vault_key_invalid",
                     "historical_v2_row_shape_invalid", "registry_auth_invalid", "registry_dedupe_unreadable",
                     "registry_vault_unreadable", "registry_historical_unreadable"})
        code = code if type(exc) is RuntimeError and code in safe else "private_preflight_or_imap_failed"
        print("MYHOST_VALUEFIRST=blocked stage=" + DIAGNOSTIC_STAGE + " registry=" + REGISTRY_DIAGNOSTIC_STAGE + " reason=" + code + " sent=0")
        return 1


if __name__ == "__main__":
    sys.exit(main())
