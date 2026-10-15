"""Regression guards for historical 450-mailbox workflow authorization.

Tests only public workflow text. No credentials, IMAP connection, or prospect data.
"""
from pathlib import Path
import unittest


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "replace450.yml"
)


class Replace450WorkflowGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_mailbox_450_is_read_only(self):
        self.assertIn("MAILBOX450_PHASE: inspect", self.workflow)
        self.assertNotIn("LEADS_INSTALL450_ONLY:", self.workflow)
        self.assertNotIn("inputs.phase", self.workflow)
        self.assertNotIn("options: [inspect, install]", self.workflow)
        self.assertNotIn("MAILBOX450_PHASE: install", self.workflow)

    def test_approved_readonly_request_is_still_gated(self):
        self.assertIn("github.ref == 'refs/heads/main'", self.workflow)
        self.assertIn("LEADS_INSPECT450_ONLY:", self.workflow)
        self.assertIn("review450-20261015", self.workflow)
        self.assertIn("python3 scripts/live_450_draft_inventory.py", self.workflow)
        self.assertIn("persist-credentials: false", self.workflow)


if __name__ == "__main__":
    unittest.main()
