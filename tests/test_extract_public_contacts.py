from __future__ import annotations

import unittest

from extract_public_contacts import (
    competitor_reason,
    detect_language,
    discover_contact_links,
    discover_contacts,
    extract_emails,
    valid_email,
)


class PublicContactDiscoveryTests(unittest.TestCase):
    def test_extracts_public_emails_and_drops_noreply(self):
        html = """
        <html><body>
        <a href="mailto:info@example.nl">info@example.nl</a>
        <span>sales@example.nl</span>
        <span>no-reply@example.nl</span>
        </body></html>
        """
        self.assertEqual(extract_emails(html), ["info@example.nl", "sales@example.nl"])

    def test_contact_links_stay_on_official_domain(self):
        html = """
        <a href="/contact">Contact</a>
        <a href="https://example.nl/over-ons">Over ons</a>
        <a href="https://other.example/contact">Contact extern</a>
        """
        links = discover_contact_links(html, "https://example.nl/", "example.nl")
        self.assertIn("https://example.nl/contact", links)
        self.assertIn("https://example.nl/over-ons", links)
        self.assertFalse(any("other.example" in item for item in links))

    def test_email_validation(self):
        self.assertTrue(valid_email("info@example.nl"))
        self.assertFalse(valid_email("no-reply@example.nl"))
        self.assertFalse(valid_email("bad-address"))

    def test_language_uses_html_lang_first(self):
        self.assertEqual(detect_language('<html lang="nl"><body>Welcome</body></html>'), ("nl", "html_lang"))
        self.assertEqual(detect_language('<html lang="en-US"><body>Welkom</body></html>'), ("en", "html_lang"))

    def test_language_falls_back_to_visible_text(self):
        html = "<html><body>Wij helpen onze klanten met diensten voor het bedrijf en de organisatie.</body></html>"
        self.assertEqual(detect_language(html, default="en"), ("nl", "page_text"))

    def test_competitor_is_excluded_from_hint(self):
        candidate = {"name_hint": "Sterk Marketingbureau", "category_hint": "Marketing agency"}
        self.assertTrue(competitor_reason(candidate).startswith("discovery_hint:"))

    def test_competitor_is_excluded_from_official_site_services(self):
        candidate = {"name_hint": "Example BV", "category_hint": "Consulting"}
        html = "<html><body>Wij bieden webdesign, SEO specialist diensten en online marketing.</body></html>"
        self.assertEqual(competitor_reason(candidate, html), "official_site:multiple_overlapping_services")

    def test_contact_discovery_is_bounded_to_100_candidates(self):
        with self.assertRaises(ValueError):
            discover_contacts({"candidates": [{} for _ in range(101)]})


if __name__ == "__main__":
    unittest.main()
