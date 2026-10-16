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
_ARCHIVE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 ]{1,80}$")


def _archive(client, *, create=False):
    if not _ARCHIVE_RE.fullmatch(ARCHIVE):
        raise RuntimeError("archive_folder_name_invalid")
    status, listed = client.list()
    if status != "OK" or not isinstance(listed, list):
        raise RuntimeError("archive_folder_list_failed")
    # Only this fixed-name private folder may be touched. We never treat
    # Drafts, INBOX, Sent or a similarly named folder as an archive.
    is_present = any(
        str(v.decode("utf-8") if isinstance(v, bytes) else v)
        .endswith('"' + ARCHIVE + '"') for v in listed
    )
    if not is_present:
        if not create:
            raise RuntimeError("archive_folder_not_initialized")
        if client.create(_mailbox_arg(ARCHIVE))[0] != "OK":
            raise RuntimeError("archive_folder_creation_failed")
    if ARCHIVE == find_drafts_folder(client):
        raise RuntimeError("archive_cannot_be_drafts")
    return ARCHIVE


def _matching(client, draft_id):
    # The dedicated archive contains only identified original messages.
    validity = transport.select(client, ARCHIVE, readonly=True)
    contents = transport.scan(client)
    entries = [(uid, row) for uid, row in contents.items()
               if row["draft_id"] == draft_id]
    if len(entries) > 1:
        raise RuntimeError("archive_duplicate_draft_id")
    if any(b"\\DELETED" in row["flags"] or row["draft_flag"]
           for row in contents.values()):
        raise RuntimeError("archive_flags_invalid")
    return validity, contents, entries


class PrivateIMAPArchive:
    """Durable, mailbox-private original MIME copies with fresh-session readback."""

    def __init__(self, *, connector=connect_imap):
        self.connector = connector

    def save(self, draft_id, uidvalidity, uid, raw):
        if not drafts.ID_PATTERN.fullmatch(draft_id) or not raw:
            raise RuntimeError("archive_identity_invalid")
        if not drafts.UID_PATTERN.fullmatch(str(uidvalidity)):
            raise RuntimeError("archive_uidvalidity_invalid")
        sha = hashlib.sha256(raw).hexdigest()
        key = (draft_id, sha)
        client = self.connector()
        try:
            _archive(client, create=True)
            validity, contents, entries = _matching(client, draft_id)
            if entries:
                archived_uid, archived = entries[0]
                if archived["sha256"] != sha:
                    raise RuntimeError("archive_original_conflict")
                if drafts._raw_snapshot(client, archived_uid, sha) != raw:
                    raise RuntimeError("archive_old_bytes_not_equal")
                return key
            before = set(contents)
            if client.append(_mailbox_arg(ARCHIVE), r"(\Seen)", None, raw)[0] != "OK":
                raise RuntimeError("archive_append_failed")
            new_validity, after, entries = _matching(client, draft_id)
            created = set(after) - before
            if (new_validity != validity or len(created) != 1
                    or len(entries) != 1 or entries[0][0] not in created
                    or after[entries[0][0]]["sha256"] != sha):
                raise RuntimeError("archive_write_scope_or_hash_mismatch")
            if drafts._raw_snapshot(client, entries[0][0], sha) != raw:
                raise RuntimeError("archive_write_mime_mismatch")
            for original_uid, previous in contents.items():
                now = after.get(original_uid)
                if (not now or now["sha256"] != previous["sha256"]
                        or now["flags"] != previous["flags"]):
                    raise RuntimeError("archive_unrelated_message_changed")
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
        client = self.connector()
        try:
            _archive(client)
            _, _, entries = _matching(client, draft_id)
            if len(entries) != 1 or entries[0][1]["sha256"] != sha:
                raise RuntimeError("archive_independent_readback_failed")
            return drafts._raw_snapshot(client, entries[0][0], sha)
        finally:
            try:
                client.logout()
            except Exception:
                pass
