from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from hybrid_discovery import combine_candidates, read_google_maps_candidates


class HybridDiscoveryTests(unittest.TestCase):
    def test_cross_source_domain_deduplication_and_bounded_email_candidates(self):
        overture = {
            "candidates": [
                {
                    "overture_id": "ov-1",
                    "name_hint": "Example BV",
                    "category_hint": "web_design",
                    "website_hint": "https://www.example.nl/",
                    "longitude": 4.48,
                    "latitude": 51.92,
                    "discovery_email_candidates": [{"email": "overture@example.nl", "source": "overture"}],
                    "identity_status": "needs_leads_verification",
                }
            ]
        }
        maps = [
            {
                "google_maps_cid": "cid-1",
                "google_maps_place_id": "place-1",
                "maps_link_hint": "https://maps.google.com/example",
                "name_hint": "Example",
                "category_hint": "Web designer",
                "website_hint": "https://example.nl/contact",
                "longitude": 4.48,
                "latitude": 51.92,
                "discovery_sources": ["google_maps"],
                "identity_status": "needs_leads_verification",
            }
        ]

        result = combine_candidates(
            overture,
            maps,
            max_results=10,
            require_website=True,
        )

        self.assertEqual(result["candidate_count"], 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["discovery_sources"], ["google_maps", "overture"])
        self.assertEqual(candidate["overture_id"], "ov-1")
        self.assertEqual(candidate["google_maps_place_id"], "place-1")
        self.assertEqual(candidate["identity_status"], "needs_leads_verification")
        self.assertTrue(result["privacy_and_scope"]["email_candidates_emitted"])
        self.assertIn(
            {"email": "overture@example.nl", "source": "overture"},
            candidate["discovery_email_candidates"],
        )
        self.assertFalse(result["privacy_and_scope"]["phones_emitted"])
        self.assertFalse(result["privacy_and_scope"]["draftqueue_write"])
        self.assertFalse(result["privacy_and_scope"]["email_send"])

    def test_google_maps_reader_keeps_email_candidates_but_drops_raw_contact_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "link",
                        "title",
                        "category",
                        "website",
                        "phone",
                        "emails",
                        "longitude",
                        "latitude",
                        "cid",
                        "place_id",
                        "status",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "link": "https://maps.google.com/example",
                        "title": "Example",
                        "category": "Agency",
                        "website": "https://example.nl",
                        "phone": "+31101234567",
                        "emails": "sales@example.nl",
                        "longitude": "4.48",
                        "latitude": "51.92",
                        "cid": "cid-1",
                        "place_id": "place-1",
                        "status": "Open",
                    }
                )

            candidates, raw_rows = read_google_maps_candidates(path, require_website=True)
            self.assertEqual(raw_rows, 1)
            self.assertEqual(len(candidates), 1)
            self.assertNotIn("phone", candidates[0])
            self.assertNotIn("emails", candidates[0])
            self.assertEqual(
                candidates[0]["discovery_email_candidates"],
                [{"email": "sales@example.nl", "source": "google_maps"}],
            )
            self.assertEqual(candidates[0]["website_hint"], "https://example.nl")

    def test_transitive_identity_bridge_merges_existing_clusters(self):
        overture = {
            "candidates": [
                {
                    "overture_id": "ov-1",
                    "name_hint": "Example BV",
                    "website_hint": "https://example.nl",
                },
                {
                    "overture_id": "ov-2",
                    "name_hint": "Second record",
                    "website_hint": "https://second.nl",
                },
            ]
        }
        maps = [
            {
                "google_maps_place_id": "place-bridge",
                "name_hint": "Bridge",
                "website_hint": "https://second.nl",
                "discovery_sources": ["google_maps"],
                "identity_status": "needs_leads_verification",
            },
            {
                "overture_id": "ov-1",
                "google_maps_place_id": "place-bridge",
                "name_hint": "Bridge two",
                "website_hint": "https://example.nl",
                "discovery_sources": ["google_maps"],
                "identity_status": "needs_leads_verification",
            },
        ]
        result = combine_candidates(overture, maps, max_results=10, require_website=True)
        self.assertEqual(result["candidate_count"], 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["overture_id"], "ov-1")
        self.assertEqual(candidate["google_maps_place_id"], "place-bridge")

    def test_max_results_is_bounded_to_5000(self):
        with self.assertRaises(ValueError):
            combine_candidates(
                {"candidates": []},
                [],
                max_results=5001,
                require_website=False,
            )

    def test_name_only_candidate_is_not_used_for_cross_source_dedupe(self):
        overture = {
            "candidates": [
                {
                    "overture_id": "ov-1",
                    "name_hint": "Same Name",
                    "website_hint": None,
                }
            ]
        }
        maps = [
            {
                "google_maps_place_id": "place-1",
                "name_hint": "Same Name",
                "website_hint": None,
                "discovery_sources": ["google_maps"],
                "identity_status": "needs_leads_verification",
            }
        ]
        result = combine_candidates(
            overture,
            maps,
            max_results=10,
            require_website=False,
        )
        self.assertEqual(result["candidate_count"], 2)


if __name__ == "__main__":
    unittest.main()
