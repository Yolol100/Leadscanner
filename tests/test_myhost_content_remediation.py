import unittest
from unittest.mock import patch

from myhost_content_remediation import (
    _derive_refresh_evidence_terms,
    _refresh_change_from_source,
    build_corrected_row,
    validate_request,
    verify_existing_email,
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

    def test_allows_partial_batch_up_to_100_unique_ids(self):
        request = self.base_request()
        request["audited_lead_ids"] = (
            request["audited_lead_ids"][:52]
        )
        validate_request(request)

    def test_rejects_empty_batch(self):
        request = self.base_request()
        request["audited_lead_ids"] = []
        with self.assertRaises(ValueError):
            validate_request(request)

    def test_rejects_more_than_100_ids(self):
        request = self.base_request()
        request["audited_lead_ids"].append(
            "growth-ffffffffffffffffffff"
        )
        with self.assertRaises(ValueError):
            validate_request(request)

    def test_rejects_duplicate_ids(self):
        request = self.base_request()
        request["audited_lead_ids"] = [
            request["audited_lead_ids"][0],
            request["audited_lead_ids"][0],
        ]
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

    def test_rejects_invalid_language_override(self):
        request = self.base_request()
        lead_id = request["audited_lead_ids"][0]
        request["rewrites"] = {
            lead_id: {
                "observation": "Verified fact",
                "source_url": "https://example.org/",
                "evidence_terms": ["Verified"],
                "language": "de",
            }
        }
        with self.assertRaises(ValueError):
            validate_request(request)

    def test_refresh_verified_source_rows_must_be_boolean(self):
        request = self.base_request()
        request["refresh_verified_source_rows"] = "yes"
        with self.assertRaises(ValueError):
            validate_request(request)

    def test_refresh_change_rejects_low_signal_observation(self):
        source = {
            "lead_id": "growth-bbbbbbbbbbbbbbbbbbbb",
            "company": "Voorbeeld BV",
            "verified_observation": "Welkom bij Voorbeeld BV",
            "verified_observation_source_url": "https://example.nl/",
            "verified_observation_source_type": "official_site",
        }
        with self.assertRaisesRegex(
            RuntimeError,
            "low-signal",
        ):
            _refresh_change_from_source(source)

    def test_refresh_change_requires_official_site_provenance(self):
        source = {
            "lead_id": "growth-bbbbbbbbbbbbbbbbbbbb",
            "company": "Voorbeeld BV",
            "verified_observation": "Voorbeeld biedt interieuradvies in Utrecht",
            "verified_observation_source_url": "https://example.nl/",
            "verified_observation_source_type": "directory",
        }
        with self.assertRaises(RuntimeError):
            _refresh_change_from_source(source)

    def test_refresh_terms_avoid_company_only_tokens(self):
        source = {
            "lead_id": "growth-bbbbbbbbbbbbbbbbbbbb",
            "company": "Voorbeeld BV",
            "verified_observation": "Voorbeeld BV biedt interieuradvies in Utrecht",
        }
        terms = _derive_refresh_evidence_terms(source)
        self.assertIn("interieuradvies", terms)
        self.assertNotIn("voorbeeld", terms)

    def test_refresh_change_reuses_verified_official_source(self):
        source = {
            "lead_id": "growth-bbbbbbbbbbbbbbbbbbbb",
            "company": "Voorbeeld BV",
            "verified_observation": "Voorbeeld BV biedt interieuradvies in Utrecht",
            "verified_observation_source_url": "https://example.nl/diensten",
            "verified_observation_source_type": "official_site",
        }
        change = _refresh_change_from_source(source)
        self.assertEqual(
            change["source_url"],
            "https://example.nl/diensten",
        )
        self.assertEqual(
            change["observation"],
            source["verified_observation"],
        )
        self.assertTrue(change["evidence_terms"])

    @patch(
        "myhost_content_remediation.build_template",
        return_value="body",
    )
    def test_verified_language_override_updates_copy_language(
        self,
        template,
    ):
        source = {
            "lead_id": "growth-bbbbbbbbbbbbbbbbbbbb",
            "company": "Voorbeeld BV",
            "website": "https://example.nl/",
            "official_domain_hint": "example.nl",
            "email": "info@example.nl",
            "language": "en",
            "category_hint": "restaurant",
            "status": "review_draft",
            "contact_basis_status": "review_required",
        }
        change = {
            "observation": "Voorbeeld is een restaurant.",
            "source_url": "https://example.nl/",
            "evidence_terms": ["restaurant"],
            "language": "nl",
        }
        row = build_corrected_row(
            source,
            change,
            price_min=250,
            price_max=500,
            replacement=False,
        )
        self.assertEqual(row["language"], "nl")
        self.assertEqual(
            row["language_source"],
            "official_site_manual_override",
        )
        template.assert_called_once()
        self.assertEqual(
            template.call_args.args[1],
            "nl",
        )

    @patch(
        "myhost_content_remediation.fetch_html",
        return_value=(
            '<html><body>Amsterdam Nissan<script>window.data={"email":"sales.branch@example.nl"}</script></body></html>',
            "https://example.nl/branch",
            200,
        ),
    )
    @patch(
        "myhost_content_remediation.normalize_domain",
        return_value="example.nl",
    )
    def test_replacement_email_may_be_in_first_party_source_data(
        self,
        domain,
        fetch,
    ):
        source = {
            "lead_id": "growth-bbbbbbbbbbbbbbbbbbbb",
            "website": "https://example.nl/",
            "official_domain_hint": "example.nl",
        }
        change = {
            "email": "sales.branch@example.nl",
            "observation": "Amsterdam Nissan",
            "source_url": "https://example.nl/branch",
            "evidence_terms": [
                "Amsterdam Nissan",
                "sales.branch@example.nl",
            ],
        }
        result = __import__(
            "myhost_content_remediation"
        ).validate_online_evidence(
            source,
            change,
            require_email=True,
        )
        self.assertTrue(
            result["replacement_email_verified"]
        )
        self.assertIn(
            result["language"],
            {"nl", "en"},
        )
        self.assertTrue(
            result["language_source"]
        )

    @patch(
        "myhost_content_remediation.discover_contact_links",
        return_value=[],
    )
    @patch(
        "myhost_content_remediation.fetch_html",
        return_value=(
            '<html><body><a href="mailto:info@example.nl">Mail</a></body></html>',
            "https://example.nl/contact",
            200,
        ),
    )
    def test_existing_email_requires_current_first_party_presence(
        self,
        fetch,
        links,
    ):
        source = {
            "lead_id": "growth-bbbbbbbbbbbbbbbbbbbb",
            "website": "https://example.nl/",
            "official_domain_hint": "example.nl",
            "email": "info@example.nl",
            "email_source_urls": [
                "https://example.nl/contact"
            ],
            "verified_observation_source_url": (
                "https://example.nl/"
            ),
        }
        result = verify_existing_email(source)
        self.assertEqual(
            result["email"],
            "info@example.nl",
        )
        self.assertEqual(
            result["source_type"],
            "official_site",
        )

    @patch(
        "myhost_content_remediation.discover_contact_links",
        return_value=[],
    )
    @patch(
        "myhost_content_remediation.fetch_html",
        return_value=(
            "<html><body>Contact us</body></html>",
            "https://example.nl/contact",
            200,
        ),
    )
    def test_existing_email_fails_closed_when_not_currently_public(
        self,
        fetch,
        links,
    ):
        source = {
            "lead_id": "growth-bbbbbbbbbbbbbbbbbbbb",
            "website": "https://example.nl/",
            "official_domain_hint": "example.nl",
            "email": "old@example.nl",
            "email_source_urls": [],
            "email_source_types": ["overture"],
            "verified_observation_source_url": (
                "https://example.nl/contact"
            ),
        }
        with self.assertRaisesRegex(
            RuntimeError,
            "not verified",
        ):
            verify_existing_email(source)

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
