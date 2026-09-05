import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import prospect_discovery as discovery
import prospect_target_policy as policy


class ProspectTargetPolicyTests(unittest.TestCase):
    def source(self, *, country="US", exclude_terms=(), source_url="https://example.com/"):
        return discovery.SourceSpec(
            source_id="s1",
            source_type="seed_site",
            source_url=source_url,
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

    def test_short_country_codes_do_not_match_inside_unrelated_names(self):
        self.assertEqual(policy.canonical_country("Zimbabwe"), "ZIMBABWE")
        self.assertEqual(policy.canonical_country("Austria"), "AT")

    def test_webactueel_and_subdomains_are_self_excluded(self):
        self.assertTrue(policy.is_excluded_domain("https://webactueel.nl/"))
        self.assertTrue(policy.is_excluded_domain("https://shop.webactueel.nl/example"))
        self.assertFalse(policy.is_excluded_domain("https://example.com/"))
        filtered, reason = policy.apply_source_policy(
            self.source(source_url="https://www.webactueel.nl/leads")
        )
        self.assertIsNone(filtered)
        self.assertEqual(reason, "self_domain_excluded")

    def test_agency_terms_are_merged_without_erasing_source_terms(self):
        filtered, _ = policy.apply_source_policy(self.source(exclude_terms=("casino",)))
        self.assertIn("casino", filtered.exclude_terms)
        self.assertIn("marketing agency", filtered.exclude_terms)
        self.assertIn("webdesignbureau", filtered.exclude_terms)
        self.assertIn("agence web", filtered.exclude_terms)
        self.assertIn("app development agency", filtered.exclude_terms)
        self.assertIn("software development agency", filtered.exclude_terms)
        self.assertIn("ux agency", filtered.exclude_terms)

    def test_agency_filter_can_only_be_disabled_explicitly(self):
        source = self.source(exclude_terms=("casino",))
        filtered, _ = policy.apply_source_policy(source, exclude_agencies=False)
        self.assertEqual(filtered.exclude_terms, ("casino",))

    def test_policy_terms_reject_agencies_but_keep_product_company(self):
        source, _ = policy.apply_source_policy(self.source())
        agency_examples = (
            "We are a digital marketing agency helping companies with web design.",
            "Mobile app development agency for startups and established brands.",
            "Software development agency building custom business platforms.",
            "UX agency specialising in conversion-focused digital products.",
        )
        retailer = "Independent furniture shop with tables, chairs and online checkout."
        software_product = "Cloud inventory software for independent furniture retailers."
        for agency in agency_examples:
            self.assertFalse(discovery.match_terms(agency, source.include_terms, source.exclude_terms)[0])
        self.assertTrue(discovery.match_terms(retailer, source.include_terms, source.exclude_terms)[0])
        self.assertTrue(discovery.match_terms(software_product, source.include_terms, source.exclude_terms)[0])

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
