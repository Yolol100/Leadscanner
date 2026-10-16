"""One-off 450 replacement must remain explicitly authorized and unsent."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "reconcile450-current.yml"
SCRIPT = ROOT / "scripts" / "reconcile450_current.py"


class OneOffSafetyTests(unittest.TestCase):
    def test_dispatch_is_owner_gated_and_not_automatic(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("issue_comment:", workflow)
        self.assertIn("github.actor == 'Yolol100'", workflow)
        self.assertIn("github.event.issue.number == 1659", workflow)
        self.assertIn("LEADS_450_RECONCILE_ONLY: review450-20261016", workflow)
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertNotIn("  push:", workflow)

    def test_delete_is_targeted_and_requires_complete_readback(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("verify_new_complete(staged, expected)", script)
        self.assertIn("private_review_changed_before_remove", script)
        self.assertIn('client.uid("EXPUNGE", uid_list)', script)
        self.assertNotIn("client.expunge(", script)
        self.assertNotIn("sendmail(", script)
        self.assertNotIn("smtp", script.casefold())


if __name__ == "__main__":
    unittest.main()
