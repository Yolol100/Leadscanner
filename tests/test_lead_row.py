import unittest

from lead_row import ALLOWED_OFFERS, validate_row


class LeadRowTests(unittest.TestCase):
    def base(self):
        return {
            "lead_id": "lead-1",
            "company": "Voorbeeld BV",
            "website": "https://example.nl/",
            "offer": "website_webshop",
            "observation": "De offertepagina vraagt niet duidelijk wat de volgende stap is.",
            "observation_source_url": "https://example.nl/offerte/",
            "email": "info@example.nl",
            "email_source_url": "https://example.nl/contact/",
            "subject": "Kleine website kans",
            "body": (
                "Beste team, op jullie offertepagina zag ik dat de volgende stap voor een nieuwe aanvraag niet "
                "duidelijk wordt uitgelegd. Ik kan één kort voorbeeld maken van een duidelijkere contactroute die "
                "beter aansluit op deze pagina. Zal ik het voorbeeld sturen? Geen interesse? Een kort nee is genoeg. "
                "Met vriendelijke groet, Andrew Baeten, andrewbaeten.nl"
            ),
        }

    def test_valid_row(self):
        self.assertEqual(validate_row(self.base())["lead_id"], "lead-1")

    def test_exact_four_offers_are_allowed(self):
        self.assertEqual(
            ALLOWED_OFFERS,
            {"ai_agents", "social_media", "search_visibility", "website_webshop"},
        )
        for offer in sorted(ALLOWED_OFFERS):
            row = self.base()
            row["offer"] = offer
            self.assertEqual(validate_row(row)["offer"], offer)

    def test_legacy_offer_labels_block(self):
        for offer in ["conversion_contact", "wordpress_elementor", "seo"]:
            row = self.base()
            row["offer"] = offer
            with self.assertRaises(ValueError):
                validate_row(row)

    def test_missing_evidence_url_blocks(self):
        row = self.base()
        row["observation_source_url"] = ""
        with self.assertRaises(ValueError):
            validate_row(row)

    def test_external_observation_source_blocks(self):
        row = self.base()
        row["observation_source_url"] = "https://other.example/contact/"
        with self.assertRaises(ValueError):
            validate_row(row)

    def test_external_email_source_blocks(self):
        row = self.base()
        row["email_source_url"] = "https://directory.example/company/"
        with self.assertRaises(ValueError):
            validate_row(row)

    def test_subdomain_source_is_allowed(self):
        row = self.base()
        row["email_source_url"] = "https://contact.example.nl/team/"
        self.assertEqual(validate_row(row)["email"], "info@example.nl")

    def test_invalid_offer_blocks(self):
        row = self.base()
        row["offer"] = "everything"
        with self.assertRaises(ValueError):
            validate_row(row)

    def test_placeholder_blocks(self):
        row = self.base()
        row["body"] += " {{NAME}}"
        with self.assertRaises(ValueError):
            validate_row(row)

    def test_missing_optout_blocks(self):
        row = self.base()
        row["body"] = row["body"].replace("Geen interesse? Een kort nee is genoeg. ", "")
        with self.assertRaises(ValueError):
            validate_row(row)


if __name__ == "__main__":
    unittest.main()
