from __future__ import annotations

import unittest

from prepare_growth_batch import prepare_batch


class GrowthBatchTests(unittest.TestCase):
    def config(self):
        return {
            "monthly_price_eur": {"min": 250, "max": 500},
        }

    def test_dutch_contact_gets_dutch_concept_preview(self):
        contacts = {
            "candidates": [
                {
                    "name_hint": "Voorbeeld BV",
                    "website_hint": "https://voorbeeld.nl",
                    "official_domain_hint": "voorbeeld.nl",
                    "public_business_emails": ["info@voorbeeld.nl"],
                    "email_source_urls": ["https://voorbeeld.nl/contact"],
                    "language": "nl",
                    "language_source": "html_lang",
                    "excluded_competitor": False,
                    "contact_basis_status": "unverified",
                    "contact_basis_hint": "generic_contact_only",
                }
            ]
        }
        result = prepare_batch(contacts, self.config())
        row = result["rows"][0]
        self.assertEqual(row["status"], "needs_contact_basis")
        self.assertEqual(row["email"], "info@voorbeeld.nl")
        self.assertIsNone(row["body"])
        self.assertEqual(row["subject_preview"], "Korte vraag over online groei")
        self.assertIn("€250-€500", row["concept_preview"])
        self.assertIn("vaste contactpersoon", row["concept_preview"])
        self.assertIn("Geen interesse?", row["concept_preview"])

    def test_english_passed_contact_gets_english_addressed_copy(self):
        contacts = {
            "candidates": [
                {
                    "name_hint": "Example Ltd",
                    "website_hint": "https://example.com",
                    "public_business_emails": ["sales@example.com"],
                    "email_source_urls": ["https://example.com/contact"],
                    "language": "en",
                    "language_source": "html_lang",
                    "excluded_competitor": False,
                    "contact_basis_status": "pass",
                    "contact_basis_hint": "reviewed_pass",
                }
            ]
        }
        result = prepare_batch(contacts, self.config())
        row = result["rows"][0]
        self.assertEqual(row["status"], "draft_ready")
        self.assertEqual(row["subject"], "Quick question about online growth")
        self.assertIn("€250-€500", row["body"])
        self.assertIn("website/webshop improvements", row["body"])
        self.assertIn("search visibility", row["body"])
        self.assertIn("social content", row["body"])
        self.assertIn("30%", row["body"])
        self.assertIn("hosting management", row["body"])
        self.assertIn("one fixed contact", row["body"])
        self.assertIn("Not interested?", row["body"])

    def test_competitor_gets_no_concept(self):
        contacts = {
            "candidates": [
                {
                    "name_hint": "Agency BV",
                    "language": "nl",
                    "excluded_competitor": True,
                    "exclusion_reason": "official_site:digital agency",
                    "public_business_emails": ["info@agency.nl"],
                }
            ]
        }
        result = prepare_batch(contacts, self.config())
        row = result["rows"][0]
        self.assertEqual(row["status"], "excluded_competitor")
        self.assertIsNone(row["email"])
        self.assertIsNone(row["concept_preview"])

    def test_nl_and_en_copy_stay_short(self):
        for language in ("nl", "en"):
            contacts = {
                "candidates": [
                    {
                        "name_hint": "Example",
                        "language": language,
                        "excluded_competitor": False,
                        "public_business_emails": [],
                    }
                ]
            }
            result = prepare_batch(contacts, self.config())
            words = len(result["rows"][0]["concept_preview"].split())
            self.assertGreaterEqual(words, 55)
            self.assertLessEqual(words, 95)


if __name__ == "__main__":
    unittest.main()
