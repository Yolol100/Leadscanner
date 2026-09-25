from __future__ import annotations

import unittest

from apply_google_maps_email_fallback import apply_fallback


class TargetedGoogleMapsFallbackTests(unittest.TestCase):
    def test_applies_only_matching_business_email(self):
        payload = {
            "contact_found_count": 0,
            "candidates": [{
                "google_maps_place_id": "place-1",
                "google_maps_cid": "cid-1",
                "maps_link_hint": "https://maps.google.com/example",
                "website_hint": "https://example.nl",
                "official_domain_hint": "example.nl",
                "public_business_emails": [],
                "email_source_types": [],
                "email_source_refs": [],
                "excluded_competitor": False,
                "contact_basis_status": "unverified",
            }],
            "safety": {},
        }
        rows = {
            "place:place-1": {
                "place_id": "place-1",
                "cid": "cid-1",
                "website": "https://example.nl",
                "link": "https://maps.google.com/example",
                "emails": "info@example.nl",
            }
        }
        result = apply_fallback(payload, rows)
        row = result["candidates"][0]
        self.assertEqual(row["public_business_emails"], ["info@example.nl"])
        self.assertEqual(row["email_source_types"], ["google_maps_targeted_fallback"])
        self.assertEqual(row["contact_basis_status"], "review_required")
        self.assertEqual(result["contact_found_count"], 1)

    def test_rejects_cross_domain_fallback(self):
        payload = {
            "contact_found_count": 0,
            "candidates": [{
                "google_maps_place_id": "place-1",
                "website_hint": "https://example.nl",
                "official_domain_hint": "example.nl",
                "public_business_emails": [],
                "excluded_competitor": False,
            }],
            "safety": {},
        }
        rows = {
            "place:place-1": {
                "place_id": "place-1",
                "website": "https://other.nl",
                "emails": "info@other.nl",
            }
        }
        result = apply_fallback(payload, rows)
        self.assertEqual(result["candidates"][0]["public_business_emails"], [])
        self.assertEqual(result["contact_found_count"], 0)


if __name__ == "__main__":
    unittest.main()
