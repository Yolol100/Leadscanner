"""Read-only readiness checks for the existing private draft-management library.

No GitHub issue command is registered, no automatic scheduler, no SMTP, and no
APPEND/STORE/EXPUNGE. The result is a technical preflight, not authorization
to update existing mailbox messages.
"""
from __future__ import annotations

import os
from pathlib import Path
import secrets

from private_mime_snapshots import PrivateMimeSnapshots
import draft_management as management
from myhost_draft import connect_imap, find_drafts_folder


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def private_storage_from_environment(env=None):
    """Require a private storage location outside the CI checkout and runner temp.

    GitHub-hosted Actions have ephemeral disks; a successful CI job cannot
    make original message backups durable.
    """
    env = os.environ if env is None else env
    value = str(env.get("OUTREACH_PRIVATE_SNAPSHOT_ROOT", "")).strip()
    if not value or not Path(value).is_absolute():
        raise RuntimeError("snapshot_persistent_location_unconfigured")
    root = Path(value)
    if root.resolve(strict=True) != root:
        raise RuntimeError("snapshot_symlink_path_forbidden")
    for key in ("GITHUB_WORKSPACE", "RUNNER_TEMP"):
        base = str(env.get(key, "")).strip()
        if base and _inside(root, Path(base).resolve()):
            raise RuntimeError("snapshot_ephemeral_location_forbidden")
    if (str(env.get("GITHUB_ACTIONS", "")).lower() == "true"
            and env.get("RUNNER_ENVIRONMENT") != "self-hosted"):
        raise RuntimeError("snapshot_github_hosted_runner_ephemeral")
    return PrivateMimeSnapshots(root)


def verify_storage_roundtrip(storage):
    """Write, independently read, and remove one synthetic test snapshot."""
    test_bytes = b"From: test@example.invalid\r\nSubject: Storage readiness\r\n\r\nSynthetic only\r\n"
    draft_id = "draft-" + secrets.token_hex(16)
    key = storage.save(draft_id, "1", "1", test_bytes)
    try:
        independent = PrivateMimeSnapshots(storage.root)
        if independent.read(key) != test_bytes:
            raise RuntimeError("snapshot_independent_readback_failed")
    finally:
        # Only remove the known synthetic probe; never delete real backups.
        (storage.root / key).unlink()
    return True


def check_drafts_readonly(*, connector=connect_imap):
    """Read the exact current folder; never match against old 450/509 batches.

    Only aggregate counters leave this function. Recipient and message bytes
    remain inside the connected private runtime.
    """
    management.imap.target_guard()
    client = connector()
    try:
        folder = find_drafts_folder(client)
        validity, records = management._scope(client, folder)
        if management.imap.uidset(client) != set(records):
            raise RuntimeError("mailbox_changed_during_readonly_check")
        flagged = sum(bool(row["draft_flag"]) for row in records.values())
        tracked = sum(bool(management.ID_PATTERN.fullmatch(row["draft_id"]))
                      for row in records.values())
        blocked = sum(b"\\DELETED" in row["flags"] for row in records.values())
        return {
            "status": "readonly_checked",
            "total": len(records),
            "draft_flagged": flagged,
            "tracked_ids": tracked,
            "untracked_or_invalid_ids": len(records) - tracked,
            "deleted_flagged": blocked,
            "uidvalidity_present": bool(validity),
            "modified": 0,
            "sent": 0,
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


def perform_readiness(*, env=None, connector=connect_imap):
    """No write activation: tests storage and inventories current drafts."""
    storage = private_storage_from_environment(env)
    verify_storage_roundtrip(storage)
    return {
        "storage_probe": "passed",
        "storage_persistence": "requires_independent_confirmation",
        "mailbox": check_drafts_readonly(connector=connector),
        "writer_enabled": False,
    }


if __name__ == "__main__":
    try:
        result = perform_readiness()
        counts = result["mailbox"]
        print("PRIVATE_DRAFT_PREFLIGHT=readonly_ok count={} tracked={} modified=0 sent=0"
              .format(counts["total"], counts["tracked_ids"]))
        print("PRIVATE_DRAFT_WRITER=disabled storage_persistence=unverified")
    except Exception:
        # Never expose authentication, paths, recipients or MIME in logs.
        print("PRIVATE_DRAFT_PREFLIGHT=blocked modified=0 sent=0")
        raise SystemExit(1) from None
