"""One existing Leadscanner IMAP Drafts continuation, never a second scanner.

Read exact private 450 sources and fresh Leadscanner WebsiteEvidence. Preserve
original MIME in a private IMAP archive before replacing any authorized draft.
No SMTP, scheduling, public recipient data or unscoped EXPUNGE.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO

import draft_management as drafts
import fast_website_evidence as websites
import replace450 as imap
import replace450_fast as transport
import sync450_openings as history
from myhost_draft import _matches, build_message, connect_imap, find_drafts_folder
from private_candidate_handoff import authorized_writer
from private_imap_archive import PrivateIMAPArchive
from registry_readonly import load_discovery_suppressions

ISSUE = 1659
REPO = "Yolol100/Leadscanner"
OWNER = "Yolol100"
PREFIX = "LEADS_CONVERSATIONS_V1:"
MODES = frozenset({"PRECHECK", "PILOT", "AUDIT"} |
                  {f"BATCH_{i}" for i in range(1, 6)})
TABS = tuple((f"Gespreksstijl Fase{i} 20261016", 100 if i < 5 else 50)
             for i in range(1, 6))
EXPECTED_COUNTS = {"target": 391, "source_hold": 16, "held": 4,
                   "closed": 1, "excluded": 38}
OPT = "Liever geen e-mails meer? Antwoord met 'nee', dan laat ik het hierbij."


def authorize(event, mode):
    if mode not in MODES or not isinstance(event, dict):
        raise RuntimeError("conversation_mode_unauthorized")
    if (event.get("action") != "created"
            or (event.get("repository") or {}).get("full_name") != REPO
            or (event.get("issue") or {}).get("number") != ISSUE
            or (event.get("issue") or {}).get("pull_request")
            or (event.get("comment") or {}).get("body") != PREFIX + mode
            or (event.get("comment") or {}).get("user", {}).get("login") != OWNER
            or (event.get("comment") or {}).get("author_association") != "OWNER"):
        raise RuntimeError("conversation_owner_authorization_denied")


def review_body(value):
    if not isinstance(value, str) or len(value.split()) > 110:
        raise RuntimeError("conversation_review_body_invalid")
    parts = value.replace("\r\n", "\n").strip().split("\n\n")
    if (len(parts) != 5 or parts[0] != "Hoi,"
            or not parts[1] or "?" in parts[1]
            or not parts[2].endswith("?") or parts[2].count("?") != 1
            or parts[3] != OPT or parts[4] != "Groet,\nAndrew"
            or "Was gewoon benieuwd." in value or "{{" in value):
        raise RuntimeError("conversation_review_body_invalid")


def _private_rows(conn):
    older = history.load_scope(conn)
    # Every historical source must remain available, including the independent
    # HMAC vault and current private LeadHistory/DraftQueue. Never clear them.
    load_discovery_suppressions(session=conn)
    history.verify_suppressions(conn, older)
    reviews = []
    for tab, length in TABS:
        raw = history.source.read(
            conn, history.source.SID, "'" + tab + "'!A1:M" + str(length+1))
        if (len(raw) != length+1 or raw[0] != [
            "Nr", "Bestaand Draft-ID", "Bedrijf", "Officiële bron",
            "Bronfeit uit vorige controle", "Dienstaansluiting intern",
            "Onderwerp nieuw", "Tekstvoorstel - interne review",
            "Redactionele score /10", "Redactionele status", "Bronstatus",
            "Juridische status", "Mijn.Host status",
        ]):
            raise RuntimeError("conversation_review_sheet_scope_invalid")
        reviews.extend(raw[1:])
    if len(reviews) != 450:
        raise RuntimeError("conversation_review_missing")
    official = history.source.read(conn, history.source.SID, "Review450!A1:P451")
    evidence = history.source.read(conn, history.source.SID, "WebsiteEvidence!A1:N1000")
    if len(official) != 451 or official[0] != list(websites.REVIEW_COLUMNS):
        raise RuntimeError("conversation_official_source_changed")
    if not evidence or evidence[0] != list(websites.COLUMNS):
        raise RuntimeError("conversation_evidence_missing")
    found = {}
    for raw in evidence[1:]:
        if len(raw) != len(websites.COLUMNS):
            raise RuntimeError("conversation_evidence_row_invalid")
        if raw[0] in found:
            raise RuntimeError("conversation_evidence_duplicate")
        found[raw[0]] = raw
    counts = {k: 0 for k in EXPECTED_COUNTS}
    mapped = {}
    questions = set()
    now = datetime.now(timezone.utc)
    for number, (proposal, proof) in enumerate(zip(reviews, official[1:]), start=1):
        key = proof[0]
        base = older.get(key)
        if (not base or len(proposal) != 13 or len(proof) != 16
                or proposal[0] != str(number)
                or proposal[1] != key or proof[0] != key
                or proposal[2] != base["old"]["company"]
                or proposal[3] != base["old"]["source_url"]
                or proof[2] != base["old"]["company"]
                or proof[3].casefold() != base["old"]["email"].casefold()):
            raise RuntimeError("conversation_source_identity_mismatch")
        evidence_row = found.get("Review450:" + key)
        if (not evidence_row or evidence_row[1] != "Review450"
                or evidence_row[2] != str(number + 1)
                or evidence_row[4] != proof[2]
                or evidence_row[5] != proof[7]
                or evidence_row[6].casefold() != proof[3].casefold()
                or evidence_row[3] != websites._digest(
                    [proof[2], proof[7], proof[3], proof[9]])):
            raise RuntimeError("conversation_official_evidence_identity_mismatch")
        try:
            checked = datetime.fromisoformat(
                evidence_row[11].replace("Z", "+00:00"))
            if checked.tzinfo is None or not 0 <= (now-checked).total_seconds() < 86400:
                raise ValueError("evidence stale")
        except (ValueError, TypeError, AttributeError):
            raise RuntimeError("conversation_official_evidence_stale") from None
        old_category = base["category"]
        if old_category in {"closed", "excluded", "held"}:
            category = old_category
            if proposal[7] or proposal[9] != "OVERGESLAGEN - BRONBLOKKADE":
                raise RuntimeError("conversation_blocked_entry_modified")
        elif evidence_row[12] == "needs_manual_check":
            category = "source_hold"
            # A proposal may exist but must never cause a mailbox mutation.
        elif evidence_row[12] in {"verified_activity_only", "verified_with_detail"}:
            category = "target"
            if proposal[9] != "VOORLOPIG REDACTIONEEL VOORSTEL":
                raise RuntimeError("conversation_review_not_ready")
            review_body(proposal[7])
            question = proposal[7].split("\n\n")[2]
            if question in questions:
                raise RuntimeError("conversation_duplicate_question")
            questions.add(question)
        else:
            raise RuntimeError("conversation_website_not_verified")
        current = base["new"] if old_category == "ready" else base["old"]
        new = {"draft_id": key, "company": proof[2], "email": proof[3],
               "source_url": proof[4], "subject": proposal[6],
               "body": proposal[7]}
        mapped[key] = {"category": category, "number": number,
                       "current": current, "new": new,
                       "website_status": evidence_row[12]}
        counts[category] += 1
    if counts != EXPECTED_COUNTS or len(mapped) != 450:
        raise RuntimeError("conversation_population_changed")
    return mapped


def _digest(records):
    return hashlib.sha256(json.dumps([
        (key, row["category"], row["current"]["subject"],
         row["current"]["body"], row["new"]["subject"], row["new"]["body"])
        for key, row in records.items()
    ], ensure_ascii=True).encode()).hexdigest()


def _classify(records, inventory):
    state = {}
    for uid, item in inventory.items():
        key = item["draft_id"]
        if key not in records:
            raise RuntimeError("conversation_unrelated_message_in_drafts")
        record = records[key]
        if (not item["draft_flag"] or b"\\DELETED" in item["flags"]):
            raise RuntimeError("conversation_draft_flags_changed")
        from email.utils import parseaddr
        if parseaddr(item["message"].get("From", ""))[1].casefold() != imap.USER:
            raise RuntimeError("conversation_sender_changed")
        if key in state:
            raise RuntimeError("conversation_duplicate_draft_id")
        if record["category"] == "target" and _matches(
                build_message(record["new"]), item["message"]):
            version = "new"
        elif _matches(build_message(record["current"]), item["message"]):
            version = "old"
        else:
            raise RuntimeError("conversation_mailbox_message_changed")
        state[key] = (uid, version, item["sha256"])
    for key, record in records.items():
        has = key in state
        if record["category"] in {"target", "source_hold", "held"} and not has:
            raise RuntimeError("conversation_expected_draft_missing")
        if record["category"] in {"closed", "excluded"} and has:
            raise RuntimeError("conversation_excluded_or_closed_has_draft")
        if has and record["category"] != "target" and state[key][1] != "old":
            raise RuntimeError("conversation_blocked_draft_modified")
    if len(inventory) != 411:
        raise RuntimeError("conversation_mailbox_count_changed")
    return state


def _verified_scope(session, previous=None):
    current = _private_rows(session)
    if previous is not None and _digest(current) != previous:
        raise RuntimeError("conversation_private_sources_changed")
    return current


def _check_mailbox(connector=connect_imap, records=None):
    client = connector()
    try:
        folder = find_drafts_folder(client)
        validity = imap.select(client, folder, readonly=True)
        scan = transport.scan(client)
        before = set(scan)
        if before != imap.uidset(client):
            raise RuntimeError("conversation_mailbox_changed_during_scan")
        return folder, validity, _classify(records, scan)
    finally:
        try:
            client.logout()
        except Exception:
            pass


def run(mode, event, *, connector=connect_imap):
    authorize(event, mode)
    imap.target_guard()
    session = authorized_writer()
    records = _verified_scope(session)
    snapshot = _digest(records)
    folder, validity, state = _check_mailbox(connector, records)
    probe = connector()
    try:
        if not imap.uidplus(probe):
            raise RuntimeError("conversation_uidplus_required")
    finally:
        try:
            probe.logout()
        except Exception:
            pass
    total_target = sum(row["category"] == "target" for row in records.values())
    changed = sum(version == "new" for key, (uid, version, sha) in state.items()
                  if records[key]["category"] == "target")
    if mode in {"PRECHECK", "AUDIT"}:
        return {"total": len(state), "eligible": total_target,
                "already_new": changed,
                "blocked": EXPECTED_COUNTS["source_hold"] + EXPECTED_COUNTS["held"],
                "sent": 0}
    number = 1 if mode == "PILOT" else None
    batch = int(mode.rsplit("_", 1)[1]) if mode.startswith("BATCH_") else None
    allowed = [
        key for key, record in records.items()
        if record["category"] == "target"
        and (record["number"] == number if number else
             (record["number"]-1)//100+1 == batch)
    ]
    if not allowed:
        raise RuntimeError("conversation_batch_empty")
    archive = PrivateIMAPArchive(connector=connector)
    installed = skipped = 0
    for key in allowed:
        orig_uid, generation, original_sha = state[key]
        if generation == "new":
            skipped += 1
            continue
        # Recheck all private source material and historical opt-outs before
        # each destructive operation, not just when the GitHub run starts.
        def check_source():
            _verified_scope(session, previous=snapshot)
            return True
        current_event = dict(event)
        current_event["comment"] = dict(event["comment"],
                                        body="LEADS_MANAGE_V1:UPDATE_DRAFT:" + key)
        expected = {"folder": folder, "uidvalidity": validity,
                    "uid": orig_uid, "sha256": original_sha}
        result = drafts.execute(
            current_event, "UPDATE_DRAFT", key,
            row=records[key]["new"], expected=expected,
            check_source=check_source, snapshots=archive, connector=connector)
        if result["status"] != "verified":
            raise RuntimeError("conversation_independent_readback_failed")
        installed += 1
    _, follow_validity, follow = _check_mailbox(connector, records)
    if follow_validity != validity:
        raise RuntimeError("conversation_uidvalidity_changed")
    for key in allowed:
        if follow[key][1] != "new":
            raise RuntimeError("conversation_batch_final_verification_failed")
    return {"total": len(follow), "eligible": total_target,
            "installed": installed, "already_new": skipped,
            "blocked": EXPECTED_COUNTS["source_hold"] + EXPECTED_COUNTS["held"],
            "sent": 0}


def main():
    mode = os.getenv("CONVERSATION_MODE", "")
    try:
        if mode not in MODES or os.getenv("GITHUB_EVENT_NAME") != "issue_comment":
            raise RuntimeError("conversation_mode_invalid")
        with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
            event = json.load(f)
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            result = run(mode, event)
        print("CONVERSATION411=green " +
              " ".join(f"{k}={v}" for k, v in result.items()))
        return 0
    except Exception:
        print("CONVERSATION411=blocked confidential_details_suppressed sent=0")
        return 1


if __name__ == "__main__":
    sys.exit(main())
