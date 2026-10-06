import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "leads-opening-bulk.yml"


class OpeningBulkWorkflowTests(unittest.TestCase):
    def test_bulk_route_is_generic_encrypted_and_serializes_apply_writes(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("[growth-opening-bulk]", text)
        self.assertIn("scripts/opening_transport.py resolve", text)
        self.assertIn("scripts/myhost_opening_bulk.py", text)
        self.assertIn("leads-content-remediation-write", text)
        self.assertIn("LEADSCANNER_WEBSITE_TOTAL_CONCURRENCY: '240'", text)
        self.assertIn("LEADSCANNER_WEBSITE_SHARD_CONCURRENCY: '60'", text)
        self.assertIn("LEADSCANNER_WEBSITE_PER_HOST: '2'", text)
        self.assertNotIn("smtplib", text)
        self.assertNotIn("sendmail(", text)
        self.assertNotIn("SMTP(", text)
        self.assertNotRegex(text, r"growth-[0-9a-f]{20}")


if __name__ == "__main__":
    unittest.main()
