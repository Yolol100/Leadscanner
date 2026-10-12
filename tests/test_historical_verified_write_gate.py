"""Only an audited 1,128-contact protected-main run can unlock IMAP saves."""
from pathlib import Path
import unittest

FILE = Path(__file__).resolve().parents[1] / ".github/workflows/historic-verified-review-drafts-once.yml"

class FinalHistoricalWriteGateTests(unittest.TestCase):
    def test_main_commit_marker_and_green_independent_audit_proof_required(self):
        value = FILE.read_text()
        for required in (
            "push:", "branches: [main]",
            "contains(github.event.head_commit.message, '[historical-reviewed-drafts]')",
            "audit_id = 38318758579",
            "expected_sha = '13c23f8ff8408d77dfd4ae7403d6dd62e84c46b6'",
            "run.get('conclusion') == 'success'",
            "run.get('event') == 'push'",
            "run.get('head_branch') == 'main'",
            "jobs.get('total_count') == 13",
            "actual == expected",
            "HISTORICAL_AUDIT_GATE=green batches=12 identities=1128",
            "ref: 37e89fd3d9d65cea430cbaa11cd6046b1ef58e45",
            "max-parallel: 1", "--mode drafts",
            "leadscanner-mijnhost-drafts",
            "0, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100",
        ):
            self.assertIn(required, value)
        self.assertNotIn("smtp.send", value.casefold())
        self.assertNotIn("upload-artifact", value)
        self.assertNotIn("workflow_dispatch:", value)
        self.assertNotIn("workflow_run:", value)

if __name__ == "__main__":
    unittest.main()
