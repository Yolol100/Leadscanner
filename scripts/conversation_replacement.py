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
import time
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
MODES = frozenset({"PRECHECK", "PILOT", "AUDIT", "BATCH_2_TO_5"} |
                  {f"BATCH_{i}" for i in range(1, 6)})
TABS = tuple((f"Gespreksstijl Fase{i} 20261016", 100 if i < 5 else 50)
             for i in range(1, 6))
EXPECTED_COUNTS = {"target": 391, "source_hold": 16, "held": 4,
                   "closed": 1, "excluded": 38}
OPT = "Liever geen e-mails meer? Antwoord met 'nee', dan laat ik het hierbij."


class RateLimitedSourceReads:
    """Gentle bounded Google Sheets reads for the current single IMAP batch.

    Avoid service-account read quota exhaustion from rechecking all 450
    private records before EACH potentially destructive draft operation.
    No cache, reduced preflight, extra permissions or public source content.
    """

    MIN_GAP_SECONDS = 1.5
    TRANSIENT = frozenset({429, 500, 502, 503, 504})
    RETRIES = 4

    def __init__(self, session, *, clock=time.monotonic, sleeper=time.sleep):
        self.session = session
        self.clock = clock
        self.sleeper = sleeper
        self.next_read = 0.0

    def get(self, url, **kwargs):
        for attempt in range(self.RETRIES):
            now = self.clock()
            if now < self.next_read:
                self.sleeper(self.next_read - now)
            # Reserve the next read slot even if the provider request fails.
            self.next_read = self.clock() + self.MIN_GAP_SECONDS
            result = self.session.get(url, **kwargs)
            if result.status_code not in self.TRANSIENT:
                return result
            if attempt + 1 == self.RETRIES:
                raise RuntimeError("conversation_sheet_transient_exhausted")
            self.sleeper(min(30, 5 * (2 ** attempt)))
        raise RuntimeError("conversation_sheet_transient_exhausted")



class _ScopedValueResponse:
    """Read-only response compatible with the existing values GET validators."""

    status_code = 200

    def __init__(self, values):
        self._values = values

    def json(self):
        # A second suppression check must never share mutable parser state.
        from copy import deepcopy
        return {"values": deepcopy(self._values)}


class ScopedSheetsSnapshot:
    """Read every private input afresh, with one batchGet per spreadsheet.

    Constructed once for EACH _private_rows preflight; never cached across
    operations, destructive checks, retries, jobs or process invocations.
    Existing source validators and independent IMAP/MIME gates are unchanged.
    """

    def __init__(self, session):
        from urllib.parse import urlencode
        import historical_v2
        import registry_readonly as registry

        review_ranges = [
            "QA450Actueel!A2:P451",
            "OpeningenReview20261016!A2:Q451",
            "LeadHistory!A:J",
            "Review450!A1:P451",
            "WebsiteEvidence!A1:N1000",
        ] + [
            "'" + tab + "'!A1:M" + str(length + 1)
            for tab, length in TABS
        ]
        groups = (
            (history.source.SID, review_ranges),
            (registry.REGISTRY_ID, [
                "DedupeRegistry!A:J", "HistoricalHmacV2!A:J",
            ]),
            (historical_v2.VAULT_SHEET_ID, ["Keys!A:J"]),
            (registry.DRAFT_QUEUE_ID, ["DraftQueue!A:J"]),
        )
        self._values = {}
        for spreadsheet_id, ranges in groups:
            endpoint = (
                "https://sheets.googleapis.com/v4/spreadsheets/"
                + spreadsheet_id + "/values:batchGet?"
                + urlencode([("ranges", value) for value in ranges])
            )
            response = session.get(endpoint, timeout=30)
            if response.status_code != 200:
                raise RuntimeError("conversation_batch_source_read_failed")
            try:
                payload = response.json()
                actual = payload["valueRanges"]
                if (payload.get("spreadsheetId") != spreadsheet_id
                        or not isinstance(actual, list)
                        or len(actual) != len(ranges)):
                    raise ValueError("batch shape")
                for requested, entry in zip(ranges, actual):
                    actual_range = entry["range"]
                    expected_tab, expected_a1 = requested.split("!", 1)
                    actual_tab, actual_a1 = actual_range.split("!", 1)
                    expected_tab = expected_tab.strip("'")
                    actual_tab = actual_tab.strip("'")
                    # Whole-column reads are expanded to the sheet row limit
                    # by the Sheets API; fixed rectangles must match exactly.
                    if re.fullmatch(r"[A-Z]+:[A-Z]+", expected_a1):
                        begin, end = expected_a1.split(":", 1)
                        valid_a1 = bool(re.fullmatch(
                            re.escape(begin) + r"1:" + re.escape(end) + r"[1-9][0-9]*",
                            actual_a1,
                        ))
                    else:
                        valid_a1 = actual_a1 == expected_a1
                    values = entry.get("values", [])
                    if (expected_tab != actual_tab or not valid_a1
                            or not isinstance(values, list)
                            or any(not isinstance(row, list) for row in values)
                            or (spreadsheet_id, requested) in self._values):
                        raise ValueError("batch range or row shape")
                    self._values[(spreadsheet_id, requested)] = values
            except (KeyError, TypeError, ValueError, AttributeError):
                raise RuntimeError("conversation_batch_source_invalid") from None

    def get(self, url, **kwargs):
        from urllib.parse import unquote, urlsplit
        target = urlsplit(url)
        matched = re.fullmatch(
            r"/v4/spreadsheets/([A-Za-z0-9_-]+)/values/(.+)",
            target.path,
        )
        if (target.scheme != "https"
                or target.netloc != "sheets.googleapis.com"
                or target.query or target.fragment or not matched):
            raise RuntimeError("conversation_unbatched_source_request")
        key = (matched.group(1), unquote(matched.group(2)))
        if key not in self._values:
            raise RuntimeError("conversation_unbatched_source_request")
        return _ScopedValueResponse(self._values[key])


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
    conn = ScopedSheetsSnapshot(conn)
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


def _verify_archived_originals(records, state, connector=connect_imap):
    """Every replaced draft must have exactly one private archived original."""
    replaced = {key for key, (uid, version, sha) in state.items()
                if version == "new" and records[key]["category"] == "target"}
    if not replaced:
        return 0
    from private_imap_archive import _archive, ARCHIVE
    client = connector()
    try:
        _archive(client)
        archive_validity = imap.select(client, ARCHIVE, readonly=True)
        archive_entries = transport.scan(client)
        if set(archive_entries) != imap.uidset(client):
            raise RuntimeError("conversation_archive_changed_during_readback")
        by_draft = {}
        for uid, saved in archive_entries.items():
            key = saved["draft_id"]
            if (key not in records or key in by_draft
                    or saved["draft_flag"] or b"\\DELETED" in saved["flags"]):
                raise RuntimeError("conversation_archive_scope_changed")
            by_draft[key] = saved
        for key in replaced:
            older = by_draft.get(key)
            if not older or not _matches(
                    build_message(records[key]["current"]), older["message"]):
                raise RuntimeError("conversation_original_archive_missing")
        return len(replaced)
    finally:
        try:
            client.logout()
        except Exception:
            pass


def run(mode, event, *, connector=connect_imap):
    authorize(event, mode)
    imap.target_guard()
    session = RateLimitedSourceReads(authorized_writer())
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
        archived = _verify_archived_originals(records, state, connector=connector)
        return {"total": len(state), "eligible": total_target,
                "already_new": changed, "archived": archived,
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
    archived = _verify_archived_originals(records, follow, connector=connector)
    if archived < installed:
        raise RuntimeError("conversation_archive_count_mismatch")
    return {"total": len(follow), "eligible": total_target,
            "archived": archived,
            "installed": installed, "already_new": skipped,
            "blocked": EXPECTED_COUNTS["source_hold"] + EXPECTED_COUNTS["held"],
            "sent": 0}


def _delegate(event, mode):
    # Only after authenticating the single owner-issued batch-chain comment.
    clone = dict(event)
    clone["comment"] = dict(event["comment"], body=PREFIX + mode)
    return clone


def run_remaining(event):
    authorize(event, "BATCH_2_TO_5")
    # The previous one-at-a-time pilot + first 100 scope must be independently
    # verified before executing any later batch.
    preliminary = run("AUDIT", _delegate(event, "AUDIT"))
    if preliminary["total"] != 411 or preliminary["already_new"] < 87:
        raise RuntimeError("conversation_first_batch_not_complete")
    completed = []
    for number in (2, 3, 4, 5):
        mode = "BATCH_" + str(number)
        result = run(mode, _delegate(event, mode))
        if result["total"] != 411 or result["sent"] != 0:
            raise RuntimeError("conversation_batch_integrity_error")
        completed.append(number)
    final = run("AUDIT", _delegate(event, "AUDIT"))
    if (final["total"] != 411 or final["already_new"] != 391
            or final["archived"] != 391 or final["sent"] != 0):
        raise RuntimeError("conversation_full_scope_not_verified")
    return {"total": final["total"], "eligible": final["eligible"],
            "already_new": final["already_new"], "archived": final["archived"],
            "blocked": final["blocked"], "batches": len(completed), "sent": 0}


_SAFE_REASONS = frozenset({
    "ambiguous_business_name",
    "approved_headers_invalid",
    "archive_append_failed",
    "archive_cannot_be_drafts",
    "archive_duplicate_draft_id",
    "archive_flags_invalid",
    "archive_folder_creation_failed",
    "archive_folder_list_failed",
    "archive_folder_name_invalid",
    "archive_folder_not_initialized",
    "archive_identity_invalid",
    "archive_independent_readback_failed",
    "archive_old_bytes_not_equal",
    "archive_original_conflict",
    "archive_read_identity_invalid",
    "archive_uidvalidity_invalid",
    "archive_unrelated_message_changed",
    "archive_write_mime_mismatch",
    "archive_write_scope_or_hash_mismatch",
    "batch_draft_outcome_invalid",
    "batch_preflight_unavailable",
    "batch_readback_failed",
    "cannot_resnapshot_during_replacement",
    "closed_business_has_new_draft",
    "closed_business_not_blocked",
    "concurrent_unrelated_drafts_present",
    "configured_drafts_folder_not_verified",
    "conversation_archive_changed_during_readback",
    "conversation_batch_source_invalid",
    "conversation_batch_source_read_failed",
    "conversation_unbatched_source_request",
    "conversation_archive_count_mismatch",
    "conversation_archive_scope_changed",
    "conversation_batch_empty",
    "conversation_batch_final_verification_failed",
    "conversation_batch_integrity_error",
    "conversation_blocked_draft_modified",
    "conversation_blocked_entry_modified",
    "conversation_draft_flags_changed",
    "conversation_duplicate_draft_id",
    "conversation_duplicate_question",
    "conversation_evidence_duplicate",
    "conversation_evidence_missing",
    "conversation_evidence_row_invalid",
    "conversation_excluded_or_closed_has_draft",
    "conversation_expected_draft_missing",
    "conversation_first_batch_not_complete",
    "conversation_full_scope_not_verified",
    "conversation_independent_readback_failed",
    "conversation_mailbox_changed_during_scan",
    "conversation_mailbox_count_changed",
    "conversation_mailbox_message_changed",
    "conversation_mode_invalid",
    "conversation_mode_unauthorized",
    "conversation_official_evidence_identity_mismatch",
    "conversation_official_evidence_stale",
    "conversation_official_source_changed",
    "conversation_original_archive_missing",
    "conversation_owner_authorization_denied",
    "conversation_population_changed",
    "conversation_private_sources_changed",
    "conversation_review_body_invalid",
    "conversation_review_missing",
    "conversation_review_not_ready",
    "conversation_review_sheet_scope_invalid",
    "conversation_sender_changed",
    "conversation_source_identity_mismatch",
    "conversation_sheet_transient_exhausted",
    "conversation_uidplus_required",
    "conversation_uidvalidity_changed",
    "conversation_unrelated_message_in_drafts",
    "conversation_website_not_verified",
    "copy_without_source_evidence",
    "deleted_draft_reappeared",
    "draft_append_failed",
    "draft_append_readback_mismatch",
    "draft_append_uid_scope_mismatch",
    "draft_authorization_denied",
    "draft_authorization_missing",
    "draft_batch_ids_invalid",
    "draft_batch_size_invalid",
    "draft_expected_identity_invalid",
    "draft_expected_identity_missing",
    "draft_flag_changed_before_delete",
    "draft_flag_or_sender_changed",
    "draft_inventory_changed",
    "draft_operation_invalid",
    "draft_queue_auth_invalid",
    "draft_queue_body_invalid",
    "draft_queue_body_word_limit_exceeded",
    "draft_queue_company_invalid",
    "draft_queue_credentials_missing",
    "draft_queue_email_invalid",
    "draft_queue_headers_invalid",
    "draft_queue_id_invalid",
    "draft_queue_id_missing_or_duplicate",
    "draft_queue_read_failed",
    "draft_queue_registry_headers_invalid",
    "draft_queue_registry_identity_missing",
    "draft_queue_registry_invalid_identity",
    "draft_queue_registry_invalid_row",
    "draft_queue_row_shape_invalid",
    "draft_queue_source_url_invalid",
    "draft_queue_subject_invalid",
    "draft_queue_unfilled_placeholder",
    "draft_queue_values_missing",
    "draft_readback_failed",
    "draft_readback_mismatch",
    "draft_readback_missing",
    "draft_readback_missing_message",
    "draft_search_failed",
    "draft_source_or_exclusion_unverified",
    "draft_stage_readback_mismatch",
    "draft_stage_uid_scope_changed",
    "drafts_folder_changed",
    "drafts_folder_missing_or_ambiguous",
    "drafts_folder_select_failed",
    "duplicate_business",
    "duplicate_draft_after_append",
    "duplicate_draft_generation",
    "duplicate_draft_id",
    "duplicate_draft_id_in_mailbox",
    "duplicate_mailbox_draft_id",
    "excluded_draft_created",
    "excluded_entry_in_mailbox",
    "excluded_review_modified",
    "existing_draft_changed",
    "held_draft_changed",
    "held_draft_must_remain",
    "historical_suppression_changed",
    "historical_suppression_unavailable",
    "historical_v2_bad_hash_key_or_domain",
    "historical_v2_duplicate_identity",
    "historical_v2_headers_missing",
    "historical_v2_incomplete",
    "historical_v2_row_shape_invalid",
    "historical_v2_source_overflow",
    "historical_v2_vault_key_invalid",
    "historical_v2_vault_unavailable_or_modified",
    "historically_suppressed_before_draft",
    "historically_suppressed_before_install",
    "history_readback_failed",
    "imap_append_failed",
    "imap_batch_body_failed",
    "imap_batch_flags_changed",
    "imap_batch_message_size_invalid",
    "imap_batch_metadata_failed",
    "imap_batch_metadata_incomplete",
    "imap_batch_readback_incomplete",
    "imap_batch_uid_set_changed",
    "imap_capability_unavailable",
    "imap_configuration_missing",
    "imap_drafts_select_failed",
    "imap_folder_list_failed",
    "imap_inventory_size_unreviewable",
    "imap_login_failed",
    "imap_message_read_failed",
    "imap_message_readback_incomplete",
    "imap_message_shape_invalid",
    "imap_message_size_unreviewable",
    "imap_metadata_failed",
    "imap_metadata_incomplete",
    "imap_uid_list_invalid",
    "imap_uid_search_failed",
    "imap_uid_search_shape",
    "imap_uidvalidity_missing",
    "independent_draft_mismatch",
    "independent_inventory_mismatch",
    "inventory_not_ready",
    "lead_history_blank_row",
    "lead_history_duplicate_identity",
    "lead_history_headers_invalid",
    "lead_history_identity_missing",
    "lead_history_incomplete",
    "lead_history_invalid_row",
    "lead_history_unavailable",
    "mailbox_changed_before_delete",
    "mailbox_changed_before_targeted_cleanup",
    "mailbox_changed_during_inventory",
    "mailbox_changed_during_readback",
    "mailbox_control_capacity",
    "mailbox_control_headers_invalid",
    "mailbox_control_invalid",
    "mailbox_control_readback_failed",
    "mailbox_control_wrong_task",
    "mailbox_inventory_hash_mismatch",
    "mailbox_inventory_row_invalid",
    "mailbox_plan_readback_failed",
    "mailbox_target_not_authorized",
    "mailbox_uid_scope_changed",
    "mismatch",
    "missing_values",
    "old_draft_changed_do_not_delete",
    "old_draft_changed_during_delete",
    "old_draft_delete_flag_failed",
    "old_draft_delete_readback_failed",
    "old_draft_disappeared",
    "old_message_not_confirmed_as_draft",
    "old_or_closed_draft_remains",
    "old_uid_changed_before_delete",
    "old_uid_scope_or_bytes_changed",
    "open_source_hold_bypassed",
    "original_draft_changed",
    "original_draft_missing",
    "original_fifty_not_available",
    "phase_exact_readback_failed",
    "private_batch_headers_invalid",
    "private_batch_row_invalid",
    "private_handoff_auth_invalid",
    "private_handoff_credentials_missing",
    "private_handoff_row_invalid",
    "private_handoff_run_id_invalid",
    "private_handoff_size_invalid",
    "private_handoff_unverified",
    "private_review_identity_changed",
    "private_review_identity_mismatch",
    "private_review_incomplete",
    "private_review_missing",
    "private_review_opt_out_or_signoff_invalid",
    "private_review_score_invalid",
    "private_row_width_invalid",
    "private_rows_changed_during_install",
    "private_sheet_read_failed",
    "private_sheet_shape_invalid",
    "private_sheet_write_failed",
    "private_snapshot_readback_failed",
    "private_snapshot_sha_mismatch",
    "private_snapshot_storage_required",
    "private_source_scope_changed",
    "read_failed",
    "recipient_identity_changed",
    "registry_auth_invalid",
    "registry_credentials_missing",
    "registry_location_invalid",
    "registry_read_failed",
    "registry_unavailable_before_draft",
    "removed_sentence_in_mailbox",
    "replacement_content_not_reviewed",
    "replacement_content_readback_mismatch",
    "replacement_draft_count_mismatch",
    "replacement_draft_missing_or_wrong_flag",
    "replacement_final_count_invalid",
    "replacement_precondition_failed",
    "replacement_requires_exactly_450",
    "review_body_invalid",
    "review_copy_invalid",
    "review_draft_missing",
    "review_population_changed",
    "review_row_invalid",
    "sender_identity_invalid",
    "snapshot_message_read_failed",
    "snapshot_original_changed",
    "source_changed_before_targeted_cleanup",
    "source_changed_during_phase",
    "source_shape_invalid",
    "targeted_delete_flag_failed",
    "targeted_delete_readback_failed",
    "targeted_draft_changed_before_delete",
    "targeted_old_mark_failed",
    "targeted_old_remove_not_verified",
    "targeted_old_uid_expunge_failed",
    "targeted_uid_expunge_failed",
    "targeted_uid_expunge_unavailable",
    "targeted_uid_expunge_unsupported",
    "too_many_batch_rows",
    "uidvalidity_changed",
    "uidvalidity_changed_before_delete",
    "unrecognized_or_manually_edited_draft",
    "unrelated_draft_changed",
    "unrelated_mailbox_message_preserved",
    "unreviewed_entry_cannot_sync",
    "verified_draft_not_ready",
    "write_failed",
})


def _safe_reason(error):
    # Never publish exception detail unless it is one of these constants.
    message = str(error)
    return message if type(error) is RuntimeError and message in _SAFE_REASONS else "private_or_unclassified_error"


def main():
    command = os.getenv("CONVERSATION_MODE", "")
    mode = command[len(PREFIX):] if command.startswith(PREFIX) else ""
    try:
        if mode not in MODES or os.getenv("GITHUB_EVENT_NAME") != "issue_comment":
            raise RuntimeError("conversation_mode_invalid")
        with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
            event = json.load(f)
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            result = run_remaining(event) if mode == "BATCH_2_TO_5" else run(mode, event)
        print("CONVERSATION411=green " +
              " ".join(f"{k}={v}" for k, v in result.items()))
        return 0
    except Exception as error:
        print("CONVERSATION411=blocked reason=" + _safe_reason(error) + " sent=0")
        return 1


if __name__ == "__main__":
    sys.exit(main())
