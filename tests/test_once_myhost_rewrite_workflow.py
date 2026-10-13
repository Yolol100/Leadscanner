"""Freeze explicit one-time rewrite-only conditions and no SMTP leakage."""
from pathlib import Path
import unittest

WORKFLOW = (Path(__file__).resolve().parents[1] /
            ".github/workflows/once-myhost-existing-rewrite-100.yml")

class RewriteWorkflowTests(unittest.TestCase):
    def test_one_time_only_existing_drafts_exactly_12_consecutive_batches(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        for marker in (
            "branches: [main]",
            "github.run_attempt == 1",
            "'[myhost-1173-rewrite]'",
            "max-parallel: 1",
            "offset: [0, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100]",
            "needs: [verify, readonly]",
            "--mode review",
            "--mode rewrite",
            "LEADSCANNER_TRUSTED_REWRITE: 'true'",
            "leadscanner-mijnhost-drafts",
            "persist-credentials: false",
            "python3 -m unittest discover",
        ):
            self.assertIn(marker, text)
        for forbidden in ("workflow_dispatch:", "smtp", "--mode drafts",
                          "upload-artifact", "actions/download-artifact"):
            self.assertNotIn(forbidden, text.lower())
    def test_old_blanket_rewrite_prohibition_removed_without_new_draft_creation(self):
        rules = (Path(__file__).resolve().parents[1] / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("Vervang gewijzigde concepten nooit automatisch.", rules)
        self.assertIn("een ontbrekend concept mag nooit worden aangemaakt", rules)


if __name__ == "__main__":
    unittest.main()
