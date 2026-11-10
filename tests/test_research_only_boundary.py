"""No-network guard: retired mailbox writers must not exist in active main."""
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
class ResearchOnlyBoundary(unittest.TestCase):
    def test_only_research_workflows_enabled(self):
        paths = {p.name for p in (ROOT / ".github/workflows").glob("*.yml")}
        self.assertEqual(paths, {"fresh-leads.yml", "leads-chat-command.yml", "fast-website-evidence.yml"})
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            body = path.read_text(encoding="utf-8")
            for needle in ("OUTREACH_MAIL_PASSWORD", "OUTREACH_IMAP_HOST", "OUTREACH_SMTP", "DRAFTS_AUDIT", "myhost_draft.py", "draft_trigger.py", "schedule:"):
                with self.subTest(path=path.name, needle=needle):
                    self.assertNotIn(needle, body)
    def test_no_legacy_writers_remain(self):
        for filename in ("myhost_draft.py", "draft_management.py", "draft_trigger.py", "draft_revision.py", "sync450_openings.py", "private_imap_archive.py"):
            with self.subTest(filename=filename):
                self.assertFalse((ROOT/"scripts"/filename).exists())
    def test_suppression_guard_remains_active(self):
        body=(ROOT/"scripts/registry_readonly.py").read_text(encoding="utf-8")
        self.assertIn("DRAFT_QUEUE_ID",body)
        self.assertIn("load_discovery_suppressions",body)
        workflow=(ROOT/".github/workflows/fresh-leads.yml").read_text(encoding="utf-8")
        self.assertIn("load_discovery_suppressions",workflow)
    def test_contact_validator_remains_not_mail_sender(self):
        from business_contacts import valid_general_email
        self.assertTrue(valid_general_email("info@voorbeeld.nl"))
        self.assertFalse(valid_general_email("ongeldig"))
        body=(ROOT/"scripts/business_contacts.py").read_text(encoding="utf-8")
        self.assertNotIn("smtplib",body)
        self.assertNotIn("imaplib",body)
if __name__=="__main__":
    unittest.main()
