"""Owner-only, draft-only V2 copy migration for the existing 450 private records.

An immutable old MIME is copied and independently verified in a separate
private IMAP archive BEFORE a new draft is staged. Only exact old UIDs may be
expunged, after exact new readback. No SMTP, campaigns, public prospect data,
unscoped EXPUNGE/CLOSE or scheduled activation.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from email.utils import parseaddr
from io import StringIO

import conversation_replacement as legacy
import draft_revision as rev
import private_imap_archive as archives
from myhost_draft import _matches, build_message, _mailbox_arg, connect_imap

PREFIX = "LEADS_V2_DRAFTS:"
MODES = frozenset({"PRECHECK", "AUDIT", "PILOT", "RECREATE_REMAINING"} |
                  {f"BATCH_{i}" for i in range(1, 6)} |
                  {f"RECREATE_BATCH_{i}" for i in range(1, 6)})
V2_HEADERS = [
    "Nr", "Oorspronkelijk Draft-ID", "Bedrijf", "Ontvanger (ongewijzigd)",
    "Bron-URL", "Onderwerp verbeterd", "Nieuwe mail - REVIEW, NIET VERZENDEN",
    "Redactiecheck", "Bronstatus 19 oktober", "Detailbewijs",
    "Historische beoordeling", "Juridisch", "Mijn.Host",
    "Eindstatus", "Nog te doen",
]
ALLOWED_QA = {"VOOR_MENSELIJKE_EINDCONTROLE", "VOORSTEL_HANDMATIGE_EINDCHECK"}
OPT = "Liever geen e-mails meer? Antwoord met 'nee', dan laat ik het hierbij."


def authorize(event, mode):
    if mode not in MODES or not isinstance(event, dict):
        raise RuntimeError("v2_unauthorized")
    if (event.get("comment") or {}).get("body") != PREFIX + mode:
        raise RuntimeError("v2_unauthorized")
    checked = dict(event, comment=dict(event["comment"],
                                     body=legacy.PREFIX + "AUDIT"))
    legacy.authorize(checked, "AUDIT")


def valid_body(body):
    if (not isinstance(body, str) or len(body.split()) > 110
            or len(body.split()) < 25
            or not body.startswith(("Hoi,\n\n", "Goedendag,\n\n"))
            or body.count("?") != 2
            or body.count(OPT) != 1
            or not body.endswith("\n\n" + OPT + "\n\nGroet,\nAndrew")
            or "Was gewoon benieuwd." in body
            or "{{" in body or "}}" in body
            or "[" in body or "]" in body
            or "\r" in body or "\x00" in body):
        raise RuntimeError("v2_text_unverified")


def source_scope(session):
    """Unchanged full HMAC/suppression and official-source validation, plus V2."""
    baseline = legacy._private_rows(session, require_fresh=False)
    sid = legacy.history.source.SID
    qa = legacy.history.source.read(session, sid, "QA450Actueel!A1:P451")
    prior = legacy.history.source.read(
        session, sid, "'Conceptkwaliteit 20261018'!A1:M451")
    evidence = legacy.history.source.read(session, sid, "WebsiteEvidence!A1:N1000")
    tabs = []
    for batch in range(1, 6):
        length = 50 if batch == 5 else 100
        tabs.extend(legacy.history.source.read(
            session, sid,
            f"'Korte mails V2 B{batch} REVIEW 20261019'!A1:O{length + 1}")[1:])
    if (len(baseline) != 450 or len(qa) != 451 or len(prior) != 451
            or len(tabs) != 450 or qa[0][0:4] != [
                "Nr", "Draft-ID", "Bedrijf", "E-mailadres"]
            or prior[0] != rev.HEADERS
            or not evidence or evidence[0] != list(legacy.websites.COLUMNS)):
        raise RuntimeError("v2_source_shape")
    proof = {r[0]: r for r in evidence[1:] if len(r) == 14}
    if len(proof) != len(evidence) - 1:
        raise RuntimeError("v2_evidence_duplicate")
    result = {}
    count = 0
    for number, (raw, old, proposal) in enumerate(
            zip(qa[1:], prior[1:], tabs), 1):
        if len(raw) != 16 or len(old) != 13 or len(proposal) != 15:
            raise RuntimeError("v2_source_shape")
        key, company, email, src = raw[1], raw[2], raw[3], raw[8]
        original = baseline.get(key)
        base = proof.get("Review450:" + key)
        if (not original or original["number"] != number
                or raw[0] != str(number) or old[0] != str(number)
                or proposal[0] != str(number)
                or key != old[1] or key != proposal[1]
                or company != old[2] or company != proposal[2]
                or email.casefold() != proposal[3].casefold()
                or email.casefold() != original["new"]["email"].casefold()
                or original["new"]["company"] != company
                or not base or base[6].casefold() != email.casefold()
                or proposal[4] != original["new"]["source_url"]
                or proposal[11] != "NIET VERZENDGEREED - menselijke controle nodig"
                or proposal[12] != "ONGEWIJZIGD" or key in result):
            raise RuntimeError("v2_source_identity")
        was_skipped = old[5] == "OVERGESLAGEN"
        row = dict(original, number=number)
        if was_skipped:
            if (old[7] or proposal[5] or proposal[6]
                    or proposal[13] != "HOLD - NIET VERVANGEN"
                    or original["category"] == "target"):
                raise RuntimeError("v2_hold_release_denied")
            row["active"] = False
            row["category"] = "held"
            result[key] = row
            continue
        count += 1
        if raw[5] != proposal[5] or raw[6] != proposal[6]:
            raise RuntimeError("v2_copy_changed")
        if (old[5] not in rev.REVIEW_STATES
                or old[11] != "NIET VERZENDGEREED - HANDMATIGE REVIEW"
                or old[4] != original["new"]["subject"]
                or raw[13] not in ALLOWED_QA
                or not proposal[13].startswith(("REVIEW - ", "HOLD - "))
                or not proposal[7].startswith("TEKSTCHECK_OK ")):
            raise RuntimeError("v2_source_unapproved")
        try:
            editorial_score = float(raw[10])
        except (ValueError, TypeError):
            raise RuntimeError("v2_score_invalid") from None
        if not 0 <= editorial_score <= 10:
            raise RuntimeError("v2_score_invalid")
        rev.validate_body(old[7])
        valid_body(proposal[6])
        if (original["category"] not in {"target", "source_hold"}
                or not proposal[5] or not raw[5]):
            raise RuntimeError("v2_source_scope")
        current = {
            "draft_id": key, "company": company, "email": email,
            "source_url": original["new"]["source_url"],
            "subject": old[4], "body": old[7],
        }
        newer = dict(current, subject=proposal[5], body=proposal[6])
        if not 0 < len(newer["subject"]) <= 120:
            raise RuntimeError("v2_subject_invalid")
        fresh = False
        if (base[12] in {"verified_activity_only", "verified_with_detail"}
                and base[6].casefold() == email.casefold()):
            try:
                legacy._check_evidence_timestamp(
                    base[11], datetime.now(timezone.utc), require_fresh=True)
                fresh = True
            except RuntimeError:
                pass
        row.update(
            category="target" if original["category"] == "target" else "source_hold",
            current=current, new=newer,
            quality_ready=editorial_score >= 9.0,
            active=bool(fresh and editorial_score >= 9.0
                        and original["category"] == "target"))
        result[key] = row
    if count != 410 or len(result) != 450:
        raise RuntimeError("v2_source_scope")
    return result


def digest(records):
    return hashlib.sha256(json.dumps([
        (key, row["number"], row["category"], row["active"],
         row["current"]["email"], row["current"]["subject"],
         row["current"]["body"], row["new"]["subject"], row["new"]["body"])
        for key, row in records.items()
    ], ensure_ascii=True).encode()).hexdigest()


def classify(records, inventory):
    """Allow only one known draft per ID and only exact old/new text generations."""
    found = {}
    for uid, item in inventory.items():
        key = item["draft_id"]
        row = records.get(key)
        if (not row or key in found
                or row["category"] not in {"target", "source_hold"}
                or not item["draft_flag"] or b"\\DELETED" in item["flags"]
                or parseaddr(item["message"].get("From", ""))[1].casefold()
                    != legacy.imap.USER):
            raise RuntimeError("v2_mailbox_identity_changed")
        if _matches(build_message(row["new"]), item["message"]):
            generation = "new"
        elif _matches(build_message(row["current"]), item["message"]):
            generation = "old"
        else:
            raise RuntimeError("v2_mailbox_text_changed")
        if row["category"] == "source_hold" and generation != "old":
            raise RuntimeError("v2_source_hold_modified")
        found[key] = (uid, generation, item["sha256"])
    if len(found) > 410:
        raise RuntimeError("v2_mailbox_scope_changed")
    return found


def summary(records, state, archived, recovery_proofs=0):
    eligible = sum(x["category"] == "target" for x in records.values())
    active = sum(x["category"] == "target" and x["active"] for x in records.values())
    new = sum(g == "new" for _, g, _ in state.values())
    quality_review = sum(row["category"] == "target" and
                         not row.get("quality_ready", True)
                         for row in records.values())
    old = sum(g == "old" for _, g, _ in state.values())
    pending = sum(x["category"] == "target" and x["active"]
                  and (key not in state or state[key][1] == "old")
                  for key, x in records.items())
    present_targets = sum(key in state for key, row in records.items()
                          if row["category"] == "target")
    return dict(total=len(state), eligible=eligible, active=active, new=new,
                old=old, missing=eligible-present_targets, pending=pending,
                archived=archived, recovery_proofs=recovery_proofs,
                blocked=450-active,
                quality_review=quality_review, sent=0, deleted=0)


def selected(records, mode):
    if mode == "RECREATE_REMAINING":
        return {key for key, row in records.items()
                if row["category"] == "target" and row["active"]}
    group = None
    if mode == "PILOT":
        return {key for key, row in records.items() if row["number"] == 1}
    if "_BATCH_" in mode:
        group = int(mode.rsplit("_", 1)[1])
    elif mode.startswith("BATCH_"):
        group = int(mode.rsplit("_", 1)[1])
    if group is None:
        return set()
    return {key for key, row in records.items()
            if (row["number"]-1)//100+1 == group}


def recovery_rows(records):
    """Only active/held target identities may have a private new-MIME marker."""
    return {key: dict(row, category="target", current=dict(row["new"]))
            for key, row in records.items() if row["category"] == "target"}


def run(mode, event, *, connector=connect_imap, loader=source_scope):
    authorize(event, mode)
    legacy.imap.target_guard()
    session = legacy.RateLimitedSourceReads(legacy.authorized_writer())
    records = loader(session)
    source_hash = digest(records)
    folder, validity, before = rev.read_drafts(connector)
    state = classify(records, before)
    _, _, stored = rev.archive_inventory(
        connector, records, archive_folder=archives.V2_ARCHIVE)
    _, _, created_proofs = rev.archive_inventory(
        connector, recovery_rows(records),
        archive_folder=archives.V2_CREATED)
    if set(stored) & set(created_proofs):
        raise RuntimeError("v2_archive_generation_conflict")
    if any(key in state and state[key][1] != "new" for key in created_proofs):
        raise RuntimeError("v2_recovery_marker_conflict")
    required_prior = {key: None for key, (_, generation, _) in state.items()
                      if generation == "new"}
    for key in required_prior:
        if key not in stored and key not in created_proofs:
            raise RuntimeError("v2_original_backup_missing")
        if (key in created_proofs
                and state[key][2] != created_proofs[key]["sha256"]):
            raise RuntimeError("v2_recovery_proof_mismatch")
    baseline = summary(records, state, len(stored), len(created_proofs))
    if mode in {"AUDIT", "PRECHECK"}:
        return baseline
    chosen = selected(records, mode)
    if not chosen:
        raise RuntimeError("v2_batch_empty")
    pending = {key: uid for key, (uid, generation, _) in state.items()
               if key in chosen and generation == "old"
               and records[key]["active"]}
    if mode.startswith("RECREATE_BATCH_") or mode == "RECREATE_REMAINING":
        if pending:
            raise RuntimeError("v2_recreate_before_update")
        missing = sorted((key for key in chosen
                          if records[key]["category"] == "target"
                          and records[key]["active"] and key not in state),
                         key=lambda key: records[key]["number"])
        if not missing:
            return baseline
        again = loader(session)
        if digest(again) != source_hash:
            raise RuntimeError("v2_source_changed")
        marker = archives.PrivateIMAPArchive(
            connector=connector, folder=archives.V2_CREATED)
        prepared = {key: marker.prepare_missing_draft(
            key, validity, records[key]["new"]) for key in missing}
        # Source/opt-outs must still match AFTER the durable private archive.
        again = loader(session)
        if digest(again) != source_hash:
            raise RuntimeError("v2_source_changed")
        client = connector()
        try:
            if (legacy.find_drafts_folder(client) != folder
                    or legacy.imap.select(client, folder, readonly=True) != validity):
                raise RuntimeError("v2_mailbox_changed")
            rev.unchanged(before, legacy.transport.scan(client))
            for key in missing:
                if client.append(_mailbox_arg(folder), r"(\Draft)", None,
                                 prepared[key])[0] != "OK":
                    raise RuntimeError("v2_create_failed")
        finally:
            client.logout()
        end_folder, end_validity, after = rev.read_drafts(connector)
        if end_folder != folder or end_validity != validity:
            raise RuntimeError("v2_mailbox_changed")
        added = set(after) - set(before)
        rev.unchanged(before, after, added=added)
        if len(added) != len(missing):
            raise RuntimeError("v2_create_readback_failed")
        exact = set()
        for uid in added:
            item = after[uid]
            key = item["draft_id"]
            if (key not in prepared or key in exact or not item["draft_flag"]
                    or item["sha256"] != hashlib.sha256(prepared[key]).hexdigest()
                    or not _matches(build_message(records[key]["new"]),
                                    item["message"])):
                raise RuntimeError("v2_create_readback_failed")
            exact.add(key)
        if exact != set(missing):
            raise RuntimeError("v2_create_readback_failed")
        final = classify(records, after)
        if any(key not in final or final[key][1] != "new" for key in missing):
            raise RuntimeError("v2_final_readback_failed")
        again = loader(session)
        if digest(again) != source_hash:
            raise RuntimeError("v2_source_changed")
        _, _, confirmed = rev.archive_inventory(
            connector, recovery_rows(records),
            required={key: hashlib.sha256(raw).hexdigest()
                      for key, raw in prepared.items()},
            archive_folder=archives.V2_CREATED)
        return dict(summary(records, final, len(stored), len(confirmed)),
                    created=len(missing), installed=0)
    if not pending:
        return baseline
    client = connector()
    try:
        if not legacy.imap.uidplus(client):
            raise RuntimeError("v2_uidplus_required")
        rev.archive_batch(client, connector, folder, validity, before,
                          records, pending, archive_folder=archives.V2_ARCHIVE)
        if legacy.imap.select(client, folder, readonly=False) != validity:
            raise RuntimeError("v2_mailbox_changed")
        rev.unchanged(before, legacy.transport.scan(client))
        try:
            for key in pending:
                if client.append(_mailbox_arg(folder), r"(\Draft)", None,
                                 build_message(records[key]["new"]).as_bytes())[0] != "OK":
                    raise RuntimeError("v2_stage_failed")
            staged = legacy.transport.scan(client)
            added = set(staged) - set(before)
            rev.unchanged(before, staged, added=added)
            matches = set()
            for uid in added:
                item = staged[uid]
                key = item["draft_id"]
                if (key not in pending or key in matches
                        or not item["draft_flag"] or b"\\DELETED" in item["flags"]
                        or not _matches(build_message(records[key]["new"]),
                                        item["message"])):
                    raise RuntimeError("v2_stage_mismatch")
                matches.add(key)
            if matches != set(pending):
                raise RuntimeError("v2_stage_mismatch")
            again = loader(session)
            if digest(again) != source_hash:
                raise RuntimeError("v2_source_changed")
            rev.archive_inventory(
                connector, records,
                required={key: before[uid]["sha256"] for key, uid in pending.items()},
                archive_folder=archives.V2_ARCHIVE)
            if legacy.imap.select(client, folder, readonly=False) != validity:
                raise RuntimeError("v2_uidvalidity_changed")
            rev.unchanged(staged, legacy.transport.scan(client))
            exact = rev.uidset(pending.values())
            if client.uid("STORE", exact, "+FLAGS.SILENT", r"(\Deleted)")[0] != "OK":
                raise RuntimeError("v2_delete_failed")
            if client.uid("EXPUNGE", exact)[0] != "OK":
                raise RuntimeError("v2_delete_failed")
            final = legacy.transport.scan(client)
            rev.unchanged(staged, final, removed=set(pending.values()))
        except Exception:
            rev.rollback_staged(client, folder, validity, before, records, pending)
            raise
    finally:
        client.logout()
    end_folder, end_validity, after = rev.read_drafts(connector)
    if end_folder != folder or end_validity != validity:
        raise RuntimeError("v2_final_readback_failed")
    rev.unchanged(final, after)
    end_state = classify(records, after)
    if any(end_state[key][1] != "new" for key in pending):
        raise RuntimeError("v2_final_readback_failed")
    _, _, verified = rev.archive_inventory(
        connector, records, required={key: None for key in pending},
        archive_folder=archives.V2_ARCHIVE)
    return dict(summary(records, end_state, len(verified), len(created_proofs)),
                installed=len(pending), created=0)


# Only stable internal codes may enter public CI logs. Never log an exception
# message, traceback, mailbox UID, email, company or MIME data by default.
_SAFE_REASON_CODES = frozenset({
    "archive_folder_name_invalid", "archive_folder_creation_failed",
    "archive_folder_not_initialized", "archive_folder_list_failed",
    "archive_cannot_be_drafts", "archive_flags_invalid",
    "archive_scope_changed", "archive_identity_invalid",
    "archive_uidvalidity_invalid", "archive_duplicate_draft_id",
    "archive_read_identity_invalid", "archive_readback_failed",
    "archive_independent_readback_failed", "archive_old_bytes_not_equal",
    "archive_original_conflict", "archive_write_mime_mismatch",
    "archive_append_failed", "archive_write_scope_or_hash_mismatch",
    "archive_recovery_identity_invalid", "archive_recovery_content_changed",
    "archive_recovery_readback_invalid", "v2_source_changed",
    "v2_mailbox_changed", "v2_source_shape", "v2_source_identity",
    "v2_original_backup_missing", "v2_recovery_proof_mismatch",
    "v2_archive_generation_conflict", "v2_recovery_marker_conflict",
    "v2_create_failed", "v2_create_readback_failed",
    "v2_final_readback_failed", "v2_uidplus_required",
    "v2_mailbox_identity_changed", "v2_mailbox_text_changed",
    "v2_source_unapproved", "v2_recreate_before_update",
    "revision_archive_readback_failed", "revision_archive_changed",
    "conversation_official_evidence_stale", "conversation_source_identity_mismatch",
})


def safe_error_reason(error):
    reason = str(error) if type(error) is RuntimeError else ""
    return (reason if reason in _SAFE_REASON_CODES
            else "private_source_or_imap_unverified")


def main():
    value = os.environ.get("CONVERSATION_MODE", "")
    mode = value[len(PREFIX):] if value.startswith(PREFIX) else ""
    try:
        if mode not in MODES or os.environ.get("GITHUB_EVENT_NAME") != "issue_comment":
            raise RuntimeError("v2_unauthorized")
        with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as handle:
            event = json.load(handle)
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            outcome = run(mode, event)
        print("DRAFT_V2=green mode=" + mode + " " +
              " ".join(f"{k}={v}" for k, v in outcome.items()))
        return 0
    except Exception as error:
        # Known static machine reason only: never print raw private exceptions.
        print("DRAFT_V2=blocked reason=" + safe_error_reason(error) + " sent=0")
        return 1


if __name__ == "__main__":
    sys.exit(main())
