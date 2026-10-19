"""Private IMAP archive adapter for the existing draft_management executor.

No SMTP, no cloud/public artifacts and no global EXPUNGE/CLOSE. Every archive
write is exact-MIME-verified in the same folder and independently read again.
"""
from __future__ import annotations

import hashlib
import re
from email import policy
from email.parser import BytesParser

import draft_management as drafts
import replace450 as transport
from myhost_draft import (_mailbox_arg, _matches, build_message,
                          connect_imap, find_drafts_folder)

ARCHIVE = "Webactueel Original Drafts 20261017"
REVISION_ARCHIVE = "Webactueel Drafts Before Revision 20261018"
V2_ARCHIVE = "Webactueel Drafts Before V2 20261019"
V2_CREATED = "Webactueel V2 Missing Draft Proof 20261019"
_ARCHIVE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 ]{1,80}$")


def _archive(client, *, create=False, folder=None):
    folder = ARCHIVE if folder is None else folder
    if folder not in {ARCHIVE, REVISION_ARCHIVE, V2_ARCHIVE, V2_CREATED} or not _ARCHIVE_RE.fullmatch(folder):
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


def _archive_index(client, *, folder=ARCHIVE):
    """One complete archive scan per private operation batch, not per draft.

    transport.scan enforces before/after UID equality and hashes every MIME.
    The resulting index is only reused while UIDVALIDITY and the full UID set
    stay unchanged. Every referenced original is still fetched and SHA-checked
    in a fresh IMAP session before a Drafts deletion may proceed.
    """
    validity = transport.select(client, folder, readonly=True)
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

    def __init__(self, *, connector=connect_imap, folder=ARCHIVE):
        if folder not in {ARCHIVE, V2_CREATED}:
            raise RuntimeError("archive_folder_name_invalid")
        self.connector = connector
        self.folder = folder
        self._validity = None
        self._uids = None
        self._index = None

    def _initialize(self):
        if self._index is not None:
            return
        client = self.connector()
        try:
            _archive(client, create=True, folder=self.folder)
            validity, uids, index = _archive_index(client, folder=self.folder)
            self._validity, self._uids, self._index = validity, uids, index
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def _check_session(self, client):
        _archive(client, folder=self.folder)
        validity = transport.select(client, self.folder, readonly=True)
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
            if client.append(_mailbox_arg(self.folder), r"(\Seen)", None, raw)[0] != "OK":
                raise RuntimeError("archive_append_failed")
            new_validity = transport.select(client, self.folder, readonly=True)
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

    def prepare_missing_draft(self, draft_id, uidvalidity, proposed):
        """Archive intended MIME first, and safely reuse it on retries.

        Caller must prove the draft ID absent in the full live mailbox.
        This fixed private proof folder stores new, not old, generations.
        """
        if self.folder != V2_CREATED or proposed.get("draft_id") != draft_id:
            raise RuntimeError("archive_recovery_identity_invalid")
        self._initialize()
        known = self._index.get(draft_id)
        if known:
            raw = self.read((draft_id, known[1]))
            actual = BytesParser(policy=policy.default).parsebytes(raw)
            if not _matches(build_message(proposed), actual):
                raise RuntimeError("archive_recovery_content_changed")
            return raw
        raw = build_message(proposed).as_bytes()
        key = self.save(draft_id, uidvalidity, None, raw)
        if self.read(key) != raw:
            raise RuntimeError("archive_recovery_readback_invalid")
        return raw
