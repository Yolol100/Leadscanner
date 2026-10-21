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
from short_email_policy import validate_short_email

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


def load_alternate_versions(session, expected):
    """Read known historical private copy generations; never accept an unknown UID.

    These are only comparison fingerprints, not authorization to update mail.
    None of the version content, recipient data or individual IDs is logged.
    """
    specs = {
        "original": ("Review450!A2:P451", 0, 2, 5, 6),
        "openingen": ("OpeningenReview20261016!A2:Q451", 1, 2, 3, 7),
        "conceptkwaliteit": ("'Conceptkwaliteit 20261018'!A2:M451", 1, 2, 4, 7),
    }
    versions = {name: {} for name in (*specs, "gespreksstijl")}
    for name, (range_a1, id_col, company_col, subject_col, body_col) in specs.items():
        rows = review.read(session, review.SID, range_a1)
        if len(rows) != 450:
            raise RuntimeError("private_versions_count_invalid")
        for row in rows:
            if (len(row) <= max(id_col, company_col)
                    or row[id_col] not in expected
                    or row[company_col] != expected[row[id_col]]["company"]
                    or row[id_col] in versions[name]):
                raise RuntimeError("private_versions_identity_invalid")
            subject = row[subject_col] if len(row) > subject_col else ""
            body = row[body_col] if len(row) > body_col else ""
            if subject and body:
                versions[name][row[id_col]] = dict(
                    expected[row[id_col]], subject=subject, body=body)
    for batch in range(1, 6):
        size = 50 if batch == 5 else 100
        rows = review.read(
            session, review.SID,
            f"'Gespreksstijl Fase{batch} 20261016'!A2:M{size + 1}")
        if len(rows) != size:
            raise RuntimeError("private_versions_count_invalid")
        for offset, row in enumerate(rows, 1):
            number = (batch - 1) * 100 + offset
            if (len(row) < 3 or row[0] != str(number)
                    or row[1] not in expected
                    or row[2] != expected[row[1]]["company"]
                    or row[1] in versions["gespreksstijl"]):
                raise RuntimeError("private_versions_identity_invalid")
            if len(row) > 7 and row[6] and row[7]:
                versions["gespreksstijl"][row[1]] = dict(
                    expected[row[1]], subject=row[6], body=row[7])
    return versions


def matches_current_style(row):
    """Apply the active single-format validator to an already matched source row."""
    try:
        validate_short_email(row)
    except RuntimeError:
        return False
    return True


def audit():
    session = authorized_session()
    expected = load_expected(session)
    versions = load_alternate_versions(session, expected)
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
        exact_new_style = exact_legacy_style = 0
        generation_counts = {name: 0 for name in versions}
        unrecognized = 0
        for record in inventory.values():
            key = record["draft_id"]
            if key not in expected:
                continue
            matched = False
            for name, generation in versions.items():
                row = generation.get(key)
                if row and record["draft_flag"] and _matches(
                        build_message({"draft_id": key, **row}), record["message"]):
                    generation_counts[name] += 1
                    matched = True
            if not matched and record["draft_flag"] and not _matches(
                    build_message({"draft_id": key, **expected[key]}),
                    record["message"]):
                unrecognized += 1
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
                if matches_current_style(row):
                    exact_new_style += 1
                else:
                    exact_legacy_style += 1
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
            "exact_new_style": exact_new_style,
            "exact_legacy_style": exact_legacy_style,
            "missing": missing, "duplicates": duplicate,
            "blocked_existing": blocked_existing,
            "suppressed_eligible": suppressed,
            "uidvalidity_ok": bool(validity),
            "unrecognized_generations": unrecognized,
            **{"generation_" + name: count
               for name, count in generation_counts.items()},
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


def cohort_acceptance_state(stats):
    """Separate a successful read from proven draft-cohort acceptance.

    In particular, zero recognized IDs is not evidence that a historic cohort
    was deleted: the account/folder/source identity may be wrong.
    """
    if stats["eligible"] > 0 and stats["known"] == 0:
        return "unverified_mailbox_cohort"
    if any(stats[field] for field in (
            "missing", "stale", "duplicates",
            "blocked_existing", "unrecognized_generations")):
        return "mismatch"
    if (stats["exact"] != stats["eligible"]
            or stats["exact_new_style"] != stats["eligible"]):
        return "needs_review"
    return "verified"


def main():
    try:
        # External libraries must never log private rows or mailbox contents.
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            stats = audit()
        state = cohort_acceptance_state(stats)
        print("MYHOST_450_READONLY=cohort_status=" + state + " " + " ".join(
            f"{key}={str(value).lower() if isinstance(value, bool) else value}"
            for key, value in stats.items()
        ) + " sent=0 deleted=0 created=0")
        return 0 if state == "verified" else 1
    except Exception:
        print("MYHOST_450_READONLY=blocked reason=private_preflight_or_imap_unverified sent=0")
        return 1


if __name__ == "__main__":
    sys.exit(main())
