from __future__ import annotations

import unittest

from extract_public_contacts import (
    discover_contact_links,
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
        self.assertEqual(
            extract_emails(html),
            ["info@example.nl", "sales@example.nl"],
        )

    def test_contact_links_stay_on_official_domain(self):
        html = """
        <a href="/contact">Contact</a>
        <a href="https://example.nl/over-ons">Over ons</a>
        <a href="https://other.example/contact">Contact extern</a>
        """
        links = discover_contact_links(
            html,
            "https://example.nl/",
            "example.nl",
        )
        self.assertIn("https://example.nl/contact", links)
        self.assertIn("https://example.nl/over-ons", links)
        self.assertFalse(any("other.example" in item for item in links))

    def test_email_validation(self):
        self.assertTrue(valid_email("info@example.nl"))
        self.assertFalse(valid_email("no-reply@example.nl"))
        self.assertFalse(valid_email("bad-address"))


if __name__ == "__main__":
    unittest.main()
