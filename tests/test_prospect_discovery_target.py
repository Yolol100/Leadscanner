import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "prospect_discovery_runtime.py"
WORKFLOW = ROOT / ".github" / "workflows" / "prospect-discovery.yml"
CANONICAL_SHEET_ID = "1p4vZnCdcex9zpTAV-ssebXqZcBS2TU6KfXwS-4d2iSI"


class ProspectDiscoveryTargetTests(unittest.TestCase):
    def test_workflow_exposes_bounded_target_fill_without_mail_secrets(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("PROSPECT_DISCOVERY_TARGET_NEW: ${{ vars.PROSPECT_DISCOVERY_TARGET_NEW || '10' }}", text)
        self.assertIn("PROSPECT_DISCOVERY_MAX_TOTAL: ${{ vars.PROSPECT_DISCOVERY_MAX_TOTAL || '25' }}", text)
        self.assertIn(f"OUTREACH_SPREADSHEET_ID: ${{{{ vars.OUTREACH_SPREADSHEET_ID || '{CANONICAL_SHEET_ID}' }}}}", text)
        self.assertNotIn("OUTREACH_MAIL_PASSWORD", text)
        self.assertNotIn("OUTREACH_MAILBOXES_JSON", text)

    def test_runtime_persists_observations_only_when_tab_exists(self):
        text = RUNTIME.read_text(encoding="utf-8")
        self.assertIn('"ProspectObservations": OBSERVATION_HEADERS', text)
        self.assertIn('observation_persisted = "ProspectObservations" in sheet_titles', text)
        self.assertIn("make_observation_row", text)

    def test_runtime_reports_target_gap_instead_of_faking_completion(self):
        text = RUNTIME.read_text(encoding="utf-8")
        self.assertIn("clamp_target", text)
        self.assertIn("target_summary", text)
        self.assertIn('"source_results": source_results', text)


if __name__ == "__main__":
    unittest.main()
