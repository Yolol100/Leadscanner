import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import prospect_discovery as discovery
import prospect_target_policy as policy


class ProspectTargetPolicyTests(unittest.TestCase):
    def source(self, *, country="US", exclude_terms=()):
        return discovery.SourceSpec(
            source_id="s1",
            source_type="seed_site",
            source_url="https://example.com/",
            country=country,
            exclude_terms=tuple(exclude_terms),
            approved=True,
            enabled=True,
        )

    def test_netherlands_is_excluded_by_default(self):
        for value in ("NL", "NLD", "Netherlands", "Nederland", "Netherlands (NL)"):
            filtered, reason = policy.apply_source_policy(self.source(country=value))
            self.assertIsNone(filtered)
            self.assertEqual(reason, "country_excluded")

    def test_usa_and_uk_are_retained(self):
        for value in ("US", "USA", "United States", "GB", "UK", "United Kingdom"):
            filtered, reason = policy.apply_source_policy(self.source(country=value))
            self.assertIsNotNone(filtered)
            self.assertEqual(reason, "")

    def test_agency_terms_are_merged_without_erasing_source_terms(self):
        filtered, _ = policy.apply_source_policy(self.source(exclude_terms=("casino",)))
        self.assertIn("casino", filtered.exclude_terms)
        self.assertIn("marketing agency", filtered.exclude_terms)
        self.assertIn("webdesignbureau", filtered.exclude_terms)
        self.assertIn("agence web", filtered.exclude_terms)

    def test_agency_filter_can_only_be_disabled_explicitly(self):
        source = self.source(exclude_terms=("casino",))
        filtered, _ = policy.apply_source_policy(source, exclude_agencies=False)
        self.assertEqual(filtered.exclude_terms, ("casino",))

    def test_policy_terms_reject_agency_but_keep_retailer(self):
        source, _ = policy.apply_source_policy(self.source())
        agency = "We are a digital marketing agency helping companies with web design."
        retailer = "Independent furniture shop with tables, chairs and online checkout."
        self.assertFalse(discovery.match_terms(agency, source.include_terms, source.exclude_terms)[0])
        self.assertTrue(discovery.match_terms(retailer, source.include_terms, source.exclude_terms)[0])

    def test_country_priority_keeps_stable_order(self):
        sources = [
            self.source(country="DE"),
            discovery.SourceSpec("s2", "seed_site", "https://uk.example/", "GB", approved=True),
            discovery.SourceSpec("s3", "seed_site", "https://us.example/", "US", approved=True),
            discovery.SourceSpec("s4", "seed_site", "https://fr.example/", "FR", approved=True),
        ]
        ordered = policy.prioritize_sources(sources, ("US", "GB", "DE", "FR"))
        self.assertEqual([item.source_id for item in ordered], ["s3", "s2", "s1", "s4"])


if __name__ == "__main__":
    unittest.main()
