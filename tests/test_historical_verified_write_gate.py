"""Synthetic policy test for unmerged, one-time historical IMAP review closure."""
from pathlib import Path
import unittest

FILE = Path(__file__).resolve().parents[1] / ".github/workflows/historic-verified-review-drafts-once.yml"

class FinalHistoricalWriteGateTests(unittest.TestCase):
    def test_exact_green_main_audit_is_the_only_allowed_trigger(self):
        value = FILE.read_text()
        for required in (
            "workflow_run:", "types: [completed]",
            "workflow_run.id == 38318758579",
            "workflow_run.head_branch == 'main'",
            "workflow_run.event == 'push'",
            "workflow_run.conclusion == 'success'",
            "workflow_run.head_sha == '13c23f8ff8408d77dfd4ae7403d6dd62e84c46b6'",
            "ref: 37e89fd3d9d65cea430cbaa11cd6046b1ef58e45",
            "max-parallel: 1", "--mode drafts",
            "leadscanner-mijnhost-drafts",
            "0, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100",
        ):
            self.assertIn(required, value)
        self.assertNotIn("smtp.send", value.casefold())
        self.assertNotIn("upload-artifact", value)
        self.assertNotIn("workflow_dispatch:", value)

if __name__ == "__main__":
    unittest.main()
