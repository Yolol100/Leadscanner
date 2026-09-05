from __future__ import annotations

import unittest

from outreach_copy_preflight import followup_copy_errors, initial_copy_errors
from outreach_prepare import build_copy, build_prepared_row


class OutreachPrepareTests(unittest.TestCase):
    def test_dutch_prepared_copy_matches_active_leadpromo_contract(self):
        subject, body, followup_subject, followup_body, delay = build_copy(
            company="Voorbeeld Winkel",
            country="NL",
            fact="In de begrensde homepagecheck van Voorbeeld Winkel is geen duidelijke interne contact- of offertelink gevonden.",
            idea="Voeg op de homepage van Voorbeeld Winkel één vaste contact- of offerteknop toe, zodat bezoekers in één stap kunnen reageren.",
            analysis_type="webshop",
        )
        self.assertEqual(initial_copy_errors(subject, body), [])
        self.assertEqual(followup_copy_errors(followup_body), [])
        self.assertEqual(followup_subject, "")
        self.assertEqual(delay, 4)

    def test_us_copy_contains_commercial_label_and_postal_address(self):
        address = "Example Business, 1 Test Street, New York, NY 10001, USA"
        subject, body, _, followup_body, _ = build_copy(
            company="Example Products",
            country="US",
            fact="The bounded homepage check for Example Products found no clear internal contact or quote link.",
            idea="Add one persistent contact or quote call-to-action on the homepage of Example Products so visitors can respond in one step.",
            analysis_type="website",
            postal_address=address,
        )
        self.assertIn("commercial message", body.lower())
        self.assertIn(address, body)
        self.assertEqual(initial_copy_errors(subject, body), [])
        self.assertEqual(followup_copy_errors(followup_body), [])

    def test_us_copy_fails_closed_without_postal_address(self):
        with self.assertRaises(ValueError):
            build_copy(
                company="Example Products",
                country="US",
                fact="The bounded homepage check for Example Products found no clear internal contact or quote link.",
                idea="Add one persistent contact or quote call-to-action on the homepage of Example Products so visitors can respond in one step.",
                analysis_type="website",
            )

    def test_prepared_row_never_auto_approves_or_sends(self):
        candidate = {
            "candidate_id": "prospect-1",
            "company": "Voorbeeld Winkel",
            "website": "https://voorbeeld.nl/",
            "country": "NL",
            "status": "qualified",
        }
        qualification = {
            "tier": "A",
            "status": "qualified",
            "customer_potential": "8",
            "evidence_url": "https://voorbeeld.nl/",
            "fact": "In de begrensde homepagecheck van Voorbeeld Winkel is geen duidelijke interne contact- of offertelink gevonden.",
            "idea": "Voeg op de homepage van Voorbeeld Winkel één vaste contact- of offerteknop toe, zodat bezoekers in één stap kunnen reageren.",
            "analysis_type": "website",
        }
        contact = {
            "checked_at": "2026-09-05T20:00:00Z",
            "email": "info@voorbeeld.nl",
            "status": "ready",
        }
        row = build_prepared_row(candidate, qualification, contact)
        self.assertEqual(row["status"], "prepared")
        self.assertEqual(row["compliance_status"], "manual_review")
        self.assertEqual(row["compliance_basis"], "")
        self.assertEqual(row["opt_out_mode"], "reply_optout")
        self.assertTrue(row["source"].startswith("website_scan:"))

    def test_non_a_or_non_ready_contact_is_rejected(self):
        candidate = {
            "candidate_id": "prospect-1", "company": "Example", "website": "https://example.com/",
            "country": "US", "status": "qualified",
        }
        qualification = {
            "tier": "B", "status": "hold", "fact": "x" * 20, "idea": "y" * 30,
            "analysis_type": "website",
        }
        contact = {"email": "info@example.com", "status": "ready"}
        with self.assertRaises(ValueError):
            build_prepared_row(candidate, qualification, contact, postal_address="1 Test Street, New York, NY 10001, USA")


if __name__ == "__main__":
    unittest.main()
