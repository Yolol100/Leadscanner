"""Read-only current-state check for the historical 450 Mijn.Host drafts.

Only anonymous counts are printed. Never APPEND, STORE, EXPUNGE or send.
No personal data, message content or recipient hashes leave the private runtime.
"""
from __future__ import annotations

import os
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import replace450 as mailbox
import replace450_fast as fast
import review450 as review
from dedupe_preflight import match_candidate
from myhost_draft import _matches, build_message, connect_imap, find_drafts_folder
from registry_readonly import authorized_session, load_suppressions

OPT_OUT = "Liever geen e-mails meer? Antwoord met 'nee', dan laat ik het hierbij."
DRAFT_RE = re.compile(r"draft-[0-9a-f]{32}\Z")
CANDIDATE_STATUSES = {"VOOR_MENSELIJKE_EINDCONTROLE", "VOORSTEL_HANDMATIGE_EINDCHECK"}


def load_expected(session):
    rows = review.read(session, review.SID, "QA450Actueel!A2:P451")
    if len(rows) != 450:
        raise RuntimeError("private_review_count_invalid")
    expected = {}
    for number, raw in enumerate(rows, 1):
        if len(raw) != 16 or raw[0] != str(number):
            raise RuntimeError("private_review_row_invalid")
        draft_id, company, recipient, subject, body, source, status = (
            raw[1], raw[2], raw[3], raw[5], raw[6], raw[8], raw[13]
        )
        if (
            not DRAFT_RE.fullmatch(draft_id)
            or draft_id in expected
            or not company or recipient.count("@") != 1
            or not source.startswith(("http://", "https://"))
            or not subject or not body
            or len(body.split()) > 110
            or OPT_OUT not in body
            or not status
        ):
            raise RuntimeError("private_review_invalid")
        expected[draft_id] = {
            "company": company, "email": recipient, "subject": subject,
            "body": body, "source_url": source,
            "blocked": status not in CANDIDATE_STATUSES,
        }
    return expected


def audit():
    session = authorized_session()
    expected = load_expected(session)
    suppressions = load_suppressions(session=session)
    suppressed = sum(
        match_candidate({
            "name_hint": row["company"],
            "website_hint": row["source_url"],
            "email": row["email"],
        }, suppressions) is not None
        for row in expected.values() if not row["blocked"]
    )
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        validity = mailbox.select(client, folder, readonly=True)
        initial = mailbox.uidset(client)
        inventory = fast.scan(client)
        if mailbox.uidset(client) != initial:
            raise RuntimeError("mailbox_changed_during_audit")
        matching = {key: [] for key in expected}
        unexpected = 0
        non_drafts = 0
        for record in inventory.values():
            draft_id = record["draft_id"]
            if not record["draft_flag"]:
                non_drafts += 1
            if draft_id in matching:
                matching[draft_id].append(record)
            else:
                unexpected += 1
        exact = stale = missing = duplicate = blocked_existing = 0
        for key, row in expected.items():
            records = matching[key]
            if row["blocked"]:
                blocked_existing += len(records)
                continue
            if not records:
                missing += 1
                continue
            if len(records) != 1:
                duplicate += 1
                continue
            if records[0]["draft_flag"] and _matches(
                build_message({"draft_id": key, **row}), records[0]["message"]
            ):
                exact += 1
            else:
                stale += 1
        return {
            "eligible": sum(not x["blocked"] for x in expected.values()),
            "blocked": sum(x["blocked"] for x in expected.values()),
            "mailbox_total": len(inventory),
            "known": len(inventory)-unexpected,
            "unrelated": unexpected,
            "nondraft": non_drafts,
            "exact": exact, "stale": stale,
            "missing": missing, "duplicates": duplicate,
            "blocked_existing": blocked_existing,
            "suppressed_eligible": suppressed,
            "uidvalidity_ok": bool(validity),
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


def main():
    try:
        # External libraries must never log private rows or mailbox contents.
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            stats = audit()
        print("MYHOST_450_READONLY=" + " ".join(
            f"{key}={str(value).lower() if isinstance(value, bool) else value}"
            for key, value in stats.items()
        ) + " sent=0 deleted=0 created=0")
        return 0
    except Exception:
        print("MYHOST_450_READONLY=blocked reason=private_preflight_or_imap_unverified sent=0")
        return 1


if __name__ == "__main__":
    sys.exit(main())
