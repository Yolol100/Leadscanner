"""Content-only revisions inside the existing owner-authorized draft workflow.

No new recipients, discovery, sending, scheduling or global EXPUNGE. Prior
versions remain byte-identical in a separate private IMAP archive. Website
age is not a gate for changing the text of an already verified draft; live
identity, original MIME, source and historical suppression checks still are.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO

import conversation_replacement as legacy
import private_imap_archive as archives
from myhost_draft import _mailbox_arg, _matches, build_message, connect_imap

TAB = "Conceptkwaliteit 20261018"
HEADERS = [
    "Bronnummer", "Draft-ID", "Bedrijf", "Branche", "Bestaand onderwerp",
    "Redactionele beoordeling", "Waarom herzien", "Verbeterde mail - VOORSTEL",
    "Controle vooraf", "Offici\u00eble bron (historisch)", "Mijn.Host-status",
    "Verzendstatus", "Audittype",
]
REVIEW_STATES = {"HERZIEN VOOR MENSELIJKE CONTROLE",
                 "EXTRA BRANCHEREVIEW - ALGEMEEN AANBOD"}
RECREATE_MODES = {"RECREATE_PRECHECK", "RECREATE_PILOT"} | {
    f"RECREATE_BATCH_{n}" for n in range(1, 6)
}
MODES = {"REVISION_PRECHECK", "REVISION_AUDIT", "REVISION_PILOT", "REVISION_ALL"} | RECREATE_MODES
ERRORS = {
    "revision_command_invalid", "revision_source_shape", "revision_source_identity",
    "revision_source_scope", "revision_body_invalid", "revision_subject_changed",
    "revision_source_changed", "revision_archive_changed", "revision_archive_copy_failed",
    "revision_archive_copy_mismatch", "revision_archive_flags_failed",
    "revision_archive_readback_failed", "revision_mailbox_changed",
    "revision_stage_failed", "revision_stage_mismatch", "revision_delete_failed",
    "revision_final_mismatch", "revision_originals_incomplete",
}


def authorize(mode, event):
    if mode not in MODES | {"AUDIT"}:
        raise RuntimeError("revision_command_invalid")
    if not isinstance(event, dict) or (event.get("comment") or {}).get("body") != legacy.PREFIX + mode:
        raise RuntimeError("revision_command_invalid")
    # Reuse the exact established owner/issue/repository authorization policy.
    checked = dict(event, comment=dict(event["comment"], body=legacy.PREFIX + "AUDIT"))
    legacy.authorize(checked, "AUDIT")


def validate_body(body):
    if not isinstance(body, str) or "\r" in body or "\x00" in body:
        raise RuntimeError("revision_body_invalid")
    parts = body.split("\n\n")
    if len(parts) != 5 or parts[0] not in {"Hoi,", "Goedendag,"}:
        raise RuntimeError("revision_body_invalid")
    # Validate without changing the approved greeting or stored content.
    legacy.review_body("\n\n".join(["Hoi,"] + parts[1:]))
    # The opening must describe a verified company fact and an actual offer,
    # not a compulsory self-introduction or a generic marketing phrase.
    if ("Ik ben Andrew van Webactueel" in body
            or not parts[1].strip()
            or "}}" in body or "[" in body or "]" in body):
        raise RuntimeError("revision_body_invalid")


def load_scope(session):
    # Content-only, same recipient. Full live identity/opt-out/HMAC reads remain;
    # this does not turn old website evidence into current proof for sending.
    base = legacy._private_rows(session, require_fresh=False)
    values = legacy.history.source.read(
        session, legacy.history.source.SID, "'" + TAB + "'!A1:M451")
    if len(values) != 451 or values[0] != HEADERS or len(base) != 450:
        raise RuntimeError("revision_source_shape")
    result = {}
    for number, raw in enumerate(values[1:], 1):
        if len(raw) != 13 or raw[0] != str(number):
            raise RuntimeError("revision_source_shape")
        key = raw[1]
        item = base.get(key)
        if (not item or key in result or item["number"] != number
                or raw[2] != item["new"]["company"]):
            raise RuntimeError("revision_source_identity")
        if item["category"] != "target":
            if raw[7] or raw[5] != "OVERGESLAGEN":
                raise RuntimeError("revision_source_scope")
            result[key] = dict(item)
            continue
        if (raw[5] not in REVIEW_STATES
                or raw[11] != "NIET VERZENDGEREED - HANDMATIGE REVIEW"):
            raise RuntimeError("revision_source_scope")
        if raw[4] != item["new"]["subject"]:
            raise RuntimeError("revision_subject_changed")
        validate_body(raw[7])
        # No address field is accepted from the proposal. Reuse the old To,
        # source URL, subject, company and opaque identity without alteration.
        result[key] = dict(item, current=dict(item["new"]),
                           new=dict(item["new"], body=raw[7]))
    if sum(x["category"] == "target" for x in result.values()) != 410:
        raise RuntimeError("revision_source_scope")
    return base, result


def read_drafts(connector):
    client = connector()
    try:
        folder = legacy.find_drafts_folder(client)
        validity = legacy.imap.select(client, folder, readonly=True)
        return folder, validity, legacy.transport.scan(client)
    finally:
        client.logout()


def unchanged(before, after, *, removed=frozenset(), added=frozenset()):
    if set(after) != (set(before) - set(removed)) | set(added):
        raise RuntimeError("revision_mailbox_changed")
    for uid, item in before.items():
        if uid in removed:
            continue
        # RFC 3501 2.3.2: Recent belongs to a session, not the stored message.
        # Retain every persistent flag/keyword, UID and byte-hash comparison.
        if (after[uid]["sha256"] != item["sha256"]
                or (after[uid]["flags"] - {b"\\RECENT"}) !=
                   (item["flags"] - {b"\\RECENT"})):
            raise RuntimeError("revision_mailbox_changed")


def uidset(values):
    values = sorted(set(values), key=int)
    if not values or any(not legacy.drafts.UID_PATTERN.fullmatch(x) for x in values):
        raise RuntimeError("revision_source_scope")
    return ",".join(values)


def archive_inventory(connector, records, *, required=None):
    client = connector()
    try:
        try:
            archives._archive(client, folder=archives.REVISION_ARCHIVE)
        except RuntimeError as error:
            if str(error) == "archive_folder_not_initialized" and not required:
                return None, {}, {}
            raise
        validity = legacy.imap.select(client, archives.REVISION_ARCHIVE, readonly=True)
        found = legacy.transport.scan(client)
        by_key = check_archive(found, records)
        if required is not None:
            for key, sha in required.items():
                if key not in by_key or (sha is not None and by_key[key]["sha256"] != sha):
                    raise RuntimeError("revision_archive_readback_failed")
        return validity, found, by_key
    finally:
        client.logout()


def check_archive(found, records, *, allow_draft=False):
    by_key = {}
    for uid, saved in found.items():
        key = saved["draft_id"]
        if (key not in records or records[key]["category"] != "target"
                or key in by_key or b"\\DELETED" in saved["flags"]
                or (saved["draft_flag"] and not allow_draft)
                or not _matches(build_message(records[key]["current"]), saved["message"])):
            raise RuntimeError("revision_archive_changed")
        by_key[key] = saved
    return by_key


def archive_batch(client, connector, folder, validity, before, records, pending):
    """Server-side copies, then independent full SHA/MIME readback; no deletion."""
    keeper = connector()
    try:
        archives._archive(keeper, create=True, folder=archives.REVISION_ARCHIVE)
        av = legacy.imap.select(keeper, archives.REVISION_ARCHIVE, readonly=False)
        old_archive = legacy.transport.scan(keeper)
        old_keys = check_archive(old_archive, records, allow_draft=True)
    finally:
        keeper.logout()
    missing, required = [], {}
    for key, original_uid in pending.items():
        required[key] = before[original_uid]["sha256"]
        if key in old_keys:
            if old_keys[key]["sha256"] != required[key]:
                raise RuntimeError("revision_archive_copy_mismatch")
        else:
            missing.append(original_uid)
    if legacy.imap.select(client, folder, readonly=True) != validity:
        raise RuntimeError("uidvalidity_changed")
    unchanged(before, legacy.transport.scan(client))
    if missing and client.uid("COPY", uidset(missing), _mailbox_arg(archives.REVISION_ARCHIVE))[0] != "OK":
        raise RuntimeError("revision_archive_copy_failed")
    keeper = connector()
    try:
        if legacy.imap.select(keeper, archives.REVISION_ARCHIVE, readonly=False) != av:
            raise RuntimeError("revision_archive_changed")
        copied = legacy.transport.scan(keeper)
        added = set(copied) - set(old_archive)
        unchanged(old_archive, copied, added=added)
        by_key = check_archive(copied, records, allow_draft=True)
        if (len(added) != len(missing)
                or set(by_key) != set(old_keys) | set(pending)
                or any(by_key[key]["sha256"] != sha for key, sha in required.items())):
            raise RuntimeError("revision_archive_copy_mismatch")
        # COPY preserves flags. Remove Draft only from proved archive copies.
        draft_uids = [x["uid"] for x in by_key.values() if x["draft_flag"]]
        if draft_uids and keeper.uid("STORE", uidset(draft_uids), "-FLAGS.SILENT", r"(\Draft)")[0] != "OK":
            raise RuntimeError("revision_archive_flags_failed")
    finally:
        keeper.logout()
    read_validity, readback, _ = archive_inventory(connector, records, required=required)
    if read_validity != av or set(readback) != set(copied):
        raise RuntimeError("revision_archive_readback_failed")
    for uid in copied:
        if readback[uid]["sha256"] != copied[uid]["sha256"]:
            raise RuntimeError("revision_archive_readback_failed")


def rollback_staged(client, folder, validity, before, records, pending):
    """Compensate only exact new copies whose exact original is still present."""
    try:
        if legacy.imap.select(client, folder, readonly=False) != validity:
            return
        current = legacy.transport.scan(client)
        restore, remove = [], []
        for key, old_uid in pending.items():
            item = current.get(old_uid)
            if not item or item["sha256"] != before[old_uid]["sha256"]:
                continue  # Never remove the sole remaining version.
            if b"\\DELETED" in item["flags"]:
                restore.append(old_uid)
            matches = [uid for uid, entry in current.items() if uid not in before
                       and entry["draft_id"] == key and entry["draft_flag"]
                       and _matches(build_message(records[key]["new"]), entry["message"])]
            if len(matches) == 1:
                remove.extend(matches)
        if restore:
            if client.uid("STORE", uidset(restore), "-FLAGS.SILENT", r"(\Deleted)")[0] != "OK":
                return
        if remove and client.uid("STORE", uidset(remove), "+FLAGS.SILENT", r"(\Deleted)")[0] == "OK":
            client.uid("EXPUNGE", uidset(remove))
    except Exception:
        pass  # Preserve uncertain messages and fail; never use CLOSE/EXPUNGE.


def report(base, records, state, original_archives, revision_archives, mode):
    revised = sum(v[1] == "new" for k, v in state.items() if records[k]["category"] == "target")
    if mode == "AUDIT":
        return {"total": len(state), "eligible": 410, "already_new": 410,
                "archived": original_archives, "revised": revised,
                "revision_archived": revision_archives, "blocked": 1, "sent": 0}
    return {"total": len(state), "eligible": 410, "revised": revised,
            "revision_archived": revision_archives, "original_archived": original_archives,
            "pending": 410 - revised, "blocked": 1, "sent": 0}


def run(mode, event, *, connector=connect_imap):
    authorize(mode, event)
    if mode in RECREATE_MODES:
        import recreate_reviewed_drafts
        return recreate_reviewed_drafts.run(
            mode, revision=sys.modules[__name__], connector=connector)
    legacy.imap.target_guard()
    session = legacy.RateLimitedSourceReads(legacy.authorized_writer())
    base, records = load_scope(session)
    source_hash = legacy._digest(records)
    folder, validity, before = read_drafts(connector)
    state = legacy._classify(records, before)
    # Both conversation and revised text already have a first-pass original.
    first_state = {k: (u, "new" if records[k]["category"] == "target" else version, sha)
                   for k, (u, version, sha) in state.items()}
    original_archives = legacy._verify_archived_originals(base, first_state, connector=connector)
    if original_archives != 410:
        raise RuntimeError("revision_originals_incomplete")
    required = {k: None for k, (_, version, _) in state.items()
                if version == "new" and records[k]["category"] == "target"}
    _, _, prior_copies = archive_inventory(connector, records, required=required)
    if mode in {"AUDIT", "REVISION_AUDIT", "REVISION_PRECHECK"}:
        return report(base, records, state, original_archives, len(prior_copies), mode)
    pending = {k: u for k, (u, version, _) in state.items()
               if records[k]["category"] == "target" and version == "old"
               and (mode != "REVISION_PILOT" or records[k]["number"] == 1)}
    if not pending:
        return report(base, records, state, original_archives, len(prior_copies), mode)
    client = connector()
    try:
        if not legacy.imap.uidplus(client):
            raise RuntimeError("targeted_uid_expunge_unsupported")
        archive_batch(client, connector, folder, validity, before, records, pending)
        if legacy.imap.select(client, folder, readonly=False) != validity:
            raise RuntimeError("uidvalidity_changed")
        unchanged(before, legacy.transport.scan(client))
        try:
            for key in pending:
                raw = build_message(records[key]["new"]).as_bytes()
                if client.append(_mailbox_arg(folder), r"(\Draft)", None, raw)[0] != "OK":
                    raise RuntimeError("revision_stage_failed")
            staged = legacy.transport.scan(client)
            added = set(staged) - set(before)
            unchanged(before, staged, added=added)
            seen = set()
            for uid in added:
                entry = staged[uid]
                key = entry["draft_id"]
                if (key not in pending or key in seen or not entry["draft_flag"]
                        or b"\\DELETED" in entry["flags"]
                        or not _matches(build_message(records[key]["new"]), entry["message"])):
                    raise RuntimeError("revision_stage_mismatch")
                seen.add(key)
            if seen != set(pending):
                raise RuntimeError("revision_stage_mismatch")
            # One guarded transaction: fresh full source/registry read immediately
            # before its targeted delete, not 410 redundant website rescans.
            _, latest = load_scope(session)
            if legacy._digest(latest) != source_hash:
                raise RuntimeError("revision_source_changed")
            archive_inventory(connector, records,
                              required={k: before[u]["sha256"] for k, u in pending.items()})
            if legacy.imap.select(client, folder, readonly=False) != validity:
                raise RuntimeError("uidvalidity_changed_before_delete")
            unchanged(staged, legacy.transport.scan(client))
            exact = uidset(pending.values())
            if client.uid("STORE", exact, "+FLAGS.SILENT", r"(\Deleted)")[0] != "OK":
                raise RuntimeError("revision_delete_failed")
            if client.uid("EXPUNGE", exact)[0] != "OK":
                raise RuntimeError("revision_delete_failed")
            final = legacy.transport.scan(client)
            unchanged(staged, final, removed=set(pending.values()))
        except Exception:
            rollback_staged(client, folder, validity, before, records, pending)
            raise
    finally:
        client.logout()
    end_folder, end_validity, after = read_drafts(connector)
    if end_folder != folder or end_validity != validity:
        raise RuntimeError("revision_final_mismatch")
    unchanged(final, after)
    end_state = legacy._classify(records, after)
    if any(end_state[k][1] != "new" for k in pending):
        raise RuntimeError("revision_final_mismatch")
    _, _, copies = archive_inventory(connector, records,
                                    required={k: None for k, (_, v, _) in end_state.items()
                                              if records[k]["category"] == "target" and v == "new"})
    return report(base, records, end_state, original_archives, len(copies), mode)


def main():
    command = os.getenv("CONVERSATION_MODE", "")
    mode = command[len(legacy.PREFIX):] if command.startswith(legacy.PREFIX) else ""
    if mode not in MODES | {"AUDIT"}:
        return legacy.main()
    try:
        if os.getenv("GITHUB_EVENT_NAME") != "issue_comment":
            raise RuntimeError("revision_command_invalid")
        with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as handle:
            event = json.load(handle)
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            outcome = run(mode, event)
        print("DRAFT_REVISION=green " + " ".join(f"{key}={value}" for key, value in outcome.items()))
        return 0
    except Exception as error:
        reason = str(error) if type(error) is RuntimeError and str(error) in ERRORS else legacy._safe_reason(error)
        print("DRAFT_REVISION=blocked reason=" + reason + " sent=0")
        return 1


if __name__ == "__main__":
    sys.exit(main())
