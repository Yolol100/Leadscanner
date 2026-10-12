"""Static safeguards for one-time historical 100-contact Draft saves."""
from pathlib import Path
import unittest

SOURCE = (Path(__file__).resolve().parents[1]
          / ".github/workflows/historic-verified-review-drafts-once.yml")


class OneTimeHistoricalDraftGateTests(unittest.TestCase):
    def test_provenance_and_one_time_main_only(self):
        workflow = SOURCE.read_text(encoding="utf-8")
        for required in (
            "branches: [main]", "github.run_number == 1",
            "github.run_attempt == 1", "'[historical-reviewed-drafts]'",
            "38318758579", "38323011472",
            "13c23f8ff8408d77dfd4ae7403d6dd62e84c46b6",
            "d9c628f780475efc44441ae53add4157d9177c67",
            '"audit (" + str(offset) + ")"',
            '"failure" if offset == 1000 else "success"',
            'retries != {"recheck": ("completed", "success")}',
            "HISTORICAL_IMAP_GATE=green source_batches=12 size=1128 max_approved=53",
            "python3 -m unittest discover",
            "ref: ${{ github.sha }}",
        ):
            self.assertIn(required, workflow)
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertNotIn("workflow_run:", workflow)

    def test_100_contact_serial_batches_and_exact_draft_selftest(self):
        workflow = SOURCE.read_text(encoding="utf-8")
        for required in (
            "offset: [0, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100]",
            "max-parallel: 1", "queue: max", "cancel-in-progress: false",
            "group: leadscanner-mijnhost-drafts", "needs: [verify, smoke]",
            "live_self_draft_smoke", "synthetic_draft_cleaned",
            "LEADSCANNER_TRUSTED_HISTORICAL_WRITE: 'true'",
            '--offset "$OFFSET" --mode drafts',
            "secrets.OUTREACH_MAIL_PASSWORD",
            "persist-credentials: false",
        ):
            self.assertIn(required, workflow)
        self.assertNotIn("upload-artifact", workflow)
        self.assertNotIn("smtp.send", workflow.casefold())
        self.assertNotIn("smtplib", workflow.casefold())


if __name__ == "__main__":
    unittest.main()
