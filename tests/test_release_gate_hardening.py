import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


class ReleaseGateHardeningTests(unittest.TestCase):
    def test_legacy_live_smtp_workflow_is_not_on_default_branch(self):
        self.assertFalse((WORKFLOWS / "outreach-smtp.yml").exists())
        registry = json.loads((ROOT / "tool-registry.json").read_text(encoding="utf-8"))
        self.assertTrue(registry["policy"]["draft_only"])
        self.assertEqual(registry["policy"]["send_permission"], "none")
        self.assertNotIn("outreach-smtp.yml", json.dumps(registry, sort_keys=True))

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
