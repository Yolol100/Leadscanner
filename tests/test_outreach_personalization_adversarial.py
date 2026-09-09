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


if __name__ == "__main__":
    unittest.main()
