"""Owner-scoped, offline-testable draft operations; no automatic sending.

Reuses the existing Mijn.Host and exact UID/UIDVALIDITY transport. This is a
library, NOT a second scanner or a live issue handler. Production activation
requires a private, durable snapshot adapter and verified source guard.
"""
from __future__ import annotations

import hashlib
import re
from email.utils import parseaddr

import replace450 as imap
import replace450_fast as transport
from draft_queue_readonly import _validate_row
from myhost_draft import (
    _mailbox_arg, _matches, build_message, connect_imap, find_drafts_folder,
)

OPERATIONS = frozenset({"CREATE_DRAFT", "UPDATE_DRAFT", "DELETE_DRAFT"})
ID_PATTERN = re.compile(r"draft-[0-9a-f]{32}\Z")
SHA_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
UID_PATTERN = re.compile(r"[1-9][0-9]*\Z")
OWNER = "Yolol100"
ISSUE = 1659
OPT_OUT = "Liever geen e-mails meer? Antwoord met 'nee', dan laat ik het hierbij."


def require_owner_approval(event, operation, draft_id):
    """Only the exact trusted GitHub issue event can authorize one ID/action."""
    if operation not in OPERATIONS or not ID_PATTERN.fullmatch(str(draft_id)):
        raise RuntimeError("draft_operation_invalid")
    if not isinstance(event, dict):
        raise RuntimeError("draft_authorization_missing")
    issue, comment, repo = (event.get("issue") or {},
                            event.get("comment") or {},
                            event.get("repository") or {})
    expected = "LEADS_MANAGE_V1:" + operation + ":" + draft_id
    if (event.get("action") != "created"
            or repo.get("full_name") != "Yolol100/Leadscanner"
            or issue.get("number") != ISSUE or issue.get("pull_request")
            or (comment.get("user") or {}).get("login") != OWNER
            or comment.get("author_association") != "OWNER"
            or comment.get("body") != expected):
        raise RuntimeError("draft_authorization_denied")


def _guard(check_source):
    # Production adapter must verify official source, current historical
    # suppression, opt-outs, scope and explicit reviewed private proposal.
    if not callable(check_source) or check_source() is not True:
        raise RuntimeError("draft_source_or_exclusion_unverified")


def _scope(client, folder):
    validity = imap.select(client, folder, readonly=True)
    inventory = transport.scan(client)
    if imap.uidset(client) != set(inventory):
        raise RuntimeError("draft_inventory_changed")
    return validity, inventory


def _matches_for(inventory, draft_id):
    rows = [(uid, row) for uid, row in inventory.items()
            if row["draft_id"] == draft_id]
    if len(rows) > 1:
        raise RuntimeError("duplicate_draft_id_in_mailbox")
    if rows:
        uid, item = rows[0]
        if (not item["draft_flag"] or b"\\DELETED" in item["flags"]
                or parseaddr(item["message"].get("From", ""))[1].casefold()
                    != imap.USER):
            raise RuntimeError("draft_flag_or_sender_changed")
    return rows


def _assert_untouched(before, after, except_uids=frozenset()):
    for uid, record in before.items():
        if uid in except_uids:
            continue
        actual = after.get(uid)
        if (not actual or actual["sha256"] != record["sha256"]
                or actual["flags"] != record["flags"]):
            raise RuntimeError("unrelated_draft_changed")


def _raw_snapshot(client, uid, sha):
    size, _ = imap.metadata(client, uid)
    status, payload = client.uid("FETCH", uid, "(UID FLAGS BODY.PEEK[])")
    matches = [x for x in payload or [] if isinstance(x, tuple)
               and len(x) == 2 and isinstance(x[1], bytes)]
    if status != "OK" or len(matches) != 1:
        raise RuntimeError("snapshot_message_read_failed")
    meta, raw = matches[0]
    match = re.search(rb"\bUID (\d+)\b", meta)
    if (not match or match.group(1).decode("ascii") != uid or len(raw) != size
            or hashlib.sha256(raw).hexdigest() != sha):
        raise RuntimeError("snapshot_original_changed")
    return raw


def _snapshot(snapshots, *, draft_id, validity, uid, sha, raw):
    # The adapter must SAVE and independently READ the original MIME bytes.
    # No public GitHub log/artifact may contain a snapshot or recipient data.
    if snapshots is None or not callable(getattr(snapshots, "save", None)) \
            or not callable(getattr(snapshots, "read", None)):
        raise RuntimeError("private_snapshot_storage_required")
    key = snapshots.save(draft_id, validity, uid, raw)
    if not key or snapshots.read(key) != raw:
        raise RuntimeError("private_snapshot_readback_failed")
    if hashlib.sha256(raw).hexdigest() != sha:
        raise RuntimeError("private_snapshot_sha_mismatch")
    return key


def _targeted_remove(client, folder, validity, uid, expected_sha):
    """Only expunge an exact verified UID; clear its Deleted flag if expunge fails."""
    if not imap.uidplus(client):
        raise RuntimeError("targeted_uid_expunge_unsupported")
    if imap.select(client, folder, readonly=False) != validity:
        raise RuntimeError("uidvalidity_changed")
    current = imap.fetch_message(client, uid)
    if current["sha256"] != expected_sha or not current["draft_flag"]:
        raise RuntimeError("targeted_draft_changed_before_delete")
    try:
        if client.uid("STORE", uid, "+FLAGS.SILENT", "(\\Deleted)")[0] != "OK":
            raise RuntimeError("targeted_delete_flag_failed")
        if client.uid("EXPUNGE", uid)[0] != "OK":
            raise RuntimeError("targeted_uid_expunge_failed")
        if uid in imap.uidset(client):
            raise RuntimeError("targeted_delete_readback_failed")
    except Exception:
        # If the exact original is still present, undo a temporary Deleted flag.
        # Never use CLOSE or unscoped EXPUNGE as recovery.
        try:
            if uid in imap.uidset(client):
                unchanged = imap.fetch_message(client, uid)
                if (unchanged["sha256"] == expected_sha
                        and b"\\DELETED" in unchanged["flags"]):
                    client.uid("STORE", uid, "-FLAGS.SILENT", "(\\Deleted)")
        except Exception:
            pass
        raise


def _expect_target(record, *, uid, sha):
    if record["uid"] != uid or record["sha256"] != sha:
        raise RuntimeError("original_draft_changed")


def _independent_readback(connector, folder, validity, expected, target, operation,
                          baseline, *, expected_total):
    verification = connector()
    try:
        if find_drafts_folder(verification) != folder:
            raise RuntimeError("drafts_folder_changed")
        fresh_validity, final = _scope(verification, folder)
        if fresh_validity != validity or len(final) != expected_total:
            raise RuntimeError("independent_inventory_mismatch")
        _assert_untouched(baseline, final,
                          {target} if operation != "CREATE_DRAFT" else frozenset())
        matches = _matches_for(final, expected["draft_id"])
        if operation == "DELETE_DRAFT":
            if matches:
                raise RuntimeError("deleted_draft_reappeared")
        else:
            if len(matches) != 1 or not _matches(
                    build_message(expected), matches[0][1]["message"]):
                raise RuntimeError("independent_draft_mismatch")
        return {"status": "verified", "operation": operation,
                "drafts": len(final), "sent": 0}
    finally:
        try:
            verification.logout()
        except Exception:
            pass


def execute(event, operation, draft_id, *, row=None, expected=None,
            check_source=None, snapshots=None, connector=connect_imap):
    """Execute one owner-approved operation; no external controller/scheduler.

    UPDATE/DELETE demand expected {folder, uidvalidity, uid, sha256}; raw old
    MIME must be privately saved+read back before any destructive action.
    Retry of an already-created/updated row is safe; deletion of an absent
    message reports no-op only, never claims a deletion.
    """
    require_owner_approval(event, operation, draft_id)
    prepared = None
    if operation != "DELETE_DRAFT":
        if not isinstance(row, dict):
            raise RuntimeError("private_review_missing")
        prepared = _validate_row(row)
        if prepared["draft_id"] != draft_id:
            raise RuntimeError("private_review_identity_mismatch")
        if (OPT_OUT not in prepared["body"]
                or not prepared["body"].rstrip().endswith("Groet,\nAndrew")):
            raise RuntimeError("private_review_opt_out_or_signoff_invalid")
    if operation != "CREATE_DRAFT":
        if not isinstance(expected, dict) or not all(
                isinstance(expected.get(key), str) for key in
                ("folder", "uidvalidity", "uid", "sha256")):
            raise RuntimeError("draft_expected_identity_missing")
        if (not UID_PATTERN.fullmatch(expected["uidvalidity"])
                or not UID_PATTERN.fullmatch(expected["uid"])
                or not SHA_PATTERN.fullmatch(expected["sha256"])
                or not expected["folder"]):
            raise RuntimeError("draft_expected_identity_invalid")
    _guard(check_source)
    imap.target_guard()
    client = connector()
    try:
        folder = find_drafts_folder(client)
        if expected is not None and expected.get("folder") != folder:
            raise RuntimeError("drafts_folder_changed")
        validity, before = _scope(client, folder)
        matches = _matches_for(before, draft_id)
        if operation == "CREATE_DRAFT":
            if matches:
                if not _matches(build_message(prepared), matches[0][1]["message"]):
                    raise RuntimeError("existing_draft_changed")
                total = len(before)
            else:
                _guard(check_source)
                raw = build_message(prepared).as_bytes()
                if client.append(_mailbox_arg(folder), "(\\Draft)", None, raw)[0] != "OK":
                    raise RuntimeError("draft_append_failed")
                fresh_validity, after = _scope(client, folder)
                delta = set(after) - set(before)
                if (fresh_validity != validity or len(delta) != 1
                        or len(after) != len(before) + 1):
                    raise RuntimeError("draft_append_uid_scope_mismatch")
                added = after[next(iter(delta))]
                if (not added["draft_flag"] or not _matches(
                        build_message(prepared), added["message"])):
                    raise RuntimeError("draft_append_readback_mismatch")
                _assert_untouched(before, after)
                total = len(after)
            return _independent_readback(
                connector, folder, validity, prepared, "",
                operation, before, expected_total=total)

        # UPDATE and DELETE are necessarily tied to the exact old UID,
        # UIDVALIDITY and byte hash supplied by the private authorization.
        if validity != expected["uidvalidity"]:
            raise RuntimeError("uidvalidity_changed")
        if not matches:
            if (operation == "DELETE_DRAFT"
                    and expected["uid"] not in before):
                return {"status": "already_absent_unverified", "operation": operation,
                        "drafts": len(before), "sent": 0}
            raise RuntimeError("original_draft_missing")
        uid, old = matches[0]
        if (operation == "UPDATE_DRAFT" and uid != expected["uid"]
                and expected["uid"] not in before
                and _matches(build_message(prepared), old["message"])):
            return _independent_readback(
                connector, folder, validity, prepared, expected["uid"],
                operation, before, expected_total=len(before))
        _expect_target(old, uid=expected["uid"], sha=expected["sha256"])
        if (operation == "UPDATE_DRAFT"
                and prepared["email"].casefold()
                    != str(old["message"].get("To", "")).casefold()):
            raise RuntimeError("recipient_identity_changed")
        if (operation == "UPDATE_DRAFT"
                and _matches(build_message(prepared), old["message"])):
            return _independent_readback(
                connector, folder, validity, prepared, uid, "UPDATE_DRAFT",
                before, expected_total=len(before))

        if not imap.uidplus(client):
            raise RuntimeError("targeted_uid_expunge_unsupported")
        original_raw = _raw_snapshot(client, uid, old["sha256"])
        _snapshot(snapshots, draft_id=draft_id, validity=validity,
                  uid=uid, sha=old["sha256"], raw=original_raw)
        _guard(check_source)
        if operation == "DELETE_DRAFT":
            fresh_validity, current = _scope(client, folder)
            if fresh_validity != validity or set(current) != set(before):
                raise RuntimeError("mailbox_changed_before_delete")
            _assert_untouched(before, current)
            _targeted_remove(client, folder, validity, uid, old["sha256"])
            return _independent_readback(
                connector, folder, validity, {"draft_id": draft_id}, uid,
                operation, before, expected_total=len(before) - 1)

        # For updates, stage exactly one verified new MIME message before
        # removing the old message. A failed stage keeps the original intact.
        raw = build_message(prepared).as_bytes()
        if client.append(_mailbox_arg(folder), "(\\Draft)", None, raw)[0] != "OK":
            raise RuntimeError("draft_append_failed")
        new_uid = None
        removed_old = False
        try:
            fresh_validity, stage = _scope(client, folder)
            delta = set(stage) - set(before)
            if (fresh_validity != validity or len(delta) != 1
                    or len(stage) != len(before) + 1):
                raise RuntimeError("draft_stage_uid_scope_changed")
            new_uid = next(iter(delta))
            new = stage[new_uid]
            if (new["draft_id"] != draft_id or not new["draft_flag"]
                    or not _matches(build_message(prepared), new["message"])):
                raise RuntimeError("draft_stage_readback_mismatch")
            _assert_untouched(before, stage)
            _guard(check_source)
            if imap.select(client, folder, readonly=False) != validity:
                raise RuntimeError("uidvalidity_changed_before_delete")
            current = transport.scan(client)
            if set(current) != set(stage):
                raise RuntimeError("mailbox_changed_before_delete")
            _assert_untouched(stage, current)
            _expect_target(current[uid], uid=uid,
                           sha=expected["sha256"])
            if not current[uid]["draft_flag"] or not current[new_uid]["draft_flag"]:
                raise RuntimeError("draft_flag_changed_before_delete")
            _targeted_remove(client, folder, validity, uid, expected["sha256"])
            removed_old = True
        except Exception:
            # Never remove an unverified staged UID or an unrelated message.
            # On a safe failure before old removal, compensate only an exact
            # staged copy. Otherwise retain the original and fail closed.
            if not removed_old and new_uid is not None:
                try:
                    v, current = _scope(client, folder)
                    if (v == validity and uid in current and new_uid in current
                            and current[uid]["sha256"] == expected["sha256"]
                            and current[uid]["draft_flag"]
                            and _matches(build_message(prepared),
                                         current[new_uid]["message"])):
                        _targeted_remove(client, folder, validity, new_uid,
                                         current[new_uid]["sha256"])
                except Exception:
                    pass
            raise
        return _independent_readback(
            connector, folder, validity, prepared, uid, operation,
            before, expected_total=len(before))
    finally:
        # No CLOSE: IMAP CLOSE may globally expunge unrelated deleted mail.
        try:
            client.logout()
        except Exception:
            pass
