"""Static no-send guards for disposable automated historical draft handoff."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/historic-site-reviewed-drafts-followup-once.yml"
RUNNER = ROOT / "scripts/_once_historical_site_redraft.py"


class HistoricalDraftHandoffTests(unittest.TestCase):
    def test_only_one_exact_green_main_push_run_can_start_write(self):
        raw = WORKFLOW.read_text()
        for required in (
            "workflow_run:", "types: [completed]",
            "workflow_run.id == 38316829528",
            "workflow_run.head_branch == 'main'",
            "workflow_run.event == 'push'",
            "workflow_run.conclusion == 'success'",
            "workflow_run.head_sha == '8bf35235c715ce5c85e9531e82a207061cfb254f'",
            "ref: d70189dd49158b067cb8fe4cdad07f5889897b45",
            "max-parallel: 1", "--mode drafts",
        ):
            self.assertIn(required, raw)
        self.assertNotIn("upload-artifact", raw)
        self.assertNotIn("smtp.send", raw.casefold())

    def test_no_existing_draft_replacement_or_registry_update(self):
        runner = RUNNER.read_text()
        self.assertIn("reject_changed_existing=True", runner)
        self.assertIn("audit_exact_readback(review_batch, saved)", runner)
        self.assertIn('report["drafts_created"] = proof["created_count"]', runner)
        self.assertNotIn("update_registry(", runner)


if __name__ == "__main__":
    unittest.main()
