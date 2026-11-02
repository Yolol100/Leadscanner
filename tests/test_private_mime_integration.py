"""Offline integration tests for the existing draft writer and durable snapshots.

No production credentials, mailbox writes, or external services.
"""
from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import patch

import draft_management as management
from private_mime_snapshots import PrivateMimeSnapshots
from test_draft_management import DID, ROW, MemoryClient, MemoryStore, permission


class PrivateSnapshotIntegrationTests(unittest.TestCase):
    def test_update_preserves_original_mime_and_keeps_other_drafts(self):
        store = MemoryStore()
        old_uid = store.add(ROW)
        before = store.messages[old_uid][0]
        unrelated = dict(ROW, draft_id="draft-" + "b" * 32)
        unrelated_uid = store.add(unrelated)
        unrelated_original = store.messages[unrelated_uid]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "private"
            root.mkdir(mode=0o700)
            snapshots = PrivateMimeSnapshots(root)
            changed = dict(ROW, subject="New reviewed subject")
            with patch("draft_queue_readonly.is_public_http_url", return_value=True):
                result = management.execute(
                    permission("UPDATE_DRAFT"), "UPDATE_DRAFT", DID,
                    row=changed, expected=store.expected(old_uid),
                    check_source=lambda: True, snapshots=snapshots,
                    connector=lambda: MemoryClient(store),
                )
            self.assertEqual(result["status"], "verified")
            files = list(root.glob("*.eml"))
            self.assertEqual(len(files), 1)
            restored = snapshots.read(files[0].name)
            self.assertEqual(restored, before)
            self.assertEqual(hashlib.sha256(restored).digest(),
                             hashlib.sha256(before).digest())
            self.assertEqual(store.messages[unrelated_uid], unrelated_original)
            self.assertNotIn(old_uid, store.messages)

    def test_corrupt_snapshot_blocks_original_removal(self):
        store = MemoryStore()
        original_uid = store.add(ROW)
        original = store.messages[original_uid]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "private"
            root.mkdir(mode=0o700)
            snapshots = PrivateMimeSnapshots(root)
            old_save = snapshots.save

            def corrupt_after_save(draft_id, validity, uid, raw):
                key = old_save(draft_id, validity, uid, raw)
                (root / key).write_bytes(b"changed")
                return key

            snapshots.save = corrupt_after_save
            with patch("draft_queue_readonly.is_public_http_url", return_value=True):
                with self.assertRaisesRegex(RuntimeError, "snapshot_readback_failed"):
                    management.execute(
                        permission("UPDATE_DRAFT"), "UPDATE_DRAFT", DID,
                        row=dict(ROW, subject="New reviewed subject"),
                        expected=store.expected(original_uid),
                        check_source=lambda: True, snapshots=snapshots,
                        connector=lambda: MemoryClient(store),
                    )
            self.assertEqual(store.messages[original_uid], original)
            self.assertEqual(store.deleted, [])
            self.assertEqual(store.append_count, 0)


if __name__ == "__main__":
    unittest.main()
