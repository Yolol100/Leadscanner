from __future__ import annotations

import unittest

from prospect_candidate_sanitizer import sanitize_rows
from prospect_source_semantics import obvious_non_target, source_semantic_target_check


class ProspectSourceSemanticTests(unittest.TestCase):
    def test_institutional_navigation_candidates_are_blocked(self):
        for company, website in (
            ("Greer Chamber Job Board", "https://jobs.example.com/"),
            ("Upstate Chamber Coalition", "https://chamber.example.org/"),
            ("City of Greer", "https://city.example.org/"),
            ("[[Organization]]", "https://directory.example.org/"),
            ("Home", "https://manufacturer.example.com/"),
            ("Greenwood Village Official Website", "https://greenwood.example.com/"),
        ):
            self.assertTrue(obvious_non_target(company, website), company)

    def test_directory_provider_subdomain_is_not_a_prospect(self):
        reason = obvious_non_target(
            "Inloggen WebwinkelKeur",
            "https://dashboard.webwinkelkeur.nl/",
            "https://www.webwinkelkeur.nl/webshops/overview/city/Winkel/region%3Anl",
        )
        self.assertIn("directory provider", reason)

    def test_trustmark_review_provider_identity_is_blocked(self):
        self.assertTrue(
            obvious_non_target(
                "Webshop Trustmark & Webshop Reviews: Starting from €6 per month",
                "https://www.valuedshops.com/",
            )
        )

    def test_manufacturing_directory_requires_official_site_category_evidence(self):
        allowed, reason = source_semantic_target_check(
            source_id="us-greer-manufacturers",
            source_url="https://directory.example.com/Manufacturers",
            company="Example Community Event",
            website="https://event.example.com/",
            html="<html><head><title>Community Arts Festival</title></head><body><h1>Food and arts festival</h1></body></html>",
        )
        self.assertFalse(allowed)
        self.assertIn("lacks manufacturing", reason)

    def test_real_manufacturer_passes_manufacturing_source_gate(self):
        allowed, reason = source_semantic_target_check(
            source_id="us-greer-manufacturers",
            source_url="https://directory.example.com/Manufacturers",
            company="Example Components",
            website="https://components.example.com/",
            html="<html><head><title>Example Components</title></head><body><h1>Industrial manufacturer</h1><p>Precision manufacturing and fabrication.</p></body></html>",
        )
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_sanitizer_rejects_stale_directory_noise_without_network(self):
        rows = [
            {
                "candidate_id": "city-1", "company": "City of Greer", "website": "https://city.example.org/",
                "source_id": "us-greer-manufacturers", "source_url": "https://directory.example.com/Manufacturers",
                "status": "discovered", "reason": "old",
            }
        ]
        def should_not_fetch(_url):
            raise AssertionError("obvious institutional candidate should be rejected before fetch")
        checked, rejected, deferred = sanitize_rows(rows, fetch=should_not_fetch)
        self.assertEqual((checked, rejected, deferred), (1, 1, 0))
        self.assertEqual(rows[0]["status"], "rejected")
        self.assertIn("source_semantic_target_policy", rows[0]["reason"])


if __name__ == "__main__":
    unittest.main()
