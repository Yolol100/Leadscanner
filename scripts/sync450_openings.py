"""Owner-gated phased IMAP sync of 407 verified private lead drafts.

Never send. Keep 4 unresolved reviews unchanged and remove 1 closed
business only after exact UID/hash verification. 38 exclusions untouched.
Private addresses, UIDs, copy and message bodies never enter logs.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import redirect_stdout, redirect_stderr
from email.utils import parseaddr
from io import StringIO
import os
import re
import sys

import replace450 as legacy
import replace450_fast as transport
import review450 as source
from dedupe_preflight import match_candidate
from myhost_draft import _mailbox_arg, _matches, build_message, connect_imap, find_drafts_folder
from private_candidate_handoff import authorized_writer
from registry_readonly import load_suppressions

TASK = "opening-review-20261016"
OPT = "Liever geen e-mails meer? Antwoord met 'nee', dan laat ik het hierbij."
DRAFT_RE = re.compile(r"draft-[0-9a-f]{32}\Z")
ELIGIBLE = {"VOOR_MENSELIJKE_EINDCONTROLE", "VOORSTEL_HANDMATIGE_EINDCHECK"}
HOLD_NUMBERS = frozenset({"90", "121", "292", "355"})
CLOSED_NUMBER = "70"
READY_COUNT = 407
HOLD_COUNT = 4
CLOSED_COUNT = 1
EXCLUDED_COUNT = 38
SOURCE_COUNT = 450
PHASE_SIZE = 100


def check_body(body, *, old=False):
    if not isinstance(body, str) or len(body.split()) > 110 or "{{" in body or "}}" in body:
        raise RuntimeError("review_body_invalid")
    paragraphs = body.replace("\r\n", "\n").strip().split("\n\n")
    q_index = 3 if old else 2
    opt_index = 4 if old else 3
    sign_index = 5 if old else 4
    if (len(paragraphs) != (6 if old else 5)
            or paragraphs[0] not in {"Goedendag,", "Hoi,"}
            or paragraphs[opt_index] != OPT
            or paragraphs[sign_index] != "Groet,\nAndrew"
            or not paragraphs[1] or not re.match(r"^(Zal|Mag|Zou)\b", paragraphs[q_index])
            or paragraphs[q_index].count("?") != 1
            or body.split(OPT, 1)[0].count("?") != 1):
        raise RuntimeError("review_body_invalid")


def load_scope(session):
    old = source.read(session, source.SID, "QA450Actueel!A2:P451")
    reviewed = source.read(session, source.SID, "OpeningenReview20261016!A2:Q451")
    if len(old) != SOURCE_COUNT or len(reviewed) != SOURCE_COUNT:
        raise RuntimeError("private_source_scope_changed")
    result, counts = {}, defaultdict(int)
    for n, (raw, r) in enumerate(zip(old, reviewed), start=1):
        if (len(raw) != 16 or len(r) < 11 or raw[0] != str(n)
                or r[0] != raw[0] or r[1] != raw[1] or r[2] != raw[2]
                or r[4] != raw[8] or not DRAFT_RE.fullmatch(raw[1])
                or raw[1] in result or not raw[5] or not raw[6]):
            raise RuntimeError("private_review_identity_changed")
        if raw[13] not in ELIGIBLE:
            if r[8] != "NIET AANPASSEN":
                raise RuntimeError("excluded_review_modified")
            category = "excluded"
        else:
            if len(r) != 17 or not r[3] or not r[7] or not r[12]:
                raise RuntimeError("private_review_incomplete")
            check_body(raw[6], old=True)
            check_body(r[7])
            if not 9 <= float(r[12]) <= 10:
                raise RuntimeError("private_review_score_invalid")
            if raw[0] == CLOSED_NUMBER:
                if (r[10] != "HOLD_GESLOTEN_20260927"
                        or "NIET VERSTUREN" not in r[15]):
                    raise RuntimeError("closed_business_not_blocked")
                category = "closed"
            elif raw[0] in HOLD_NUMBERS:
                if not r[10].startswith("HOLD"):
                    raise RuntimeError("open_source_hold_bypassed")
                category = "held"
            elif r[10] == "MENSELIJKE_EINDCONTROLE":
                category = "ready"
            else:
                raise RuntimeError("unreviewed_entry_cannot_sync")
        counts[category] += 1
        result[raw[1]] = {
            "number": raw[0], "category": category,
            "old": {"draft_id": raw[1], "company": raw[2], "email": raw[3],
                    "source_url": raw[8], "subject": raw[5], "body": raw[6]},
            "new": {"draft_id": raw[1], "company": raw[2], "email": raw[3],
                    "source_url": raw[8], "subject": r[3] if len(r) > 3 else "",
                    "body": r[7] if len(r) > 7 else ""},
        }
    if dict(counts) != {"ready": READY_COUNT, "held": HOLD_COUNT,
                        "closed": CLOSED_COUNT, "excluded": EXCLUDED_COUNT}:
        raise RuntimeError("review_population_changed")
    return result


def verify_suppressions(session, expected):
    suppressions = load_suppressions(session=session)
    for row in expected.values():
        if row["category"] in {"excluded", "closed"}:
            continue
        old = row["old"]
        if match_candidate({
            "name_hint": old["company"], "website_hint": old["source_url"],
            "email": old["email"],
        }, suppressions) is not None:
            raise RuntimeError("historical_suppression_changed")


def classify(inventory, expected):
    grouped = defaultdict(lambda: {"old": [], "new": []})
    for uid, item in inventory.items():
        key = item["draft_id"]
        if key not in expected:
            raise RuntimeError("unrelated_mailbox_message_preserved")
        row = expected[key]
        if (not item["draft_flag"] or b"\\DELETED" in item["flags"]
                or parseaddr(item["message"].get("From", ""))[1].casefold() != legacy.USER):
            raise RuntimeError("draft_flag_or_sender_changed")
        if row["category"] == "ready" and _matches(build_message(row["new"]), item["message"]):
            grouped[key]["new"].append(uid)
        elif _matches(build_message(row["old"]), item["message"]):
            grouped[key]["old"].append(uid)
        else:
            raise RuntimeError("unrecognized_or_manually_edited_draft")
        if len(grouped[key]["old"]) > 1 or len(grouped[key]["new"]) > 1:
            raise RuntimeError("duplicate_draft_generation")
    for key, row in expected.items():
        state = grouped[key]
        if row["category"] == "ready" and not (state["old"] or state["new"]):
            raise RuntimeError("review_draft_missing")
        if row["category"] == "held" and (len(state["old"]) != 1 or state["new"]):
            raise RuntimeError("held_draft_changed")
        if row["category"] == "closed" and state["new"]:
            raise RuntimeError("closed_business_has_new_draft")
        if row["category"] == "excluded" and (state["old"] or state["new"]):
            raise RuntimeError("excluded_entry_in_mailbox")
    return grouped


def verify_ready(groups, expected):
    for key, row in expected.items():
        state = groups[key]
        if row["category"] == "ready" and len(state["new"]) != 1:
            raise RuntimeError("verified_draft_not_ready")
        if row["category"] == "held" and (len(state["old"]) != 1 or state["new"]):
            raise RuntimeError("held_draft_must_remain")
        if row["category"] == "excluded" and (state["old"] or state["new"]):
            raise RuntimeError("excluded_draft_created")


def verify_complete(groups, expected, count):
    verify_ready(groups, expected)
    retained = sum(row["category"] in {"ready", "held"}
                   for row in expected.values())
    if (count != retained
            or any(groups[key]["old"] for key, row in expected.items()
                   if row["category"] in {"ready", "closed"})):
        raise RuntimeError("old_or_closed_draft_remains")


def preflight():
    legacy.target_guard()
    session = authorized_writer()
    expected = load_scope(session)
    verify_suppressions(session, expected)
    return session, expected


def install():
    session, expected = preflight()
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        uidvalidity = legacy.select(client, folder, readonly=True)
        if not legacy.uidplus(client):
            raise RuntimeError("targeted_uid_expunge_unsupported")
        groups = classify(transport.scan(client), expected)
        pending = [key for key, row in expected.items()
                   if row["category"] == "ready" and not groups[key]["new"]]
        # Keep all old drafts until every new \Draft has exact readback.
        for index in range(0, len(pending), PHASE_SIZE):
            if load_scope(session) != expected:
                raise RuntimeError("source_changed_during_phase")
            verify_suppressions(session, expected)
            batch = pending[index:index + PHASE_SIZE]
            for key in batch:
                message = build_message(expected[key]["new"])
                if client.append(_mailbox_arg(folder), "(\\Draft)", None,
                                 message.as_bytes())[0] != "OK":
                    raise RuntimeError("draft_append_failed")
            groups = classify(transport.scan(client), expected)
            for key in pending[:index + len(batch)]:
                if len(groups[key]["new"]) != 1:
                    raise RuntimeError("phase_exact_readback_failed")
        stage = transport.scan(client)
        groups = classify(stage, expected)
        verify_ready(groups, expected)
        old_uids = {uid for key, group in groups.items()
                    if expected[key]["category"] in {"ready", "closed"}
                    for uid in group["old"]}
        hashes = {uid: stage[uid]["sha256"] for uid in old_uids}
        if load_scope(session) != expected:
            raise RuntimeError("source_changed_before_targeted_cleanup")
        verify_suppressions(session, expected)
        if legacy.select(client, folder, readonly=False) != uidvalidity:
            raise RuntimeError("uidvalidity_changed")
        before = transport.scan(client)
        if set(before) != set(stage):
            raise RuntimeError("mailbox_changed_before_targeted_cleanup")
        fresh = classify(before, expected)
        verify_ready(fresh, expected)
        if ({uid for key, g in fresh.items()
             if expected[key]["category"] in {"ready", "closed"}
             for uid in g["old"]} != old_uids
                or any(before[uid]["sha256"] != hashes[uid] for uid in old_uids)):
            raise RuntimeError("old_uid_scope_or_bytes_changed")
        removed = 0
        ordered = sorted(old_uids, key=int)
        for index in range(0, len(ordered), PHASE_SIZE):
            batch = ordered[index:index + PHASE_SIZE]
            for uid in batch:
                item = legacy.fetch_message(client, uid)
                if item["sha256"] != hashes[uid] or not item["draft_flag"]:
                    raise RuntimeError("old_uid_changed_before_delete")
            uidset = ",".join(batch)
            if client.uid("STORE", uidset, "+FLAGS.SILENT", "(\\Deleted)")[0] != "OK":
                raise RuntimeError("targeted_old_mark_failed")
            if client.uid("EXPUNGE", uidset)[0] != "OK":
                raise RuntimeError("targeted_old_uid_expunge_failed")
            if set(batch) & legacy.uidset(client):
                raise RuntimeError("targeted_old_remove_not_verified")
            removed += len(batch)
        final = transport.scan(client)
        verify_complete(classify(final, expected), expected, len(final))
        return {"verified": READY_COUNT, "held": HOLD_COUNT, "closed": CLOSED_COUNT,
                "created": len(pending), "removed": removed, "remaining": len(final)}
    finally:
        try:
            client.logout()
        except Exception:
            pass


def readback():
    _, expected = preflight()
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        legacy.select(client, folder, readonly=True)
        initial = legacy.uidset(client)
        inventory = transport.scan(client)
        if legacy.uidset(client) != initial:
            raise RuntimeError("mailbox_changed_during_readback")
        verify_complete(classify(inventory, expected), expected, len(inventory))
        return {"verified": READY_COUNT, "held": HOLD_COUNT,
                "closed": CLOSED_COUNT, "remaining": len(inventory)}
    finally:
        try:
            client.logout()
        except Exception:
            pass


def main():
    if os.getenv("OPENING450_TASK") != TASK:
        print("OPENING450=blocked reason=unauthorized_task sent=0")
        return 1
    mode = os.getenv("OPENING450_MODE")
    if mode not in {"install", "readback"}:
        print("OPENING450=blocked reason=unauthorized_mode sent=0")
        return 1
    try:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            stats = install() if mode == "install" else readback()
        print("OPENING450=" + mode + "_green " +
              " ".join(f"{k}={v}" for k, v in stats.items()) + " sent=0")
        return 0
    except Exception:
        print("OPENING450=blocked reason=private_source_or_imap_unverified sent=0")
        return 1


if __name__ == "__main__":
    sys.exit(main())
