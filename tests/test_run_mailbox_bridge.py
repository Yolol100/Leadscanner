from __future__ import annotations

import unittest
from unittest.mock import patch

import run_mailbox_bridge


class RunMailboxBridgeTests(unittest.TestCase):
    def test_growth_skip_audit_is_allowed_without_write_confirmation(self):
        self.assertEqual(
            run_mailbox_bridge.validate_request({"action": "audit_growth_skips"}),
            "audit_growth_skips",
        )

    @patch("run_mailbox_bridge.audit_growth_skips")
    def test_growth_skip_audit_uses_private_read_only_handler(self, audit):
        audit.return_value = {
            "review_growth_total": 1363,
            "skipped_count": 13,
            "skipped": [],
            "read_only": True,
            "smtp_send": "not_available",
        }
        result = run_mailbox_bridge.execute_request({"action": "audit_growth_skips"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "audit_growth_skips")
        self.assertTrue(result["result"]["read_only"])
        self.assertEqual(result["result"]["smtp_send"], "not_available")
        audit.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
