"""Synthetic-only source regression: discovery eligibility cannot erase history."""
import unittest
from _once_historical_source_diagnose import LIST_ID, classify

class HistoricalSourceDiagnosticTests(unittest.TestCase):
    def row(self, idx, email):
        return {
            "id": f"00000000-0000-4000-8000-{idx:012d}",
            "list_id": LIST_ID, "email": email, "payload": {},
        }

    def test_historical_address_not_eligible_for_new_prospect_is_still_an_identity(self):
        summary = classify([self.row(1, "noreply@business.nl")])
        self.assertEqual(summary["records"], 1)
        self.assertEqual(summary["new_lead_email_ineligible"], 1)
        self.assertEqual(summary["missing_normalized_email"], 0)
        self.assertEqual(summary["copy_absent"], 1)

    def test_duplicates_and_missing_identity_are_counted_separately(self):
        summary = classify([self.row(1, "info@a.nl"), self.row(1, "info@a.nl"), self.row(2, None)])
        self.assertEqual(summary["duplicate_source_id"], 1)
        self.assertEqual(summary["duplicate_email"], 1)
        self.assertEqual(summary["missing_normalized_email"], 1)

    def test_field_coverage_is_aggregate_only(self):
        row = self.row(1, "info@sample.nl")
        row["company_name"] = "Synthetic Business"
        row["website"] = "https://sample.nl/"
        row["company_domain"] = "sample.nl"
        row["payload"] = {
            "companyName": "Synthetic Business",
            "leadscanner_site_refresh_official_domain": "sample.nl",
        }
        summary = classify([row])
        self.assertEqual(summary["raw_company_name"], 1)
        self.assertEqual(summary["raw_website"], 1)
        self.assertEqual(summary["raw_company_domain"], 1)
        self.assertEqual(summary["payload_company_name"], 1)
        self.assertEqual(summary["payload_official_domain"], 1)
        self.assertNotIn("Synthetic Business", str(summary))

    def test_copy_fields_are_not_logged_or_returned(self):
        row = self.row(1, "info@a.nl")
        row["payload"]["leadscanner_site_refresh_subject"] = "SYNTHETIC PRIVATE SUBJECT"
        row["payload"]["leadscanner_site_refresh_body"] = "SYNTHETIC PRIVATE BODY"
        summary = classify([row])
        self.assertEqual(summary["copy_subject_and_body"], 1)
        self.assertNotIn("SYNTHETIC", str(summary))

if __name__ == "__main__":
    unittest.main()
