from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "leads-audited-draft-remediation-once.yml"


class TargetedDraftRemediationWorkflowTests(unittest.TestCase):
    def test_remediation_is_bound_to_existing_target_drafts_only(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("target_lead_ids = {", text)
        self.assertIn("target set mismatch", text)
        self.assertIn("TARGET_DRAFT_PREFLIGHT=green count=26 existing=26", text)
        self.assertIn("--rewrite-existing-only", text)
        self.assertIn('test "$total" -eq 26', text)
        self.assertIn("Final read-only audit group A", text)
        self.assertIn("Final read-only audit group B", text)
        self.assertNotIn("remove_growth_draft", text)
        self.assertNotIn("INVALID_DRAFT_REMOVALS", text)
        self.assertNotIn("smtplib", text)
        self.assertNotIn("sendmail(", text)
        self.assertNotIn("SMTP(", text)


if __name__ == "__main__":
    unittest.main()
