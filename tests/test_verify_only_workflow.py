from __future__ import annotations

import pathlib
import unittest

from build_verification_ready import build_ready
from select_verification_batch import select_candidates


class VerifyOnlyTests(unittest.TestCase):
    def test_unrelated_issues_do_not_share_verify_concurrency_group(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        text = (root / ".github" / "workflows" / "leads-verify.yml").read_text(encoding="utf-8")
        self.assertIn("startsWith(github.event.issue.title, '[lead-verify]')", text)
        self.assertIn("contains(github.event.issue.title, 'overture-fixed')", text)
        self.assertIn("leads-verify-overture-active", text)
        self.assertIn("leads-verify-maps-active", text)
        self.assertIn("leads-verify-dispatch-active", text)
        self.assertIn("github.run_id", text)
        self.assertIn("cancel-in-progress: false", text)

    def test_selector_restores_hybrid_provenance_and_bounds_to_100(self):
        phase2 = {
            "candidates": [
                {
                    "name_hint": "Voorbeeld",
                    "website_hint": "https://www.example.nl/contact",
                    "google_maps_place_id": "place-1",
                }
            ]
        }
        hybrid = {
            "candidates": [
                {
                    "name_hint": "Voorbeeld",
                    "website_hint": "https://example.nl/",
                    "google_maps_place_id": "place-1",
                    "discovery_email_candidates": [
                        {"email": "info@example.nl", "source": "google_maps"}
                    ],
                }
            ]
        }
        result = select_candidates(phase2, hybrid, offset=0, limit=100)
        self.assertEqual(result["selected_count"], 1)
        self.assertEqual(
            result["candidates"][0]["discovery_email_candidates"][0]["email"],
            "info@example.nl",
        )
        self.assertFalse(result["safety"]["copy_created"])
        self.assertFalse(result["safety"]["draft_created"])
        self.assertFalse(result["safety"]["email_send"])

    def test_selector_rejects_more_than_100(self):
        with self.assertRaises(ValueError):
            select_candidates({"candidates": []}, {"candidates": []}, offset=0, limit=101)

    def test_ready_requires_email_observation_and_provenance(self):
        payload = {
            "candidates": [
                {
                    "name_hint": "Voorbeeld BV",
                    "website_hint": "https://example.nl/",
                    "official_domain_hint": "example.nl",
                    "language": "nl",
                    "public_business_emails": ["info@example.nl"],
                    "email_source_types": ["official_site"],
                    "email_source_urls": ["https://example.nl/contact"],
                    "verified_observation": "Voorbeeld dienstverlening in Nederland",
                    "verified_observation_source_url": "https://example.nl/",
                    "verified_observation_source_type": "official_site",
                    "contact_basis_status": "review_required",
                    "contact_discovery_status": "found_official_site",
                    "excluded_competitor": False,
                },
                {
                    "name_hint": "Geen observatie",
                    "website_hint": "https://no-observation.nl/",
                    "official_domain_hint": "no-observation.nl",
                    "language": "nl",
                    "public_business_emails": ["info@no-observation.nl"],
                    "email_source_types": ["official_site"],
                    "email_source_urls": ["https://no-observation.nl/contact"],
                    "contact_basis_status": "review_required",
                    "contact_discovery_status": "found_official_site",
                    "excluded_competitor": False,
                },
            ]
        }
        result = build_ready(payload)
        self.assertEqual(result["ready_for_copy_count"], 1)
        self.assertEqual(result["blocked_or_skipped_count"], 1)
        self.assertEqual(result["ready_for_copy"][0]["email_source"], "https://example.nl/contact")
        self.assertFalse(result["safety"]["copy_created"])
        self.assertFalse(result["safety"]["draft_created"])
        self.assertFalse(result["safety"]["email_send"])

    def test_targeted_maps_fallback_source_ref_is_accepted(self):
        payload = {
            "candidates": [
                {
                    "name_hint": "Voorbeeld BV",
                    "website_hint": "https://example.nl/",
                    "official_domain_hint": "example.nl",
                    "language": "nl",
                    "public_business_emails": ["info@example.nl"],
                    "email_source_types": ["google_maps_targeted_fallback"],
                    "email_source_refs": ["https://maps.google.com/example"],
                    "verified_observation": "Voorbeeld dienstverlening in Nederland",
                    "verified_observation_source_url": "https://example.nl/",
                    "verified_observation_source_type": "official_site",
                    "contact_basis_status": "review_required",
                    "contact_discovery_status": "found_discovery_fallback",
                    "excluded_competitor": False,
                }
            ]
        }
        result = build_ready(payload)
        self.assertEqual(result["ready_for_copy_count"], 1)
        self.assertEqual(
            result["ready_for_copy"][0]["email_source"],
            "https://maps.google.com/example",
        )


if __name__ == "__main__":
    unittest.main()
