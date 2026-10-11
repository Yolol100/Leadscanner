"""Research-first owner contact discovery, published evidence and safety gates."""
import unittest
from unittest.mock import patch

from cold_stages import (
    parse_html, research_candidate, suppress_previously_used_contact_emails, verify_candidate,
)
from first_party_contacts import preferred_contact_links, select_site_contact


def page(path, html):
    return {
        "source_url": "https://acmefietsen.nl" + path,
        "parsed": parse_html(html),
    }


class Response:
    def __init__(self, url, html):
        self.url = url
        self.status_code = 200
        self.headers = {"content-type": "text/html"}
        self.encoding = "utf-8"
        self.content = html.encode("utf-8")

    def iter_content(self, chunk_size=65536, decode_unicode=False):
        yield self.content

    def close(self):
        pass


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        if not self.responses:
            raise AssertionError("unexpected request")
        return self.responses.pop(0)


class FirstPartyContactsTests(unittest.TestCase):
    def test_owner_email_on_about_beats_info_and_even_uses_public_provider(self):
        pages = [
            page("/", "<title>Acme Fietsen</title><a href='mailto:info@acmefietsen.nl'>Contact</a>"),
            page("/over-ons", """
                <h2>Jan Jansen</h2><p>Eigenaar</p>
                <a href="mailto:jan.jansen@gmail.com">Mail Jan</a>
            """),
        ]
        contact = select_site_contact(pages, "acmefietsen.nl")
        self.assertEqual(contact["contact_status"], "verified_official_site")
        self.assertEqual(contact["public_business_email"], "jan.jansen@gmail.com")
        self.assertEqual(contact["contact_person_name"], "Jan Jansen")
        self.assertEqual(contact["contact_role"], "named_owner")
        self.assertEqual(contact["email_source_url"], "https://acmefietsen.nl/over-ons")

    def test_owner_found_on_about_and_personal_email_on_contact(self):
        contact = select_site_contact([
            page("/over-ons", "<p>Oprichter: Jan van Dijk</p>"),
            page("/contact", "<p>Stuur ons team een bericht.</p><a href='mailto:jan@acmefietsen.nl'>E-mail</a>"),
            page("/", "<a href='mailto:info@acmefietsen.nl'>Info</a>"),
        ], "acmefietsen.nl")
        self.assertEqual(contact["public_business_email"], "jan@acmefietsen.nl")
        self.assertEqual(contact["contact_person_name"], "Jan van Dijk")
        self.assertEqual(contact["contact_role"], "named_owner")

    def test_named_team_member_before_generic(self):
        contact = select_site_contact([
            page("/", "<p>Mail ons via info@acmefietsen.nl voor vragen.</p>"),
            page("/team", "<p>Ons team</p><h3>Lisa de Vries</h3><p>Monteur</p><a href='mailto:lisa@acmefietsen.nl'>Mail Lisa</a>"),
        ], "acmefietsen.nl")
        self.assertEqual(contact["public_business_email"], "lisa@acmefietsen.nl")
        self.assertEqual(contact["contact_person_name"], "Lisa de Vries")
        self.assertEqual(contact["contact_role"], "named_person")

    def test_generic_mailbox_used_when_no_personal_address_is_published(self):
        contact = select_site_contact([
            page("/over-ons", "<h2>Jan Jansen</h2><p>Eigenaar</p>"),
            page("/contact", "<p>Neem gerust contact met ons op.</p><a href='mailto:contact@acmefietsen.nl'>Contact</a>"),
        ], "acmefietsen.nl")
        self.assertEqual(contact["public_business_email"], "contact@acmefietsen.nl")
        self.assertEqual(contact["contact_role"], "general_inbox")
        self.assertIsNone(contact["contact_person_name"])

    def test_personal_email_fallback_without_verified_person_name(self):
        contact = select_site_contact([
            page("/contact", "<p>Neem contact op met onze fietsmonteur.</p><a href='mailto:peter@acmefietsen.nl'>E-mail</a>"),
            page("/contact", "<p>Algemene vragen:</p><a href='mailto:info@acmefietsen.nl'>Info</a>"),
        ], "acmefietsen.nl")
        self.assertEqual(contact["public_business_email"], "peter@acmefietsen.nl")
        self.assertEqual(contact["contact_role"], "personal_mailbox")
        self.assertIsNone(contact["contact_person_name"])

    def test_unrelated_agency_address_does_not_replace_official_contact(self):
        contact = select_site_contact([
            page("/", "<p>Website door Webdesign Bureau.</p><a href='mailto:hello@webagency.nl'>Site partner</a>"),
            page("/contact", "<a href='mailto:info@acmefietsen.nl'>Contact</a>"),
        ], "acmefietsen.nl")
        self.assertEqual(contact["public_business_email"], "info@acmefietsen.nl")

    def test_do_not_invent_email_from_owner_name(self):
        contact = select_site_contact([
            page("/over-ons", "<h2>Jan Jansen</h2><p>Eigenaar van onze fietszaak</p><p>Contactformulier voor vragen.</p>"),
        ], "acmefietsen.nl")
        self.assertEqual(contact["contact_status"], "no_public_contact_found")
        self.assertIsNone(contact["public_business_email"])

    def test_about_and_team_links_are_prioritized_for_research(self):
        home = parse_html(
            "<a href='/producten'>Catalogus</a><a href='/contact'>Contact</a>"
            "<a href='/over-ons'>Over ons</a><a href='/team'>Ons team</a>"
            "<a href='https://external.example/owner'>Directie extern</a>"
        )
        links = preferred_contact_links(home, "https://acmefietsen.nl/", "acmefietsen.nl")
        self.assertEqual(set(links[:2]), {"https://acmefietsen.nl/over-ons", "https://acmefietsen.nl/team"})
        self.assertIn("https://acmefietsen.nl/contact", links)
        self.assertNotIn("https://external.example/owner", links)

    @patch("cold_stages.is_public_http_url", return_value=True)
    def test_no_email_does_not_block_website_research(self, _):
        homepage = Response("https://acmefietsen.nl/", """
            <title>Acme Fietsen</title><p>Acme Fietsen maakt en verkoopt elektrische fietsen.</p>
            <a href="/diensten">Diensten</a>
        """)
        details = Response("https://acmefietsen.nl/diensten", """
            <p>Wij bieden onderhoud en fietsreparaties vanuit onze werkplaats in Rotterdam.</p>
        """)
        session = Session([homepage, details])
        with patch("first_party_contacts.is_public_http_url", return_value=True, create=True):
            verified = verify_candidate({
                "name_hint": "Acme Fietsen", "website_hint": "https://acmefietsen.nl/"
            }, session_factory=lambda: session)
            self.assertTrue(verified["ready_for_research"])
            self.assertEqual(verified["contact_status"], "pending_post_research")
            self.assertIsNone(verified["public_business_email"])
            researched = research_candidate(verified, session_factory=lambda: session)
        self.assertEqual(researched["research_status"], "ready")
        self.assertEqual(researched["contact_status"], "no_public_contact_found")
        self.assertGreaterEqual(len(researched["evidence_candidates"]), 1)
        self.assertEqual(len(session.urls), 2)

    def test_contact_only_dedupe_suppresses_known_shared_email_not_website(self):
        researched = {
            "candidate_count": 1, "research_ready_count": 1,
            "candidates": [{
                "name_hint": "Acme Fietsen",
                "official_domain": "acmefietsen.nl",
                "research_status": "ready",
                "evidence_candidates": [{"text": "Klanten kunnen online een afspraak maken."}],
                "public_business_email": "jan@gmail.com",
                "email_source_url": "https://acmefietsen.nl/team",
                "contact_person_name": "Jan Jansen",
                "contact_role": "named_owner",
                "contact_status": "verified_official_site",
            }],
        }
        registry = [{
            "identity": {"company": "unrelated", "domains": {"elsewhere.nl"}, "emails": {"jan@gmail.com"}, "lead_ids": set()},
            "status": "sent", "row_number": 2,
        }]
        result = suppress_previously_used_contact_emails(researched, registry)
        selected = result["candidates"][0]
        self.assertEqual(result["research_ready_count"], 1)
        self.assertEqual(result["contact_dedupe_suppressed_count"], 1)
        self.assertEqual(selected["contact_status"], "suppressed_existing_email")
        self.assertIsNone(selected["public_business_email"])
        self.assertTrue(selected["evidence_candidates"])


if __name__ == "__main__":
    unittest.main()
