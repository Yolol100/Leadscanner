from __future__ import annotations

import unittest

from prospect_discovery import ParsedPage
from outreach_site_personalization import build_personalization


class OutreachSitePersonalizationTests(unittest.TestCase):
    def test_same_agent_gets_different_site_bound_copy(self):
        roofing = ParsedPage(
            title="Best Buy Metal Roofing | Metal Roofing Panels",
            links=[("https://roof.example/request-a-quote", "Request a Quote")],
        )
        solar = ParsedPage(
            title="Sun Example | Commercial Solar Installations",
            links=[("https://solar.example/free-estimate", "Free Estimate")],
        )
        first = build_personalization(
            roofing,
            company="Best Buy Metal Roofing",
            agent_type="quote_intake",
            language="en",
            evidence_url="https://roof.example/",
        )
        second = build_personalization(
            solar,
            company="Sun Example",
            agent_type="quote_intake",
            language="en",
            evidence_url="https://solar.example/",
        )
        self.assertEqual(first.anchor, "Metal Roofing Panels")
        self.assertEqual(second.anchor, "Commercial Solar Installations")
        self.assertNotEqual(first.observation, second.observation)
        self.assertNotEqual(first.value, second.value)
        self.assertIn(first.anchor, first.observation)
        self.assertIn(first.anchor, first.value)

    def test_all_public_site_agent_families_have_process_specific_value(self):
        cases = {
            "front_desk_sales": ParsedPage(
                title="Clinic One | Sports Physio",
                links=[("https://example.test/book", "Book a Sports Physio Assessment")],
            ),
            "quote_intake": ParsedPage(
                title="Roof One | Standing Seam Roofing",
                links=[("https://example.test/quote", "Request a Quote")],
            ),
            "commerce": ParsedPage(
                title="Northwind | Outdoor Lighting Collection",
                links=[("https://example.test/products/outdoor", "Outdoor Lighting")],
            ),
            "customer_support": ParsedPage(
                title="Acme | Shipping and Returns",
                links=[("https://example.test/help/returns", "Returns and Exchanges")],
            ),
            "review_concierge": ParsedPage(
                title="Bright Clean | End of Tenancy Cleaning",
                links=[("https://example.test/reviews", "Customer Reviews")],
            ),
        }
        for agent_type, page in cases.items():
            with self.subTest(agent_type=agent_type):
                result = build_personalization(
                    page,
                    company="Example Company",
                    agent_type=agent_type,
                    language="en",
                    evidence_url="https://example.test/",
                )
                self.assertTrue(result.anchor)
                self.assertIn(result.anchor, result.observation)
                self.assertIn(result.anchor, result.value)

    def test_generic_process_only_page_fails_closed(self):
        page = ParsedPage(
            title="Example Company | Home",
            links=[("https://example.test/quote", "Request a Quote")],
        )
        with self.assertRaisesRegex(ValueError, "specific"):
            build_personalization(
                page,
                company="Example Company",
                agent_type="quote_intake",
                language="en",
                evidence_url="https://example.test/",
            )

    def test_reactivation_requires_first_party_context_not_public_site(self):
        page = ParsedPage(
            title="Example Company | Customer Portal",
            links=[("https://example.test/customers", "Customer Portal")],
        )
        with self.assertRaisesRegex(ValueError, "first-party"):
            build_personalization(
                page,
                company="Example Company",
                agent_type="lead_reactivation",
                language="en",
                evidence_url="https://example.test/",
            )


if __name__ == "__main__":
    unittest.main()
