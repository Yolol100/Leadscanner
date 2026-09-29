from __future__ import annotations

import unittest
from unittest.mock import patch

from extract_public_contacts import (
    competitor_reason,
    detect_language,
    discover_contact_links,
    discover_contacts,
    extract_emails,
    extract_verified_observation,
    email_business_priority,
    email_fits_business_context,
    fetch_html,
    inspect_candidate,
    valid_email,
)


class FakeResponse:
    status_code = 200
    url = "https://example.nl/"
    encoding = "utf-8"
    headers = {"content-type": "text/html"}

    def iter_content(self, chunk_size=65536, decode_unicode=False):
        yield b'<html lang="nl"><body><h1>Ambachtelijke bakkerij voor Den Haag</h1>Welkom bij ons bedrijf.</body></html>'

    def close(self):
        pass


class FakeSession:
    def get(self, *args, **kwargs):
        return FakeResponse()


class PublicContactDiscoveryTests(unittest.TestCase):
    def test_extracts_verified_observation_from_official_page(self):
        html = "<html><head><title>Voorbeeld</title></head><body><h1>Ambachtelijke bakkerij voor Den Haag</h1></body></html>"
        self.assertEqual(
            extract_verified_observation(html),
            "Ambachtelijke bakkerij voor Den Haag",
        )

    def test_extracts_visible_or_mailto_emails_and_drops_placeholders(self):
        html = (
            '<input value="naam@voorbeeld.nl">'
            '<span>info@example.nl</span>'
            '<span>no-reply@example.nl</span>'
            '<a href="mailto:sales@example.nl">Mail</a>'
        )
        self.assertEqual(extract_emails(html), ["sales@example.nl", "info@example.nl"])

    def test_extract_emails_drops_unsuitable_outreach_roles_when_general_contact_exists(self):
        html = (
            '<a href="mailto:work@starbucks.nl">Jobs</a>'
            '<span>customercare@starbucks.nl</span>'
            '<span>press@starbucks.com</span>'
        )
        self.assertEqual(extract_emails(html), ["customercare@starbucks.nl"])

    def test_contact_links_stay_on_official_domain(self):
        html = '<a href="/contact">Contact</a><a href="https://other.example/contact">Extern</a>'
        links = discover_contact_links(html, "https://example.nl/", "example.nl")
        self.assertIn("https://example.nl/contact", links)
        self.assertFalse(any("other.example" in item for item in links))

    def test_email_validation(self):
        self.assertTrue(valid_email("info@example.nl"))
        self.assertFalse(valid_email("no-reply@example.nl"))
        self.assertFalse(valid_email("naam@voorbeeld.nl"))
        self.assertFalse(valid_email("dd0a55ccb8124b9c9d938e3acf41f8aa@sentry.wixpress.com"))
        self.assertFalse(valid_email("88170cb0c9d64f94b5821ca7fd2d55a4@sentry-next.wixpress.com"))
        self.assertFalse(valid_email("b357dce2cda744d5a1263db46c56a6f6@o478484.ingest.sentry.io"))
        self.assertFalse(valid_email("info@mysite.com"))
        self.assertFalse(valid_email("press@example.nl"))
        self.assertFalse(valid_email("press-emea@example.nl"))
        self.assertFalse(valid_email("hr@example.nl"))
        self.assertFalse(valid_email("pers@example.nl"))
        self.assertFalse(valid_email("sollicitatie@example.nl"))
        self.assertFalse(valid_email("work@example.nl"))
        self.assertFalse(valid_email("investorrelations@example.nl"))
        self.assertTrue(valid_email("customercare@example.nl"))
        self.assertFalse(valid_email("bad-address"))

    def test_email_business_priority_keeps_related_local_domains_and_demotes_unrelated_provider_domains(self):
        self.assertEqual(
            email_business_priority(
                "reserveren@daalderamsterdam.nl",
                "daalderamsterdam.nl",
                "Restaurant Daalder",
            ),
            0,
        )
        self.assertEqual(
            email_business_priority(
                "info@brandocean.nl",
                "daalderamsterdam.nl",
                "Restaurant Daalder",
            ),
            2,
        )
        self.assertEqual(
            email_business_priority(
                "info@intersportroden.nl",
                "intersport.nl",
                "Intersport Superstore Roden",
            ),
            0,
        )

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
        self.assertEqual(result["verified_observation"], "Ambachtelijke bakkerij voor Den Haag")
        self.assertEqual(result["verified_observation_source_type"], "official_site")
        self.assertEqual(result["verified_observation_source_url"], "https://example.nl/")

    def test_official_site_email_must_fit_business_context(self):
        self.assertFalse(
            email_fits_business_context(
                "credit@webagency.nl",
                "prospect.nl",
                "official_site",
                "Prospect BV",
            )
        )
        self.assertTrue(
            email_fits_business_context(
                "info@intersportroden.nl",
                "intersport.nl",
                "official_site",
                "Intersport Superstore Roden",
            )
        )

    def test_official_site_provider_credit_is_not_selected_as_prospect_contact(self):
        class ProviderResponse:
            status_code = 200
            url = "https://prospect.nl/"
            encoding = "utf-8"
            headers = {"content-type": "text/html"}

            def iter_content(self, chunk_size=65536, decode_unicode=False):
                yield (
                    b'<html lang="nl"><body><h1>Prospect zakelijke dienstverlening</h1>'
                    b'<a href="mailto:credit@webagency.nl">Website partner</a></body></html>'
                )

            def close(self):
                pass

        class ProviderSession:
            def get(self, *args, **kwargs):
                self.allow_redirects = kwargs.get("allow_redirects")
                return ProviderResponse()

        session = ProviderSession()
        candidate = {
            "name_hint": "Prospect BV",
            "website_hint": "https://prospect.nl/",
            "category_hint": "zakelijke dienstverlening",
        }
        with patch("extract_public_contacts.is_public_http_url", return_value=True):
            result = inspect_candidate(candidate, session_factory=lambda: session)
        self.assertEqual(result["public_business_emails"], [])
        self.assertEqual(result["contact_basis_status"], "unverified")
        self.assertFalse(session.allow_redirects)

    def test_private_redirect_target_is_rejected_before_second_request(self):
        class RedirectResponse:
            status_code = 302
            url = "https://example.nl/"
            encoding = "utf-8"
            headers = {"content-type": "text/html", "location": "http://127.0.0.1/admin"}

            def close(self):
                pass

        class RedirectSession:
            def __init__(self):
                self.calls = []

            def get(self, url, **kwargs):
                self.calls.append((url, kwargs.get("allow_redirects")))
                return RedirectResponse()

        session = RedirectSession()
        with patch(
            "extract_public_contacts.is_public_http_url",
            side_effect=lambda value: "127.0.0.1" not in str(value),
        ):
            body, final_url, status = fetch_html(session, "https://example.nl/")
        self.assertIsNone(body)
        self.assertEqual(final_url, "http://127.0.0.1/admin")
        self.assertEqual(status, 302)
        self.assertEqual(session.calls, [("https://example.nl/", False)])

    def test_same_domain_redirect_is_followed_manually(self):
        class RedirectResponse:
            encoding = "utf-8"

            def __init__(self, status_code, url, headers, body=b""):
                self.status_code = status_code
                self.url = url
                self.headers = headers
                self.body = body

            def iter_content(self, chunk_size=65536, decode_unicode=False):
                if self.body:
                    yield self.body

            def close(self):
                pass

        class RedirectSession:
            def __init__(self):
                self.calls = []
                self.responses = [
                    RedirectResponse(302, "https://example.nl/", {"location": "/contact"}),
                    RedirectResponse(
                        200,
                        "https://example.nl/contact",
                        {"content-type": "text/html"},
                        b"<html><body>Contact</body></html>",
                    ),
                ]

            def get(self, url, **kwargs):
                self.calls.append((url, kwargs.get("allow_redirects")))
                return self.responses.pop(0)

        session = RedirectSession()
        with patch("extract_public_contacts.is_public_http_url", return_value=True):
            body, final_url, status = fetch_html(session, "https://example.nl/")
        self.assertEqual(body, "<html><body>Contact</body></html>")
        self.assertEqual(final_url, "https://example.nl/contact")
        self.assertEqual(status, 200)
        self.assertEqual(
            session.calls,
            [("https://example.nl/", False), ("https://example.nl/contact", False)],
        )

    def test_contact_discovery_is_bounded_to_100_candidates(self):
        with self.assertRaises(ValueError):
            discover_contacts({"candidates": [{} for _ in range(101)]})


if __name__ == "__main__":
    unittest.main()
