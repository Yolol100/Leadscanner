"""Prevent archived six-template migration commands from writing old IMAP drafts."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "sync450-openings.yml"

class RetiredExistingDraftTriggersTests(unittest.TestCase):
    def test_only_non_mailbox_mutating_owner_modes_are_triggerable(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        allowed = {
            "LEADS_CONVERSATIONS_V1:PRECHECK",
            "LEADS_CONVERSATIONS_V1:AUDIT",
            "LEADS_CONVERSATIONS_V1:REVISION_PRECHECK",
            "LEADS_CONVERSATIONS_V1:RECREATE_PRECHECK",
            "LEADS_V2_DRAFTS:PRECHECK",
            "LEADS_V2_DRAFTS:AUDIT",
            "LEADS_V2_DRAFTS:PREPARE60",
        }
        enabled = set(re.findall(
            r"github[.]event[.]comment[.]body == '([^']+)'", text))
        self.assertEqual(enabled, allowed)
        self.assertIn("github.actor == 'Yolol100'", text)
        self.assertIn("github.event.comment.user.login == 'Yolol100'", text)
        self.assertIn("github.event.issue.number == 1659", text)
        self.assertNotIn("schedule:", text)
        self.assertNotIn("workflow_dispatch:", text)
        self.assertNotIn("SMTP", text)

if __name__ == "__main__":
    unittest.main()
