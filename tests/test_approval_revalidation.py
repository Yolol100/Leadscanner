import csv
import tempfile
import unittest
from pathlib import Path

from approval_revalidation import revalidate_approved
from dedupe_preflight import load_registry


HEADERS = [
    "company", "website", "domain", "emails", "status", "history",
    "lead_ids", "last_event_at", "sources", "exclude_from_new_leads",
]


class ApprovalRevalidationTests(unittest.TestCase):
    def registry(self, rows):
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "registry.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(HEADERS)
            writer.writerows(rows)
        return tmp, load_registry(path)

    def batch(self):
        return {
            "rows": [
                {
                    "lead_id": "growth-aaaaaaaaaaaaaaaaaaaa",
                    "company": "Acme Fietsen",
                    "website": "https://acmefietsen.nl/",
                    "official_domain": "acmefietsen.nl",
                    "email": "info@acmefietsen.nl",
                },
                {
                    "lead_id": "growth-bbbbbbbbbbbbbbbbbbbb",
                    "company": "Beta Fietsen",
                    "website": "https://betafietsen.nl/",
                    "official_domain": "betafietsen.nl",
                    "email": "info@betafietsen.nl",
                },
            ],
            "approval": {
                "approved_count": 2,
                "automatic_send": False,
            },
        }

    def test_new_approved_rows_remain_eligible(self):
        tmp, registry = self.registry([
            ["Existing", "https://existing.nl", "existing.nl", "info@existing.nl", "concept", "concept", "growth-cccccccccccccccccccc", "", "", "TRUE"]
        ])
        try:
            result = revalidate_approved(self.batch(), registry)
        finally:
            tmp.cleanup()
        self.assertEqual(result["remaining_count"], 2)
        self.assertEqual(result["suppressed_after_preview_count"], 0)
        self.assertTrue(result["safety"]["dedupe_rechecked_immediately_before_mutation"])

    def test_domain_added_after_preview_is_suppressed(self):
        tmp, registry = self.registry([
            ["Acme Fietsen", "https://acmefietsen.nl", "acmefietsen.nl", "other@acmefietsen.nl", "concept", "concept", "growth-cccccccccccccccccccc", "", "", "TRUE"]
        ])
        try:
            result = revalidate_approved(self.batch(), registry)
        finally:
            tmp.cleanup()
        self.assertEqual(result["remaining_count"], 1)
        self.assertEqual(result["suppressed_after_preview_count"], 1)
        self.assertEqual(result["suppressed_after_preview"][0]["company"], "Acme Fietsen")
        self.assertIn("domain", result["suppressed_after_preview"][0]["dedupe_match"]["matched_by"])

    def test_email_added_after_preview_is_suppressed(self):
        tmp, registry = self.registry([
            ["Different Label", "https://other.nl", "other.nl", "info@betafietsen.nl", "sent", "sent", "growth-cccccccccccccccccccc", "", "", "TRUE"]
        ])
        try:
            result = revalidate_approved(self.batch(), registry)
        finally:
            tmp.cleanup()
        self.assertEqual(result["remaining_count"], 1)
        self.assertEqual(result["suppressed_after_preview"][0]["lead_id"], "growth-bbbbbbbbbbbbbbbbbbbb")

    def test_approval_count_mismatch_fails_closed(self):
        batch = self.batch()
        batch["approval"]["approved_count"] = 1
        tmp, registry = self.registry([
            ["Existing", "https://existing.nl", "existing.nl", "info@existing.nl", "concept", "concept", "growth-cccccccccccccccccccc", "", "", "TRUE"]
        ])
        try:
            with self.assertRaisesRegex(ValueError, "approved_count_mismatch"):
                revalidate_approved(batch, registry)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
