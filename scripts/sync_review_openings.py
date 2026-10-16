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
EXPECTED_ELIGIBLE = 407
EXPECTED_HOLD = 5
EXPECTED_EXCLUDED = 38
EXPECTED_MAILBOX = 412
OPT = "Liever geen e-mails meer? Antwoord met 'nee', dan laat ik het hierbij."


def load_private_scope(session):
    originals = historical.load_rows(session)
    source_rows = historical.read(session, historical.SID, "QA450Actueel!A2:P451")
    latest_rows = historical.read(session, historical.SID, "OpeningenReview20261016!A2:Q451")
    frozen_rows = historical.read(session, historical.SID, "Backup_407_Fase8_20261016!A2:Q451")
    prior_rows = historical.read(session, historical.SID, "Backup_404_Sync_Review_20261016!A2:Q451")
    if (len(originals) != 450 or len(source_rows) != 450
            or len(latest_rows) != 450 or len(prior_rows) != 450
            or latest_rows != frozen_rows):
        raise RuntimeError("private_review_changed_since_snapshot")
    expected = {}
    for number, (baseline, src, latest_raw, prior_raw) in enumerate(
            zip(originals, source_rows, latest_rows, prior_rows), 1):
        now = (latest_raw + [""]*17)[:17]
        previous = (prior_raw + [""]*17)[:17]
        if (len(src) != 16 or src[0] != str(number)
                or len(latest_raw) > 17 or len(prior_raw) > 17):
            raise RuntimeError("private_450_row_invalid")
        key = src[1]
        if (not DRAFT_RE.fullmatch(key) or key in expected
                or baseline["draft_id"] != key or baseline["company"] != src[2]
                or baseline["email"].casefold() != src[3].casefold()
                or baseline["subject"] != src[4]
                or any(q[0] != src[0] or q[1] != key or
                       q[2] != src[2] or q[4] != src[8]
                       for q in (now, previous))
                or not src[8].startswith(("https://","http://"))
                or OPT not in src[6] or len(src[6].split()) > 110):
            raise RuntimeError("private_450_identity_or_copy_invalid")
        old = {"draft_id":key,"company":src[2],"email":src[3],
               "source_url":src[8],"subject":src[5],"body":src[6]}
        active = src[13] in CANDIDATE_STATUSES
        eligible = active and now[10] == "MENSELIJKE_EINDCONTROLE"
        hold = active and (now[10].startswith("HOLD")
                           or now[10] == "BRONCHECK_VOOR_VERZENDING")
        if active and not (eligible or hold):
            raise RuntimeError("unclassified_source_hold")
        if not active and (now[8] != "NIET AANPASSEN" or now[7]):
            raise RuntimeError("original_exclusion_changed")
        if active:
            try:
                score = float(now[12])
            except (TypeError, ValueError):
                raise RuntimeError("review_score_invalid")
            body = now[7]
            bits = body.split("\n\n")
            if (not 9 <= score <= 10 or len(bits) != 5
                    or bits[0] not in {"Goedendag,","Hoi,"}
                    or bits[1] != now[6]
                    or not bits[2].startswith(("Zal ","Mag ","Zou "))
                    or bits[2].count("?") != 1
                    or bits[3] != OPT or bits[4] != "Groet,\nAndrew"
                    or body.count(OPT) != 1 or len(body.split()) > 110
                    or not now[14].startswith("FASE ")
                    or any(c in body + now[3] for c in ("{{","}}","\x00"))
                    or not 5 <= len(now[3]) <= 160):
                raise RuntimeError("review_body_invalid")
        if eligible and not now[15].startswith("ALLEEN CONCEPT"):
            raise RuntimeError("human_review_gate_invalid")
        if hold and not now[15].startswith(("NIET VERSTUREN","ALLEEN CONCEPT")):
            raise RuntimeError("hold_gate_invalid")
        newer = {**old,"subject":now[3],"body":now[7]} if eligible else old
        prior = None
        if eligible and previous[10] == "MENSELIJKE_EINDCONTROLE":
            if previous[7] and (previous[3],previous[7]) != (now[3],now[7]):
                prior = {**old,"subject":previous[3],"body":previous[7]}
        expected[key]={"old":old,"new":newer,"prior":prior,
                       "eligible":eligible,"hold":hold}
    if (len(expected) != 450
            or sum(x["eligible"] for x in expected.values()) != 407
            or sum(x["hold"] for x in expected.values()) != 5
            or sum(not(x["eligible"] or x["hold"]) for x in expected.values()) != 38
            or sum(x["prior"] is not None for x in expected.values()) != 1):
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


def classify(inventory, expected, *, post=False):
    """Exact UID+copy classification, including one former reviewed version."""
    grouped = defaultdict(lambda: {"old":[],"new":[],"prior":[]})
    for uid, record in inventory.items():
        key=record["draft_id"]
        if key not in expected:
            raise RuntimeError("unrelated_drafts_present_preserve_them")
        if (not record["draft_flag"] or b"\\DELETED" in record["flags"]
                or parseaddr(record["message"].get("From",""))[1].casefold()!=legacy.USER):
            raise RuntimeError("review_draft_flag_or_sender_changed")
        item=expected[key]
        kinds = []
        for kind in ("old","new","prior"):
            if kind == "new" and not item["eligible"]:
                continue
            part=item.get(kind)
            if part is not None and _matches(build_message(part),record["message"]):
                kinds.append(kind)
        if len(kinds)!=1:
            raise RuntimeError("existing_review_draft_edited_or_unrecognized")
        grouped[key][kinds[0]].append(uid)
    for key,item in expected.items():
        state=grouped[key]
        if any(len(state[k])>1 for k in ("old","new","prior")):
            raise RuntimeError("duplicate_review_draft_version")
        if item["eligible"] and not (state["old"] or state["new"] or state["prior"]):
            raise RuntimeError("expected_review_draft_missing")
        if item["hold"] and (len(state["old"]) != (0 if post else 1)
                             or state["new"] or state["prior"]):
            raise RuntimeError("held_draft_changed_or_missing")
        if not item["eligible"] and not item["hold"] and any(state.values()):
            raise RuntimeError("excluded_draft_present")
        if post and (state["old"] or state["prior"]):
            raise RuntimeError("stale_drafts_remain")
    return grouped

def verify_new_complete(groups, expected, *, post=False):
    for key,item in expected.items():
        state=groups[key]
        if item["eligible"] and len(state["new"]) != 1:
            raise RuntimeError("new_draft_not_verified")
        if item["hold"] and (len(state["old"]) != (0 if post else 1)
                             or state["new"] or state["prior"]):
            raise RuntimeError("held_draft_changed")
        if post and (state["old"] or state["prior"]):
            raise RuntimeError("stale_drafts_remain")
        if not item["eligible"] and not item["hold"] and any(state.values()):
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
        groups = classify(records, expected, post=held_cleared)
        if not validity or len(records) not in {EXPECTED_MAILBOX, EXPECTED_ELIGIBLE, 816, 819}:
            raise RuntimeError("audit_mailbox_inventory_invalid")
        DIAGNOSTIC_STAGE = "complete"
        return {"total": len(records), "source_copy":sum(len(g["old"]) for k,g in groups.items() if expected[k]["eligible"]),
                "review_copy":sum(len(g["new"]) for k,g in groups.items() if expected[k]["eligible"]),
                "holds":sum(len(g["old"]) for k,g in groups.items() if expected[k]["hold"]),
                "prior":sum(len(g["prior"]) for g in groups.values())}
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
                    for u in staged[key]["old"] + staged[key]["prior"]}
        if len(old_uids) != EXPECTED_MAILBOX + 1:
            raise RuntimeError("old_scope_not_exact_413")
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
                for u in again[key]["old"] + again[key]["prior"]} != old_uids:
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
        final_groups = classify(final, expected, post=True)
        verify_new_complete(final_groups, expected, post=True)
        if any(final_groups[key]["old"] or final_groups[key]["prior"] for key,item in expected.items() if item["eligible"] or item["hold"]):
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
