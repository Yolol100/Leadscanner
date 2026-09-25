from __future__ import annotations

import unittest

from prepare_growth_batch import prepare_batch


class GrowthBatchTests(unittest.TestCase):
    def config(self):
        return {
            "monthly_price_eur": {"min": 200, "max": 500},
            "first_touch": {
                "price_text": "Meestal €200-€500 per maand, afhankelijk van scope."
            },
        }

    def test_unverified_contact_gets_template_only(self):
        contacts = {
            "candidates": [
                {
                    "name_hint": "Voorbeeld BV",
                    "website_hint": "https://voorbeeld.nl",
                    "official_domain_hint": "voorbeeld.nl",
                    "public_business_emails": ["info@voorbeeld.nl"],
                    "email_source_urls": ["https://voorbeeld.nl/contact"],
                    "contact_basis_status": "unverified",
                    "contact_basis_hint": "generic_contact_only",
                }
            ]
        }
        result = prepare_batch(
            contacts,
            self.config(),
            angle="website_webshop",
            show_price=False,
        )
        row = result["rows"][0]
        self.assertEqual(row["status"], "needs_contact_basis")
        self.assertIsNone(row["body"])
        self.assertIn("Groeiabonnement", row["template_preview"])
        self.assertNotIn("€200", row["template_preview"])

    def test_passed_contact_can_get_addressed_copy(self):
        contacts = {
            "candidates": [
                {
                    "name_hint": "Voorbeeld BV",
                    "website_hint": "https://voorbeeld.nl",
                    "public_business_emails": ["sales@voorbeeld.nl"],
                    "email_source_urls": ["https://voorbeeld.nl/business"],
                    "contact_basis_status": "pass",
                    "contact_basis_hint": "possible_purpose_specific",
                }
            ]
        }
        result = prepare_batch(
            contacts,
            self.config(),
            angle="automation",
            show_price=True,
        )
        row = result["rows"][0]
        self.assertEqual(row["status"], "draft_ready")
        self.assertEqual(row["email"], "sales@voorbeeld.nl")
        self.assertIn("€200-€500", row["body"])
        self.assertIn("automatiseren", row["body"])


if __name__ == "__main__":
    unittest.main()
