from __future__ import annotations

import unittest

from prepare_growth_batch import prepare_batch


class GrowthBatchTests(unittest.TestCase):
    def config(self):
        return {
            "monthly_price_eur": {"min": 200, "max": 500},
            "first_touch": {
                "price_text": "Het kost doorgaans €200-€500 per maand, afhankelijk van de afgesproken scope."
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
        self.assertIn("website/webshop", row["body"])
        self.assertIn("vindbaarheid", row["body"])
        self.assertIn("social content", row["body"])
        self.assertIn("30%", row["body"])
        self.assertIn("hosting", row["body"])
        self.assertIn("vaste contactpersoon", row["body"])
        self.assertIn("Andrew Baeten", row["body"])
        self.assertIn("andrewbaeten.nl", row["body"])
        self.assertIn("Geen interesse?", row["body"])
        self.assertEqual(row["subject"], "Groeiabonnement voor Voorbeeld BV")


    def test_all_angles_render_without_old_broken_grammar(self):
        contacts = {
            "candidates": [
                {
                    "name_hint": "Voorbeeld BV",
                    "public_business_emails": [],
                    "contact_basis_status": "unverified",
                }
            ]
        }
        for angle in (
            "website_webshop",
            "search_visibility",
            "social_content",
            "automation",
            "hosting",
            "fixed_contact",
        ):
            result = prepare_batch(
                contacts,
                self.config(),
                angle=angle,
                show_price=True,
            )
            preview = result["rows"][0]["template_preview"]
            self.assertNotIn("om hun", preview)
            self.assertGreaterEqual(len(preview.split()), 50)
            self.assertLessEqual(len(preview.split()), 90)


if __name__ == "__main__":
    unittest.main()
