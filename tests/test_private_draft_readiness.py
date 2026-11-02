"""No-network tests for private draft readiness. All identities are fictional."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import private_draft_readiness as readiness
from test_draft_management import MemoryClient, MemoryStore, ROW


class ReadinessTests(unittest.TestCase):
    def test_storage_probe_leaves_no_messages_or_test_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "private"
            root.mkdir(mode=0o700)
            storage = readiness.private_storage_from_environment(
                {"OUTREACH_PRIVATE_SNAPSHOT_ROOT": str(root)})
            self.assertTrue(readiness.verify_storage_roundtrip(storage))
            self.assertEqual(list(root.iterdir()), [])

    def test_reject_insecure_or_ephemeral_storage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "private"
            root.mkdir(mode=0o700)
            env = {"OUTREACH_PRIVATE_SNAPSHOT_ROOT": str(root)}
            with self.assertRaisesRegex(RuntimeError, "ephemeral"):
                readiness.private_storage_from_environment(
                    {**env, "RUNNER_TEMP": temp})
            with self.assertRaisesRegex(RuntimeError, "github_hosted_runner"):
                readiness.private_storage_from_environment(
                    {**env, "GITHUB_ACTIONS": "true"})
            root.chmod(0o755)
            with self.assertRaisesRegex(RuntimeError, "permissions"):
                readiness.private_storage_from_environment(env)

    def test_readonly_inventory_has_no_mailbox_writes(self):
        store = MemoryStore()
        store.add(ROW)
        store.add(dict(ROW, draft_id="draft-" + "b" * 32))
        client = lambda: MemoryClient(store)
        with patch.object(readiness.management.imap, "target_guard"):
            result = readiness.check_drafts_readonly(connector=client)
        self.assertEqual(result["status"], "readonly_checked")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["tracked_ids"], 2)
        self.assertEqual(result["modified"], 0)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(store.append_count, 0)
        self.assertEqual(store.deleted, [])


if __name__ == "__main__":
    unittest.main()
