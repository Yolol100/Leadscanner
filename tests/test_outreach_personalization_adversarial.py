from __future__ import annotations

import unittest

from prospect_discovery import ParsedPage
from outreach_site_personalization import build_personalization


class OutreachPersonalizationAdversarialTests(unittest.TestCase):
    def test_generic_process_does_not_bind_unrelated_same_site_context(self):
        cases = {
            "front_desk_sales": ("Book Now", "/book"),
            "quote_intake": ("Get a Quote", "/quote"),
            "commerce": ("Shop", "/shop"),
            "customer_support": ("FAQ", "/faq"),
            "review_concierge": ("Reviews", "/reviews"),
        }
        for agent_type, (process_label, process_path) in cases.items():
            with self.subTest(agent_type=agent_type):
                page = ParsedPage(
                    title="Example Company | Home",
                    links=[
                        (f"https://example.test{process_path}", process_label),
                        ("https://example.test/company/leadership-team", "Leadership Team"),
                    ],
                )
                with self.assertRaisesRegex(ValueError, "specific"):
                    build_personalization(
                        page,
                        company="Example Company",
                        agent_type=agent_type,
                        language="en",
                        evidence_url="https://example.test/",
                    )

    def test_specific_title_cannot_replace_missing_agent_process_route(self):
        for agent_type in (
            "front_desk_sales",
            "quote_intake",
            "commerce",
            "customer_support",
            "review_concierge",
        ):
            with self.subTest(agent_type=agent_type):
                page = ParsedPage(
                    title="Example Company | Premium Roofing Specialists",
                    links=[],
                )
                with self.assertRaisesRegex(ValueError, "specific"):
                    build_personalization(
                        page,
                        company="Example Company",
                        agent_type=agent_type,
                        language="en",
                        evidence_url="https://example.test/",
                    )

    def test_each_public_agent_varies_when_real_site_context_varies(self):
        cases = {
            "front_desk_sales": (
                ParsedPage(
                    title="Clinic One | Physiotherapy",
                    links=[
                        ("https://one.test/book", "Book Now"),
                        ("https://one.test/treatments/sports-physio", "Sports Physiotherapy"),
                    ],
                ),
                ParsedPage(
                    title="Clinic Two | Dental Care",
                    links=[
                        ("https://two.test/book", "Book Now"),
                        ("https://two.test/treatments/dental-implants", "Dental Implants"),
                    ],
                ),
            ),
            "quote_intake": (
                ParsedPage(
                    title="Roof One | Metal Roofing",
                    links=[
                        ("https://one.test/quote", "Get a Quote"),
                        ("https://one.test/through-fastened/apex-panel", "Apex Panel"),
                    ],
                ),
                ParsedPage(
                    title="Roof Two | Metal Roofing",
                    links=[
                        ("https://two.test/quote", "Get a Quote"),
                        ("https://two.test/standing-seam/snap-seam", "Snap Seam"),
                    ],
                ),
            ),
            "commerce": (
                ParsedPage(
                    title="Shop One | Home Lighting",
                    links=[
                        ("https://one.test/shop", "Shop"),
                        ("https://one.test/collections/outdoor-lighting", "Outdoor Lighting"),
                    ],
                ),
                ParsedPage(
                    title="Shop Two | Kitchen Fixtures",
                    links=[
                        ("https://two.test/shop", "Shop"),
                        ("https://two.test/collections/kitchen-faucets", "Kitchen Faucets"),
                    ],
                ),
            ),
            "customer_support": (
                ParsedPage(
                    title="Store One | Customer Help",
                    links=[
                        ("https://one.test/faq", "FAQ"),
                        ("https://one.test/help/returns", "Returns and Exchanges"),
                    ],
                ),
                ParsedPage(
                    title="Store Two | Customer Help",
                    links=[
                        ("https://two.test/faq", "FAQ"),
                        ("https://two.test/help/shipping", "Shipping Questions"),
                    ],
                ),
            ),
            "review_concierge": (
                ParsedPage(
                    title="Service One | Cleaning",
                    links=[
                        ("https://one.test/reviews", "Reviews"),
                        ("https://one.test/customer-stories", "Customer Stories"),
                    ],
                ),
                ParsedPage(
                    title="Service Two | Renovation",
                    links=[
                        ("https://two.test/reviews", "Reviews"),
                        ("https://two.test/testimonials", "Client Testimonials"),
                    ],
                ),
            ),
        }
        for agent_type, (first_page, second_page) in cases.items():
            with self.subTest(agent_type=agent_type):
                first = build_personalization(
                    first_page,
                    company="First Company",
                    agent_type=agent_type,
                    language="en",
                    evidence_url="https://one.test/",
                )
                second = build_personalization(
                    second_page,
                    company="Second Company",
                    agent_type=agent_type,
                    language="en",
                    evidence_url="https://two.test/",
                )
                self.assertNotEqual(first.anchor, second.anchor)
                self.assertNotEqual(first.observation, second.observation)
                self.assertNotEqual(first.value, second.value)
                self.assertIn(first.anchor, first.observation)
                self.assertIn(first.anchor, first.value)

    def test_reactivation_stays_first_party_only(self):
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
