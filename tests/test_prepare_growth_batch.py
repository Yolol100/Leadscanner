from __future__ import annotations

import unittest

from prepare_growth_batch import prepare_batch, subject_for_company


class GrowthBatchTests(unittest.TestCase):
    def config(self):
        return {"monthly_price_eur": {"min": 250, "max": 500}}

    def contact(self, language="nl", basis="review_required"):
        return {
            "name_hint": "Voorbeeld Fysiotherapie" if language == "nl" else "Example Physiotherapy",
            "website_hint": "https://voorbeeld.nl" if language == "nl" else "https://example.com",
            "official_domain_hint": "voorbeeld.nl" if language == "nl" else "example.com",
            "public_business_emails": ["info@voorbeeld.nl" if language == "nl" else "sales@example.com"],
            "email_source_urls": ["https://voorbeeld.nl/contact"],
            "email_source_types": ["official_site"],
            "email_source_refs": ["https://voorbeeld.nl/contact"],
            "verified_observation": "Fysiotherapie in Utrecht" if language == "nl" else "Physical therapy in Utrecht",
            "verified_observation_source_url": "https://voorbeeld.nl" if language == "nl" else "https://example.com",
            "verified_observation_source_type": "official_site",
            "language": language,
            "language_source": "html_lang",
            "excluded_competitor": False,
            "contact_basis_status": basis,
            "contact_basis_hint": "public_email_review_required",
        }

    def test_review_required_contact_becomes_personal_review_draft(self):
        row = prepare_batch({"candidates": [self.contact()]}, self.config(), draft_limit=1)["rows"][0]
        self.assertEqual(row["status"], "review_draft")
        self.assertTrue(row["lead_id"].startswith("growth-"))
        self.assertEqual(row["subject"], "Idee voor Voorbeeld Fysiotherapie")
        self.assertEqual(row["copy_company_label"], "Voorbeeld Fysiotherapie")
        self.assertIn("Ik zag dat Voorbeeld Fysiotherapie zich richt op fysiotherapie", row["body"])
        self.assertIn("Met mijn Groeiabonnement kan ik helpen met", row["body"])
        self.assertNotIn("Op jullie website staat", row["body"])
        self.assertEqual(row["verified_observation_source_type"], "official_site")
        for value in (
            "Website/webshop — verbeteren of nieuw maken waar nodig",
            "Zoekbaarheid — beter vindbaar worden",
            "Social content — passende content maken",
            "Automatisering — geschikte processen deels automatiseren",
            "Hosting — beheren of overnemen waar passend",
            "Ik als vast contactpersoon",
            "€250–€500 per maand, afhankelijk van wat jullie nodig hebben",
            "voorbeeld design maken voor Voorbeeld Fysiotherapie",
            "Groet,\nAndrew",
        ):
            self.assertIn(value, row["body"])
        self.assertNotIn("30%", row["body"])
        self.assertNotIn("Webactueel B.V.", row["body"])

    def test_low_signal_observation_uses_service_focus_without_fake_quote(self):
        contact = self.contact()
        contact["name_hint"] = "030 Fietsen – Tweedehands Fietsen Utrecht"
        contact["verified_observation"] = "Home - 030 Fietsen"
        row = prepare_batch({"candidates": [contact]}, self.config(), draft_limit=1)["rows"][0]
        self.assertIn("Ik zag dat 030 Fietsen zich richt op fietsen en fietsservice", row["body"])
        self.assertNotIn("op de site komt dat terug in", row["body"])
        self.assertEqual(row["subject"], "Idee voor 030 Fietsen")
        self.assertIn("Ik zag dat 030 Fietsen zich richt op fietsen en fietsservice", row["body"])
        self.assertNotIn("Tweedehands Fietsen Utrecht elektrische fietsen", row["body"])

    def test_percentage_observation_is_not_quoted_into_first_touch(self):
        contact = self.contact()
        contact["name_hint"] = "Acme BV"
        contact["verified_observation"] = "Nu tot 30% voordeel op geselecteerde producten"
        row = prepare_batch({"candidates": [contact]}, self.config(), draft_limit=1)["rows"][0]
        self.assertNotIn("%", row["body"])
        self.assertIn("Ik heb de website van Acme BV bekeken.", row["body"])
        self.assertNotIn(contact["verified_observation"], row["body"])

    def test_observation_overrides_misleading_company_name_for_focus(self):
        contact = self.contact()
        contact["name_hint"] = "De Juwelier"
        contact["verified_observation"] = "À LA CARTE RESTAURANT"
        row = prepare_batch({"candidates": [contact]}, self.config(), draft_limit=1)["rows"][0]
        self.assertIn("zich richt op restaurant en gastvrijheid", row["body"])
        self.assertNotIn("sieraden en juwelierswerk", row["body"])

    def test_pass_contact_becomes_draft_ready(self):
        row = prepare_batch(
            {"candidates": [self.contact(language="en", basis="pass")]},
            self.config(),
            draft_limit=1,
        )["rows"][0]
        self.assertEqual(row["status"], "draft_ready")
        self.assertEqual(row["subject"], "An idea for Example Physiotherapy")
        self.assertIn("I saw that Example Physiotherapy focuses on physical therapy and rehabilitation", row["body"])
        self.assertIn("€250–€500 per month, depending on what you need", row["body"])
        self.assertIn("no-obligation example design for Example Physiotherapy", row["body"])
        self.assertNotIn("30%", row["body"])

    def test_missing_verified_observation_blocks_draft(self):
        contact = self.contact()
        contact["verified_observation"] = None
        contact["verified_observation_source_url"] = None
        contact["verified_observation_source_type"] = None
        row = prepare_batch({"candidates": [contact]}, self.config(), draft_limit=1)["rows"][0]
        self.assertEqual(row["status"], "blocked_missing_verified_observation")
        self.assertIsNone(row["subject"])
        self.assertIsNone(row["body"])
        self.assertIsNone(row["concept_preview"])

    def test_draft_limit_keeps_flow_small(self):
        second = {**self.contact(), "name_hint": "Tweede Fysio", "public_business_emails": ["info@tweede.nl"]}
        result = prepare_batch({"candidates": [self.contact(), second]}, self.config(), draft_limit=1)
        self.assertEqual(result["draft_candidate_count"], 1)
        self.assertEqual(result["rows"][1]["status"], "email_found_not_selected")

    def test_competitor_gets_no_concept(self):
        contact = self.contact()
        contact["excluded_competitor"] = True
        contact["exclusion_reason"] = "official_site:digital agency"
        row = prepare_batch({"candidates": [contact]}, self.config())["rows"][0]
        self.assertEqual(row["status"], "excluded_competitor")
        self.assertIsNone(row["email"])
        self.assertIsNone(row["concept_preview"])

    def test_copy_and_subject_stay_compact(self):
        for language in ("nl", "en"):
            row = prepare_batch({"candidates": [self.contact(language=language)]}, self.config())["rows"][0]
            self.assertLessEqual(len(row["body"].split()), 150)
            self.assertLessEqual(len(row["subject"].split()), 7)

    def test_long_company_uses_personal_short_label(self):
        self.assertEqual(
            subject_for_company("030 Fietsen – Tweedehands Fietsen Utrecht elektrische fietsen", "nl"),
            "Idee voor 030 Fietsen",
        )

    def test_long_company_without_separator_keeps_personal_subject(self):
        row = prepare_batch(
            {"candidates": [{**self.contact(), "name_hint": "Kindergarden Voormalige Stadstimmertuin Amsterdam"}]},
            self.config(),
            draft_limit=1,
        )["rows"][0]
        self.assertEqual(row["copy_subject_label"], "Kindergarden Voormalige Stadstimmertuin Amsterdam")
        self.assertEqual(row["subject"], "Idee voor Kindergarden Voormalige Stadstimmertuin Amsterdam")
        self.assertNotIn("jullie online aanpak", row["subject"])

    def test_subject_removes_decorative_emoji_and_avoids_dangling_connector(self):
        self.assertEqual(subject_for_company("Piccola Italia 🇮🇹", "nl"), "Idee voor Piccola Italia")
        self.assertEqual(subject_for_company("Bistro De Buik Van Parijs | Zwolle", "nl"), "Idee voor Bistro De Buik Van Parijs")
        self.assertEqual(subject_for_company("Busch & van der Worp", "nl"), "Idee voor Busch & van der Worp")

    def test_template_follows_growth_policy_order_and_single_offer(self):
        row = prepare_batch({"candidates": [self.contact()]}, self.config())["rows"][0]
        body = row["body"]
        self.assertLess(body.index("• Website/webshop"), body.index("€250–€500 per maand"))
        self.assertIn("• Ik als vast contactpersoon", body)
        self.assertIn("voorbeeld design maken voor Voorbeeld Fysiotherapie", body)
        self.assertNotIn("30%", body)
        self.assertNotIn("meeting", body.casefold())

    def test_weak_website_titles_are_not_quoted(self):
        contact = self.contact()
        contact["name_hint"] = "KU Kitchen & Bar"
        contact["verified_observation"] = "🔒 Beveiligde Website"
        row = prepare_batch({"candidates": [contact]}, self.config())["rows"][0]
        self.assertNotIn("Beveiligde Website", row["body"])


if __name__ == "__main__":
    unittest.main()
