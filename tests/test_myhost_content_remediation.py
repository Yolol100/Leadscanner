import unittest
from unittest.mock import patch

from myhost_content_remediation import (
    build_corrected_row,
    validate_request,
)


class ContentRemediationTests(unittest.TestCase):
    def base_request(self):
        ids = [
            f"growth-{i:020x}"
            for i in range(100)
        ]
        return {
            "batch_id": "batch-001",
            "source_archive_artifact_id": 123,
            "source_artifact_ids": [456],
            "audited_lead_ids": ids,
            "rewrites": {},
            "replacements": {},
            "holds": [],
        }

    def test_requires_exactly_100_unique_ids(self):
        request = self.base_request()
        request["audited_lead_ids"] = (
            request["audited_lead_ids"][:-1]
        )
        with self.assertRaises(ValueError):
            validate_request(request)

    def test_changes_stay_inside_audited_scope(self):
        request = self.base_request()
        request["rewrites"] = {
            "growth-ffffffffffffffffffff": {
                "observation": "Verified fact",
                "source_url": "https://example.org/",
                "evidence_terms": ["Verified"],
            }
        }
        with self.assertRaises(ValueError):
            validate_request(request)

    @patch(
        "myhost_content_remediation.valid_email",
        return_value=True,
    )
    @patch(
        "myhost_content_remediation.build_template",
        return_value="body",
    )
    @patch(
        "myhost_content_remediation.stable_lead_id",
        return_value="growth-aaaaaaaaaaaaaaaaaaaa",
    )
    def test_replacement_recomputes_id_and_stays_review_required(
        self,
        stable,
        template,
        valid,
    ):
        source = {
            "lead_id": "growth-bbbbbbbbbbbbbbbbbbbb",
            "company": "Example BV",
            "website": "https://example.nl/",
            "official_domain_hint": "example.nl",
            "email": "old@example.nl",
            "language": "nl",
            "category_hint": "restaurant",
            "status": "review_draft",
            "contact_basis_status": "review_required",
        }
        change = {
            "email": "new@example.nl",
            "observation": "Example is een restaurant.",
            "source_url": "https://example.nl/contact",
            "evidence_terms": ["restaurant"],
        }
        row = build_corrected_row(
            source,
            change,
            price_min=250,
            price_max=500,
            replacement=True,
        )
        self.assertEqual(
            row["lead_id"],
            "growth-aaaaaaaaaaaaaaaaaaaa",
        )
        self.assertEqual(
            row["email"],
            "new@example.nl",
        )
        self.assertEqual(
            row["status"],
            "review_draft",
        )
        self.assertEqual(
            row["contact_basis_status"],
            "review_required",
        )
        self.assertEqual(
            row["verified_observation_source_type"],
            "official_site",
        )


if __name__ == "__main__":
    unittest.main()
