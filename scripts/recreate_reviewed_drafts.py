"""Re-create deleted reviewed drafts only; never archive, delete, or send."""
from __future__ import annotations

from datetime import datetime, timezone

import conversation_replacement as legacy
from myhost_draft import build_message, save_draft, connect_imap, _matches


def load_reviewed(session, revision):
    baseline = legacy._private_rows(session, require_fresh=False)
    values = legacy.history.source.read(
        session, legacy.history.source.SID,
        "'Conceptkwaliteit 20261018'!A1:M451")
    evidence = legacy.history.source.read(
        session, legacy.history.source.SID, "WebsiteEvidence!A1:N1000")
    if (len(baseline) != 450 or len(values) != 451
            or values[0] != revision.HEADERS or not evidence
            or evidence[0] != list(legacy.websites.COLUMNS)):
        raise RuntimeError("revision_source_shape")
    proof = {}
    for item in evidence[1:]:
        if len(item) != 14 or item[0] in proof:
            raise RuntimeError("revision_source_shape")
        proof[item[0]] = item
    eligible, held = {}, set()
    reviewed = 0
    for number, raw in enumerate(values[1:], 1):
        if len(raw) != 13 or raw[0] != str(number):
            raise RuntimeError("revision_source_shape")
        key = raw[1]
        row = baseline.get(key)
        if (not row or row["number"] != number
                or raw[2] != row["new"]["company"]):
            raise RuntimeError("revision_source_identity")
        if raw[5] == "OVERGESLAGEN":
            if raw[7] or row["category"] == "target":
                raise RuntimeError("revision_source_scope")
            continue
        reviewed += 1
        if (raw[5] not in revision.REVIEW_STATES
                or raw[11] != "NIET VERZENDGEREED - HANDMATIGE REVIEW"
                or raw[4] != row["new"]["subject"]):
            raise RuntimeError("revision_source_scope")
        revision.validate_body(raw[7])
        if row["category"] == "source_hold":
            held.add(key)
            continue
        if row["category"] != "target":
            raise RuntimeError("revision_source_scope")
        detail = proof.get("Review450:" + key)
        if (not detail or not detail[12].startswith("verified_")
                or detail[6].casefold() != row["new"]["email"].casefold()):
            raise RuntimeError("revision_source_identity")
        try:
            legacy._check_evidence_timestamp(
                detail[11], datetime.now(timezone.utc), require_fresh=True)
        except RuntimeError:
            held.add(key)
            continue
        eligible[key] = dict(row, new=dict(row["new"], body=raw[7]))
    if reviewed != 410 or len(eligible) + len(held) != 410:
        raise RuntimeError("revision_source_scope")
    return eligible, held


def classify(eligible, inventory):
    from email.utils import parseaddr

    existing = {}
    for uid, item in inventory.items():
        key = item["draft_id"]
        if key not in eligible or key in existing:
            raise RuntimeError("revision_mailbox_changed")
        actual = item["message"]
        if (not item["draft_flag"] or b"\\DELETED" in item["flags"]
                or parseaddr(actual.get("From", ""))[1].casefold() != legacy.imap.USER
                or actual.is_multipart() or actual.get_content_type() != "text/plain"
                or not _matches(build_message(eligible[key]["new"]), actual)):
            raise RuntimeError("revision_mailbox_changed")
        existing[key] = uid
    return existing


def run(mode, *, revision, connector=connect_imap):
    legacy.imap.target_guard()
    session = legacy.RateLimitedSourceReads(legacy.authorized_writer())
    eligible, held = load_reviewed(session, revision)
    source_hash = legacy._digest(eligible)
    folder, validity, before = revision.read_drafts(connector)
    existing = classify(eligible, before)
    pending = [key for key in eligible if key not in existing]
    chosen = pending
    if mode == "RECREATE_PILOT":
        chosen = [key for key in pending if eligible[key]["number"] == 1]
    elif mode.startswith("RECREATE_BATCH_"):
        group = int(mode.rsplit("_", 1)[1])
        chosen = [key for key in pending
                  if (eligible[key]["number"] - 1) // 100 + 1 == group]
    if mode == "RECREATE_PRECHECK" or not chosen:
        return dict(eligible=len(eligible), held=len(held), existing=len(existing),
                    pending=len(pending), created=0, sent=0, deleted=0)

    again, holds = load_reviewed(session, revision)
    if legacy._digest(again) != source_hash or holds != held:
        raise RuntimeError("revision_source_changed")
    client = connector()
    try:
        if (legacy.find_drafts_folder(client) != folder
                or legacy.imap.select(client, folder, readonly=True) != validity):
            raise RuntimeError("revision_mailbox_changed")
        revision.unchanged(before, legacy.transport.scan(client))
        for key in chosen:
            outcome = save_draft(client, folder, eligible[key]["new"])
            if outcome != "created":
                raise RuntimeError("revision_stage_mismatch")
    finally:
        client.logout()

    final_folder, final_validity, after = revision.read_drafts(connector)
    if final_folder != folder or final_validity != validity:
        raise RuntimeError("revision_final_mismatch")
    revision.unchanged(before, after, added=set(after) - set(before))
    installed = classify(eligible, after)
    if (len(installed) != len(existing) + len(chosen)
            or not set(existing).issubset(installed)
            or not set(chosen).issubset(installed)):
        raise RuntimeError("revision_final_mismatch")
    last, last_holds = load_reviewed(session, revision)
    if legacy._digest(last) != source_hash or last_holds != held:
        raise RuntimeError("revision_source_changed")
    return dict(eligible=len(eligible), held=len(held), existing=len(installed),
                pending=len(eligible) - len(installed),
                created=len(chosen), sent=0, deleted=0)
