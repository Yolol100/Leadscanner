"""No-network regression for cross-border lead discovery."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from overture_discovery import read_candidates
from target_scope import is_foreign_country_hint
from verified_fill import fill_verified
from verify_official_lead import verify_official_site


class DutchCountryGateTests(unittest.TestCase):
    def test_known_foreign_country_codes_and_known_dutch_aliases(self):
        for code in ("BE", "DE", "FR", "BE ", "ZZ"):
            self.assertTrue(is_foreign_country_hint(code))
        for code in ("NL", "nl", "NLD", "Nederland", "Netherlands", "", None):
            self.assertFalse(is_foreign_country_hint(code))

    def test_overture_filters_cross_border_source_before_candidate_selection(self):
        features = []
        for code in ("NL", "BE", "DE", ""):
            features.append({
                "type": "Feature",
                "id": "fictional-" + (code or "unknown"),
                "properties": {
                    "names": {"primary": "Test Restaurant " + (code or "Unknown")},
                    "basic_category": "restaurant",
                    "operating_status": "open",
                    "websites": ["https://example.nl/"],
                    "addresses": ([{"country": code}] if code else []),
                },
                "geometry": {"type": "Point", "coordinates": [4.48, 51.92]},
            })
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "places.geojsonseq"
            path.write_text("".join("\x1e" + json.dumps(x) + "\n"
                                    for x in features), encoding="utf-8")
            rows = read_candidates(path, keywords=["vakbedrijven"],
                                   max_results=10, require_website=True)
        self.assertEqual({r["country_hint"] for r in rows}, {"NL", ""})

    def test_direct_official_verifier_rejects_foreign_before_network(self):
        client = Mock()
        reasons = []
        row = {"name_hint": "Test Restaurant", "website_hint": "https://example.nl/",
               "category_hint": "restaurant", "country_hint": "DE"}
        self.assertIsNone(verify_official_site(row, session=client,
                          diagnostic=reasons.append))
        self.assertEqual(reasons, ["foreign_country_hint"])
        client.get.assert_not_called()

    def test_fill_guard_rejects_foreign_before_verification(self):
        rows = [
            {"overture_id": "fake-be", "name_hint": "Test Restaurant BE",
             "website_hint": "https://example-be.nl/", "category_hint": "restaurant",
             "country_hint": "BE"},
            {"overture_id": "fake-nl", "name_hint": "Test Restaurant NL",
             "website_hint": "https://example-nl.nl/", "category_hint": "restaurant",
             "country_hint": "NL"}
        ]
        seen = []
        def discovery(**kwargs):
            return {"candidates": rows}
        def verify(row):
            seen.append(row["overture_id"])
            return {
                "company": row["name_hint"], "website": row["website_hint"],
                "email": "info@example-nl.nl", "source_url": row["website_hint"],
                "cluster": 3, "branche_meervoud": "restaurants",
                "greeting": "Goedendag,",
                "status": "verified_website_and_email"
            }
        result = fill_verified("Rotterdam", ["vakbedrijven"], 25, target=1,
                               discoverer=discovery, verifier=verify,
                               load_registry=lambda: [], max_site_checks=20)
        self.assertEqual(seen, ["fake-nl"])
        self.assertEqual(len(result["approved"]), 1)
        self.assertEqual(result["counts"]["unverified"], 1)


if __name__ == "__main__":
    unittest.main()
