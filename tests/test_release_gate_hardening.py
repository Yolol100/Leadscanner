import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


class ReleaseGateHardeningTests(unittest.TestCase):
    def test_live_outreach_requires_green_sender_readiness(self):
        text = (WORKFLOWS / "outreach-smtp.yml").read_text(encoding="utf-8")
        section = text.split("- name: Run live sender readiness gate", 1)[1].split(
            "- name: Run LeadPromo copy preflight", 1
        )[0]
        self.assertIn("OUTREACH_READINESS_REQUIRE_GREEN: 'true'", section)
        self.assertIn("outreach_sender_readiness.py", section)

    def test_myhost_draft_route_is_manual_only_and_self_only(self):
        text = (WORKFLOWS / "myhost-draft-test.yml").read_text(encoding="utf-8")
        trigger = text.split("permissions:", 1)[0]
        self.assertIn("workflow_dispatch:", trigger)
        self.assertNotIn("push:", trigger)
        self.assertNotIn("schedule:", trigger)
        self.assertNotIn("draft-test-request.txt", text)
        self.assertIn("OUTREACH_DRAFT_SELF_ONLY: 'true'", text)
        self.assertIn("outreach_imap_draft.py", text)
        self.assertNotIn("outreach_direct_smtp_runtime.py", text)


if __name__ == "__main__":
    unittest.main()
