from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "leads-audited-draft-remediation-once.yml"


class InvalidDraftBaselineWorkflowTests(unittest.TestCase):
    def test_remediation_uses_trusted_prior_readback_and_exact_predelete_guard(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("Download latest successful exact readback baseline", text)
        self.assertIn("load_previous_exact_versions", text)
        self.assertIn("build_expected_versions", text)
        self.assertIn("version_matches_message", text)
        self.assertIn("load_expected_versions(\"results/invalid-draft-baselines.json\", lead_id)", text)
        self.assertIn("remove_growth_draft(lead_id, expected)", text)
        self.assertIn("final-audit", text)
        self.assertNotIn("smtplib", text)
        self.assertNotIn("sendmail(", text)
        self.assertNotIn("SMTP(", text)


if __name__ == "__main__":
    unittest.main()
