"""Private IMAP archive adapter for the existing draft_management executor.

No SMTP, no cloud/public artifacts and no global EXPUNGE/CLOSE. Every archive
write is exact-MIME-verified in the same folder and independently read again.
"""
from __future__ import annotations

import hashlib
import re

import draft_management as drafts
import replace450 as transport
from myhost_draft import _mailbox_arg, connect_imap, find_drafts_folder

ARCHIVE = "Webactueel Original Drafts 20261017"
REVISION_ARCHIVE = "Webactueel Drafts Before Revision 20261018"
_ARCHIVE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 ]{1,80}$")


def _archive(client, *, create=False, folder=None):
    folder = ARCHIVE if folder is None else folder
    if folder not in {ARCHIVE, REVISION_ARCHIVE} or not _ARCHIVE_RE.fullmatch(folder):
        raise RuntimeError("archive_folder_name_invalid")
    status, listed = client.list()
    if status != "OK" or not isinstance(listed, list):
        raise RuntimeError("archive_folder_list_failed")
    # Only the fixed-name private version folders may be touched. Never treat
    # Drafts, INBOX, Sent or a similarly named folder as an archive.
    is_present = any(
        str(v.decode("utf-8") if isinstance(v, bytes) else v)
        .endswith('"' + folder + '"') for v in listed
    )
    if not is_present:
        if not create:
            raise RuntimeError("archive_folder_not_initialized")
        if client.create(_mailbox_arg(folder))[0] != "OK":
            raise RuntimeError("archive_folder_creation_failed")
    if folder == find_drafts_folder(client):
        raise RuntimeError("archive_cannot_be_drafts")
    return folder


def _archive_index(client):
    """One complete archive scan per private operation batch, not per draft.

    transport.scan enforces before/after UID equality and hashes every MIME.
    The resulting index is only reused while UIDVALIDITY and the full UID set
    stay unchanged. Every referenced original is still fetched and SHA-checked
    in a fresh IMAP session before a Drafts deletion may proceed.
    """
    validity = transport.select(client, ARCHIVE, readonly=True)
    scanned = transport.scan(client)
    index = {}
    for uid, item in scanned.items():
        draft_id = item["draft_id"]
        if not drafts.ID_PATTERN.fullmatch(draft_id):
            raise RuntimeError("archive_identity_invalid")
        if draft_id in index:
            raise RuntimeError("archive_duplicate_draft_id")
        if item["draft_flag"] or b"\\DELETED" in item["flags"]:
            raise RuntimeError("archive_flags_invalid")
        index[draft_id] = (uid, item["sha256"])
    return validity, set(scanned), index


class PrivateIMAPArchive:
    """Private original MIME archive: once-per-batch index, exact per-UID proof."""

    def __init__(self, *, connector=connect_imap):
        self.connector = connector
        self._validity = None
        self._uids = None
        self._index = None

    def _initialize(self):
        if self._index is not None:
            return
        client = self.connector()
        try:
            _archive(client, create=True)
            validity, uids, index = _archive_index(client)
            self._validity, self._uids, self._index = validity, uids, index
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def _check_session(self, client):
        _archive(client)
        validity = transport.select(client, ARCHIVE, readonly=True)
        # Never reuse the private snapshot if an external archive append,
        # deletion or UIDVALIDITY reset occurred during this batch.
        if validity != self._validity or transport.uidset(client) != self._uids:
            raise RuntimeError("archive_scope_changed")

    @staticmethod
    def _check_original(item, draft_id, sha):
        if (item["draft_id"] != draft_id or item["sha256"] != sha):
            raise RuntimeError("archive_independent_readback_failed")
        if item["draft_flag"] or b"\\DELETED" in item["flags"]:
            raise RuntimeError("archive_flags_invalid")

    def save(self, draft_id, uidvalidity, uid, raw):
        if not drafts.ID_PATTERN.fullmatch(draft_id) or not raw:
            raise RuntimeError("archive_identity_invalid")
        if not drafts.UID_PATTERN.fullmatch(str(uidvalidity)):
            raise RuntimeError("archive_uidvalidity_invalid")
        sha = hashlib.sha256(raw).hexdigest()
        key = (draft_id, sha)
        self._initialize()
        client = self.connector()
        try:
            self._check_session(client)
            known = self._index.get(draft_id)
            if known:
                archived_uid, old_sha = known
                if old_sha != sha:
                    raise RuntimeError("archive_original_conflict")
                saved = transport.fetch_message(client, archived_uid)
                self._check_original(saved, draft_id, sha)
                if drafts._raw_snapshot(client, archived_uid, sha) != raw:
                    raise RuntimeError("archive_old_bytes_not_equal")
                return key
            if client.append(_mailbox_arg(ARCHIVE), r"(\Seen)", None, raw)[0] != "OK":
                raise RuntimeError("archive_append_failed")
            new_validity = transport.select(client, ARCHIVE, readonly=True)
            after_uids = transport.uidset(client)
            created = after_uids - self._uids
            if (new_validity != self._validity
                    or len(created) != 1
                    or len(after_uids) != len(self._uids) + 1
                    or not self._uids.issubset(after_uids)):
                raise RuntimeError("archive_write_scope_or_hash_mismatch")
            archived_uid = next(iter(created))
            saved = transport.fetch_message(client, archived_uid)
            if saved["draft_id"] != draft_id or saved["sha256"] != sha:
                raise RuntimeError("archive_write_scope_or_hash_mismatch")
            self._check_original(saved, draft_id, sha)
            if drafts._raw_snapshot(client, archived_uid, sha) != raw:
                raise RuntimeError("archive_write_mime_mismatch")
            # Update the in-process index only AFTER exact independent-source
            # checks. The caller's separate .read() opens a FRESH connection.
            self._uids = set(after_uids)
            self._index[draft_id] = (archived_uid, sha)
            return key
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def read(self, key):
        draft_id, sha = key
        if (not drafts.ID_PATTERN.fullmatch(draft_id)
                or not drafts.SHA_PATTERN.fullmatch(sha)):
            raise RuntimeError("archive_read_identity_invalid")
        self._initialize()
        client = self.connector()
        try:
            self._check_session(client)
            known = self._index.get(draft_id)
            if known is None or known[1] != sha:
                raise RuntimeError("archive_independent_readback_failed")
            archived_uid = known[0]
            saved = transport.fetch_message(client, archived_uid)
            self._check_original(saved, draft_id, sha)
            return drafts._raw_snapshot(client, archived_uid, sha)
        finally:
            try:
                client.logout()
            except Exception:
                pass
