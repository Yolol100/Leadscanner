"""The historical audit workflow cannot access the mailbox or mutate drafts."""
import unittest
from pathlib import Path

class ReadOnlyHistoricalWorkflowTests(unittest.TestCase):
    def test_historical_audit_stays_no_send_and_no_imap_secrets(self):
        source = (Path(__file__).resolve().parents[1] /
                  ".github/workflows/historic-site-redraft-once.yml").read_text()
        self.assertIn("--mode audit", source)
        self.assertIn("max-parallel: 3", source)
        self.assertEqual(source.count("contains(github.event.head_commit.message, '[historical-site-audit]')"), 2)
        for forbidden in (
            "historical-site-write", "--mode drafts", "OUTREACH_MAIL_PASSWORD",
            "OUTREACH_IMAP_HOST", "LEADSCANNER_TRUSTED_HISTORICAL_WRITE",
            "upload-artifact", "smtp",
        ):
            self.assertNotIn(forbidden, source)

if __name__ == "__main__":
    unittest.main()
