from __future__ import annotations

import unittest
from unittest.mock import patch

from extract_public_contacts import (
    competitor_reason,
    detect_language,
    discover_contact_links,
    discover_contacts,
    extract_emails,
    email_fits_business_context,
    inspect_candidate,
    valid_email,
)


class FakeResponse:
    status_code = 200
    url = "https://example.nl/"
    encoding = "utf-8"
    headers = {"content-type": "text/html"}

    def iter_content(self, chunk_size=65536, decode_unicode=False):
        yield b'<html lang="nl"><body>Welkom bij ons bedrijf.</body></html>'

    def close(self):
        pass


class FakeSession:
    def get(self, *args, **kwargs):
        return FakeResponse()


class PublicContactDiscoveryTests(unittest.TestCase):
    def test_extracts_visible_or_mailto_emails_and_drops_placeholders(self):
        html = (
            '<input value="naam@voorbeeld.nl">'
            '<span>info@example.nl</span>'
            '<span>no-reply@example.nl</span>'
            '<a href="mailto:sales@example.nl">Mail</a>'
        )
        self.assertEqual(extract_emails(html), ["sales@example.nl", "info@example.nl"])

    def test_contact_links_stay_on_official_domain(self):
        html = '<a href="/contact">Contact</a><a href="https://other.example/contact">Extern</a>'
        links = discover_contact_links(html, "https://example.nl/", "example.nl")
        self.assertIn("https://example.nl/contact", links)
        self.assertFalse(any("other.example" in item for item in links))

    def test_email_validation(self):
        self.assertTrue(valid_email("info@example.nl"))
        self.assertFalse(valid_email("no-reply@example.nl"))
        self.assertFalse(valid_email("naam@voorbeeld.nl"))
        self.assertFalse(valid_email("bad-address"))

    def test_fallback_email_must_fit_business_context(self):
        self.assertTrue(email_fits_business_context("info@example.nl", "example.nl", "overture"))
        self.assertTrue(email_fits_business_context("bedrijf@gmail.com", "example.nl", "google_maps"))
        self.assertFalse(
            email_fits_business_context(
                "contact@aannemerrotterdam.commaandag",
                "aannemerrotterdam.com",
                "google_maps",
            )
        )

    def test_language_uses_visible_copy_to_override_stale_html_lang(self):
        self.assertEqual(detect_language('<html lang="nl"><body>Welkom</body></html>'), ("nl", "html_lang"))
        dutch = (
            '<html lang="en"><body>'
            'Wij helpen onze klanten met de website en het bedrijf. '
            'Onze diensten zijn voor klanten in Nederland en wij nemen graag contact op.'
            '</body></html>'
        )
        self.assertEqual(detect_language(dutch, default="en"), ("nl", "page_text"))

    def test_competitor_filters_individual_digital_provider(self):
        for label in ("Freelance webdesigner", "SEO specialist", "Social media manager", "WordPress specialist", "Automation consultant", "Hosting reseller"):
            self.assertIsNotNone(competitor_reason({"name_hint": label, "category_hint": ""}))

    def test_competitor_site_phrase_with_punctuation_is_detected(self):
        html = "<html><body>Wij zijn een digital agency, gespecialiseerd in websites.</body></html>"
        self.assertEqual(
            competitor_reason({"name_hint": "Voorbeeld", "category_hint": ""}, html),
            "official_site:digital agency",
        )

    def test_discovery_email_is_fallback_after_official_site_search(self):
        candidate = {
            "name_hint": "Example BV",
            "website_hint": "https://example.nl/",
            "category_hint": "bakery",
            "discovery_email_candidates": [{"email": "info@example.nl", "source": "overture"}],
            "overture_id": "ov-1",
        }
        with patch("extract_public_contacts.is_public_http_url", return_value=True):
            result = inspect_candidate(candidate, session_factory=FakeSession)
        self.assertEqual(result["public_business_emails"], ["info@example.nl"])
        self.assertEqual(result["email_source_types"], ["overture"])
        self.assertEqual(result["contact_basis_status"], "review_required")
        self.assertEqual(result["contact_discovery_status"], "found_discovery_fallback")

    def test_contact_discovery_is_bounded_to_100_candidates(self):
        with self.assertRaises(ValueError):
            discover_contacts({"candidates": [{} for _ in range(101)]})


if __name__ == "__main__":
    unittest.main()
