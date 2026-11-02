"""Private, durable original-MIME snapshots for draft_management.py.

Not a live command. Mount root on private persistent storage outside this repo.
No customer data, keys, or MIME bytes are printed or committed to GitHub.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path

DRAFT_ID = re.compile(r"draft-[0-9a-f]{32}\Z")
POSITIVE = re.compile(r"[1-9][0-9]*\Z")
KEY = re.compile(r"[0-9a-f]{64}\.eml\Z")


class PrivateMimeSnapshots:
    """Fail-closed adapter implementing save/read for draft_management.execute."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).absolute()
        if self.root.is_symlink() or not self.root.is_dir():
            raise RuntimeError("snapshot_private_directory_missing")
        mode = self.root.stat().st_mode
        if not stat.S_ISDIR(mode) or (mode & 0o077):
            raise RuntimeError("snapshot_directory_permissions_unsafe")

    def _path(self, key: str) -> Path:
        if not KEY.fullmatch(key):
            raise RuntimeError("snapshot_key_invalid")
        return self.root / key

    def save(self, draft_id: str, validity: str, uid: str, raw: bytes) -> str:
        if (not DRAFT_ID.fullmatch(str(draft_id))
                or not POSITIVE.fullmatch(str(validity))
                or not POSITIVE.fullmatch(str(uid))
                or not isinstance(raw, bytes) or not raw):
            raise RuntimeError("snapshot_identity_invalid")
        digest = hashlib.sha256(raw).hexdigest()
        # Key depends on exact content AND mailbox identity; no recipient PII.
        key = hashlib.sha256(
            (draft_id + ":" + validity + ":" + uid + ":" + digest).encode()
        ).hexdigest() + ".eml"
        path = self._path(key)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags, 0o600)
        except FileExistsError:
            if self.read(key) != raw:
                raise RuntimeError("snapshot_existing_conflict")
            return key
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            # Do not claim a failed/partial snapshot as a durable recovery.
            raise RuntimeError("snapshot_write_failed") from None
        if self.read(key) != raw:
            raise RuntimeError("snapshot_readback_failed")
        return key

    def read(self, key: str) -> bytes:
        path = self._path(key)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise RuntimeError("snapshot_not_regular_file")
            if os.fstat(stream.fileno()).st_mode & 0o077:
                raise RuntimeError("snapshot_file_permissions_unsafe")
            return stream.read()
