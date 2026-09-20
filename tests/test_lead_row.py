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
            "contact_basis_status": "pass",
            "contact_basis_type": "purpose_specific_published_contact",
            "contact_basis_evidence_ref": "https://example.nl/contact/",
            "outreach_status": "ready_for_draftqueue",
            "draft_queue_eligible": "TRUE",
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


    def test_missing_final_eligibility_gate_blocks(self):
        row = self.base()
        row["contact_basis_status"] = ""
        with self.assertRaises(ValueError):
            validate_row(row)

    def test_contact_basis_must_pass(self):
        row = self.base()
        row["contact_basis_status"] = "blocked"
        with self.assertRaises(ValueError):
            validate_row(row)

    def test_contact_basis_type_must_be_allowed(self):
        row = self.base()
        row["contact_basis_type"] = "none"
        with self.assertRaises(ValueError):
            validate_row(row)

    def test_purpose_specific_basis_evidence_must_be_official_site(self):
        row = self.base()
        row["contact_basis_evidence_ref"] = "https://directory.example/company/"
        with self.assertRaises(ValueError):
            validate_row(row)

    def test_first_party_basis_requires_first_party_reference(self):
        for basis in ("prior_valid_consent", "existing_customer_similar_services_exception"):
            with self.subTest(basis=basis):
                row = self.base()
                row["contact_basis_type"] = basis
                row["contact_basis_evidence_ref"] = "https://example.nl/contact/"
                with self.assertRaises(ValueError):
                    validate_row(row)

                row["contact_basis_evidence_ref"] = "first_party:crm-fixture-001"
                self.assertEqual(validate_row(row)["contact_basis_type"], basis)

    def test_outreach_must_be_ready_for_draftqueue(self):
        row = self.base()
        row["outreach_status"] = "blocked"
        with self.assertRaises(ValueError):
            validate_row(row)

    def test_draft_queue_eligible_must_be_true(self):
        row = self.base()
        row["draft_queue_eligible"] = "FALSE"
        with self.assertRaises(ValueError):
            validate_row(row)

    def test_price_or_discount_in_first_touch_blocks(self):
        for fragment in (" voor €500", " met 20% korting"):
            with self.subTest(fragment=fragment):
                row = self.base()
                row["body"] = row["body"].replace("Geen interesse?", fragment + ". Geen interesse?")
                with self.assertRaises(ValueError):
                    validate_row(row)

    def test_default_meeting_ask_blocks(self):
        row = self.base()
        row["body"] = row["body"].replace("Zal ik het voorbeeld sturen?", "Zullen we bellen?")
        with self.assertRaises(ValueError):
            validate_row(row)



    def test_subject_header_injection_blocks(self):
        row = self.base()
        row["subject"] = "Kleine kans\nBcc: attacker@example.com"
        with self.assertRaises(ValueError):
            validate_row(row)

    def test_lead_id_header_injection_blocks(self):
        row = self.base()
        row["lead_id"] = "lead-1\r\nBcc: attacker@example.com"
        with self.assertRaises(ValueError):
            validate_row(row)


if __name__ == "__main__":
    unittest.main()
