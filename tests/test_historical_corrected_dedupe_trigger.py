"""Bound corrected mailbox scan to explicit protected-main read-only audit."""
from pathlib import Path
import unittest

P = Path(__file__).resolve().parents[1] / ".github/workflows/historic-full-folder-duplicate-once.yml"


class CorrectedDedupeWorkflowTests(unittest.TestCase):
    def test_one_commit_only_on_main_with_no_mutations(self):
        x = P.read_text(encoding="utf-8")
        for required in (
            "branches: [main]",
            "github.run_attempt == 1",
            "'[historical-corrected-dedupe]'",
            "python3 scripts/_once_historical_myhost_audit.py --mode deep",
            "persist-credentials: false",
            "leadscanner-mijnhost-drafts",
            "python3 -m unittest discover",
        ):
            self.assertIn(required, x)
        for disallowed in ("workflow_dispatch:", "--mode drafts", "smtp.send", "imap.append"):
            self.assertNotIn(disallowed, x.casefold())


if __name__ == "__main__":
    unittest.main()
