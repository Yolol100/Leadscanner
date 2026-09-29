from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "leads-remove-invalid-draft.yml"


class RemoveInvalidDraftWorkflowTests(unittest.TestCase):
    def test_invalid_removal_is_evidence_bound_and_never_sends(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("[growth-draft-remove-invalid]", text)
        self.assertIn("invalid_official_site_observation", text)
        self.assertIn("INVALID_OFFICIAL_SITE_EVIDENCE=green", text)
        self.assertIn("INVALID_DRAFT_PREFLIGHT=green", text)
        self.assertIn("exact_current_match=1", text)
        self.assertIn("INVALID_DRAFT_REMOVAL_READBACK=green", text)
        self.assertIn("scripts/myhost_remove_duplicate_draft.py", text)
        self.assertIn("smtp_send=not_available", text)
        self.assertNotIn("smtplib", text)
        self.assertNotIn("sendmail(", text)
        self.assertNotIn("SMTP(", text)


if __name__ == "__main__":
    unittest.main()
