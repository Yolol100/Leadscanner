from __future__ import annotations

import unittest

from filter_discovery_candidates import filter_discovery_candidates


class FilterDiscoveryCandidatesTests(unittest.TestCase):
    def test_filters_competitor_hints_without_verification(self):
        payload = {
            "source_counts": {
                "overture_candidates": 2,
                "google_maps_candidates": 2,
            },
            "candidate_count": 3,
            "dropped_undedupeable_count": 0,
            "candidates": [
                {
                    "overture_id": "ov-1",
                    "name_hint": "Voorbeeld SEO specialist",
                    "category_hint": "Consultant",
                    "website_hint": "https://seo.example",
                    "discovery_sources": ["overture"],
                    "discovery_email_candidates": [
                        {"email": "info@seo.example", "source": "overture"}
                    ],
                },
                {
                    "google_maps_place_id": "place-1",
                    "name_hint": "Bakkerij Voorbeeld",
                    "category_hint": "Bakery",
                    "website_hint": "https://bakkerij.example",
                    "discovery_sources": ["google_maps"],
                    "discovery_email_candidates": [
                        {"email": "info@bakkerij.example", "source": "google_maps"}
                    ],
                },
                {
                    "google_maps_place_id": "place-2",
                    "name_hint": "Fysiotherapie Voorbeeld",
                    "category_hint": "Physiotherapist",
                    "website_hint": "https://fysio.example",
                    "discovery_sources": ["google_maps"],
                },
            ],
        }

        result = filter_discovery_candidates(payload)

        self.assertEqual(result["source_candidate_count"], 4)
        self.assertEqual(result["deduplicated_candidate_count"], 3)
        self.assertEqual(result["duplicate_count"], 1)
        self.assertEqual(result["competitor_excluded_count"], 1)
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["competitor_filter_scope"], "discovery_hints_only")
        self.assertFalse(result["safety"]["verification_performed"])
        self.assertFalse(result["safety"]["contact_basis_evaluated"])
        self.assertFalse(result["safety"]["copy_created"])
        self.assertFalse(result["safety"]["draft_created"])
        self.assertFalse(result["safety"]["email_send"])

        for item in result["candidates"] + result["excluded_competitors"]:
            self.assertNotIn("discovery_email_candidates", item)
            self.assertEqual(item["identity_status"], "needs_leads_verification")

    def test_dropped_undedupeable_is_not_counted_as_duplicate(self):
        result = filter_discovery_candidates(
            {
                "source_counts": {
                    "overture_candidates": 3,
                    "google_maps_candidates": 3,
                },
                "candidate_count": 4,
                "dropped_undedupeable_count": 1,
                "candidates": [
                    {
                        "name_hint": f"Bedrijf {index}",
                        "category_hint": "Bakery",
                        "website_hint": f"https://bedrijf-{index}.example",
                    }
                    for index in range(4)
                ],
            }
        )
        self.assertEqual(result["duplicate_count"], 1)

    def test_invalid_candidates_shape_fails_closed(self):
        with self.assertRaises(ValueError):
            filter_discovery_candidates({"candidates": "not-a-list"})


if __name__ == "__main__":
    unittest.main()
