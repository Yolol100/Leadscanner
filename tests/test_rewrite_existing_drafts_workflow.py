from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "leads-rewrite-existing-drafts.yml"


class RewriteExistingDraftWorkflowTests(unittest.TestCase):
    def test_rewrite_workflow_is_bounded_and_draft_only(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("[growth-draft-rewrite]", text)
        self.assertIn("scripts/prepare_growth_batch.py", text)
        self.assertIn("scripts/myhost_draft.py", text)
        self.assertIn("replaced_count", text)
        self.assertIn("PERSONALIZED_REWRITE_READBACK=green", text)
        self.assertIn("smtp_send=not_available", text)
        self.assertNotIn("extract_public_contacts.py", text)
        self.assertNotIn("overture_discovery.py", text)
        self.assertNotIn("hybrid_discovery.py", text)
        self.assertNotIn("smtplib", text)
        self.assertNotIn("sendmail(", text)
        self.assertNotIn("SMTP(", text)


if __name__ == "__main__":
    unittest.main()
