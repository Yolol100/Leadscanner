from __future__ import annotations

import unittest

from prepare_growth_batch import prepare_batch, subject_for_company


class GrowthBatchTests(unittest.TestCase):
    def config(self):
        return {"monthly_price_eur": {"min": 250, "max": 500}}

    def contact(self, language="nl", basis="review_required"):
        return {
            "name_hint": "Voorbeeld BV" if language == "nl" else "Example Ltd",
            "website_hint": "https://voorbeeld.nl" if language == "nl" else "https://example.com",
            "official_domain_hint": "voorbeeld.nl" if language == "nl" else "example.com",
            "public_business_emails": ["info@voorbeeld.nl" if language == "nl" else "sales@example.com"],
            "email_source_urls": ["https://voorbeeld.nl/contact"],
            "email_source_types": ["official_site"],
            "email_source_refs": ["https://voorbeeld.nl/contact"],
            "language": language,
            "language_source": "html_lang",
            "excluded_competitor": False,
            "contact_basis_status": basis,
            "contact_basis_hint": "public_email_review_required",
        }

    def test_review_required_contact_becomes_review_draft(self):
        row = prepare_batch({"candidates": [self.contact()]}, self.config(), draft_limit=1)["rows"][0]
        self.assertEqual(row["status"], "review_draft")
        self.assertTrue(row["lead_id"].startswith("growth-"))
        self.assertEqual(row["subject"], "Idee voor Voorbeeld BV")
        for value in (
            "Website/webshop verbeteren of nieuw maken waar nodig",
            "Zoekbaarheid verbeteren",
            "Social content verzorgen",
            "deels automatiseren",
            "Hosting overnemen/beheren",
            "Ik als vast contactpersoon",
            "€250–€500 per maand",
            "voorbeeld design",
            "Groet,\nAndrew",
        ):
            self.assertIn(value, row["body"])
        self.assertNotIn("30%", row["body"])
        self.assertNotIn("Webactueel B.V.", row["body"])

    def test_pass_contact_becomes_draft_ready(self):
        row = prepare_batch(
            {"candidates": [self.contact(language="en", basis="pass")]},
            self.config(),
            draft_limit=1,
        )["rows"][0]
        self.assertEqual(row["status"], "draft_ready")
        self.assertEqual(row["subject"], "An idea for Example Ltd")
        self.assertIn("€250–€500 per month", row["body"])
        self.assertIn("no-obligation example design", row["body"])
        self.assertNotIn("30%", row["body"])

    def test_draft_limit_keeps_flow_small(self):
        second = {**self.contact(), "name_hint": "Tweede BV", "public_business_emails": ["info@tweede.nl"]}
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
            self.assertLessEqual(len(row["body"].split()), 120)
            self.assertLessEqual(len(row["subject"].split()), 6)

    def test_long_company_uses_short_fallback_subject(self):
        self.assertEqual(
            subject_for_company("Een Bedrijfsnaam Die Veel Te Lang Is Voor Een Onderwerpregel", "nl"),
            "Idee voor jullie online aanpak",
        )


if __name__ == "__main__":
    unittest.main()
