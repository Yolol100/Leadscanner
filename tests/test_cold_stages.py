import unittest
from unittest.mock import patch

from cold_stages import (
    filter_discovery,
    research_candidate,
    research_candidates,
    verify_candidate,
    verify_candidates,
)


class FakeResponse:
    def __init__(self, url, body, *, status=200, headers=None):
        self.url = url
        self.status_code = status
        self.headers = headers or {"content-type": "text/html; charset=utf-8"}
        self.encoding = "utf-8"
        self._body = body.encode("utf-8")

    def iter_content(self, chunk_size=65536, decode_unicode=False):
        yield self._body

    def close(self):
        pass


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if not self.responses:
            raise AssertionError(f"unexpected request: {url}")
        return self.responses.pop(0)


class ColdStagesTests(unittest.TestCase):
    def test_filter_is_cheap_and_strips_discovery_contacts(self):
        payload = {
            "candidates": [
                {
                    "overture_id": "1",
                    "name_hint": "Acme Fietsen",
                    "category_hint": "bicycle store",
                    "website_hint": "https://acme.nl/",
                    "discovery_email_candidates": [{"email": "info@acme.nl"}],
                },
                {
                    "overture_id": "2",
                    "name_hint": "Fast Webdesign Bureau",
                    "category_hint": "digital agency",
                    "website_hint": "https://fastweb.nl/",
                },
                {"overture_id": "3", "name_hint": "Geen Site"},
                {
                    "overture_id": "4",
                    "name_hint": "Acme Dubbel",
                    "website_hint": "https://www.acme.nl/contact",
                },
            ]
        }
        result = filter_discovery(payload)
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["candidates"][0]["domain_hint"], "acme.nl")
        self.assertNotIn("discovery_email_candidates", result["candidates"][0])
        self.assertEqual(result["excluded_count"], 3)

    @patch("cold_stages.is_public_http_url", return_value=True)
    def test_verify_proves_identity_and_official_site_email(self, _safe):
        home = FakeResponse(
            "https://acmefietsen.nl/",
            """<html><head><title>Acme Fietsen</title></head><body>
            <p>Acme Fietsen verkoopt stadsfietsen en e-bikes vanuit Rotterdam.</p>
            <a href='/contact'>Contact</a><a href='/diensten'>Onze diensten</a>
            </body></html>""",
        )
        contact = FakeResponse(
            "https://acmefietsen.nl/contact",
            "<html><body><p>Neem voor vragen contact op met ons team.</p><a href='mailto:info@acmefietsen.nl'>Mail ons</a></body></html>",
        )
        session = FakeSession([home, contact])
        candidate = {
            "name_hint": "Acme Fietsen B.V.",
            "website_hint": "https://acmefietsen.nl/",
            "category_hint": "bicycle store",
        }
        result = verify_candidate(candidate, session_factory=lambda: session)
        self.assertEqual(result["identity_status"], "verified")
        self.assertEqual(result["public_business_email"], "info@acmefietsen.nl")
        self.assertEqual(result["contact_status"], "verified_official_site")
        self.assertTrue(result["ready_for_research"])
        self.assertEqual(session.calls, ["https://acmefietsen.nl/", "https://acmefietsen.nl/contact"])
        self.assertIn("https://acmefietsen.nl/diensten", result["research_links"])

    @patch("cold_stages.is_public_http_url", return_value=True)
    def test_verify_holds_when_identity_not_proven(self, _safe):
        home = FakeResponse(
            "https://unrelated.nl/",
            "<html><head><title>Ander Merk</title></head><body><p>Wij verkopen tuinmeubelen in Utrecht.</p></body></html>",
        )
        session = FakeSession([home])
        result = verify_candidate(
            {"name_hint": "Acme Fietsen", "website_hint": "https://unrelated.nl/"},
            session_factory=lambda: session,
        )
        self.assertEqual(result["identity_status"], "hold")
        self.assertEqual(result["contact_status"], "hold_identity_not_proven")
        self.assertFalse(result["ready_for_research"])

    @patch("cold_stages.is_public_http_url", return_value=True)
    def test_verify_rejects_third_party_footer_email(self, _safe):
        home = FakeResponse(
            "https://acmefietsen.nl/",
            """<html><head><title>Acme Fietsen</title></head><body>
            <p>Acme Fietsen verkoopt stadsfietsen en e-bikes vanuit Rotterdam.</p>
            <p>Website en online marketing door partner.</p>
            <a href='mailto:hello@webagency.nl'>Site partner</a>
            </body></html>""",
        )
        session = FakeSession([home])
        result = verify_candidate(
            {"name_hint": "Acme Fietsen", "website_hint": "https://acmefietsen.nl/"},
            session_factory=lambda: session,
        )
        self.assertEqual(result["identity_status"], "verified")
        self.assertFalse(result["excluded_competitor"])
        self.assertEqual(result["contact_status"], "hold_no_public_business_email")
        self.assertIsNone(result["public_business_email"])

    def test_verify_limit_is_hard_bounded(self):
        with self.assertRaisesRegex(ValueError, "verify_limit"):
            verify_candidates({"kept": [{}]}, limit=101)

    @patch("cold_stages.is_public_http_url", return_value=True)
    def test_research_reuses_homepage_and_fetches_max_two_details(self, _safe):
        detail1 = FakeResponse(
            "https://acmefietsen.nl/diensten",
            "<html><body><p>Onze werkplaats voert onderhoud uit aan stadsfietsen en elektrische fietsen.</p></body></html>",
        )
        detail2 = FakeResponse(
            "https://acmefietsen.nl/afspraak",
            "<html><body><p>Klanten kunnen online een werkplaatsafspraak aanvragen voor onderhoud of reparatie.</p></body></html>",
        )
        session = FakeSession([detail1, detail2])
        candidate = {
            "name_hint": "Acme Fietsen",
            "official_url": "https://acmefietsen.nl/",
            "official_domain": "acmefietsen.nl",
            "public_business_email": "info@acmefietsen.nl",
            "ready_for_research": True,
            "homepage_text_excerpt": "Acme Fietsen verkoopt stadsfietsen en elektrische fietsen vanuit de winkel in Rotterdam.",
            "research_links": [
                "https://acmefietsen.nl/diensten",
                "https://acmefietsen.nl/afspraak",
                "https://acmefietsen.nl/producten",
            ],
        }
        result = research_candidate(candidate, session_factory=lambda: session)
        self.assertEqual(result["research_status"], "ready")
        self.assertEqual(len(session.calls), 2)
        self.assertLessEqual(len(result["researched_urls"]), 3)
        self.assertTrue(any(item["page_type"] == "process" for item in result["evidence_candidates"]))

    def test_research_skips_not_ready_candidates_without_network(self):
        result = research_candidates(
            {"candidates": [{"name_hint": "Hold", "ready_for_research": False}]},
            limit=10,
            session_factory=lambda: (_ for _ in ()).throw(AssertionError("network should not run")),
        )
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["research_ready_count"], 0)


if __name__ == "__main__":
    unittest.main()
