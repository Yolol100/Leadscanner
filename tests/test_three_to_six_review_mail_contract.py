"""User contract: 2-3 verified practical suggestions, no synthetic send."""
import unittest

from outreach_stages import (
    generate_mails, select_reasons, choose_value_actions,
    looks_like_page_title, validate_mail,
)


def candidate(count=3, *, language="nl", domain="testwinkel.nl", store=False):
    if language == "nl":
        facts = [
            ("Klanten kunnen online een werkplaatsafspraak aanvragen voor onderhoud.", "afspraak"),
            ("Vraag online een offerte aan voor maatwerk via ons formulier.", "offerte"),
            ("Bestel onderdelen online en kies daarna het gewenste afhaalmoment.", "bestellen"),
            ("Bezoekers kunnen via het retourformulier hun bestelling retourneren.", "retouren"),
            ("Onze klanten vinden antwoorden in de kennisbank met veelgestelde vragen.", "faq"),
            ("Wij verzorgen bezorging en afhalen voor klanten in de regio.", "bezorgen"),
        ]
    else:
        facts = [
            ("Customers can book a service appointment using our online form.", "book"),
            ("Visitors can request a quote for repairs using our online form.", "quote"),
            ("Customers can order online and select a pickup time.", "order"),
        ]
    return {
        "official_domain": domain,
        "research_status": "ready",
        "public_business_email": "contact@" + domain,
        "website_type": "webshop" if store else "website",
        "evidence_candidates": [
            {"source_type": "official_site",
             "source_url": f"https://{domain}/{route}", "page_type": "process",
             "text": fact}
            for fact, route in facts[:count]
        ],
    }


def review(candidate_row):
    return generate_mails(choose_value_actions(select_reasons({
        "candidates": [candidate_row],
    })))["candidates"][0]


class ThreeToSixReviewMailContract(unittest.TestCase):
    def test_pampalini_seo_title_is_not_a_real_improvement(self):
        title = "Reserveren - Pampalini Utrecht - Lunchroom"
        self.assertTrue(looks_like_page_title(title))
        row = candidate(0)
        row["evidence_candidates"] = [
            {"text": title, "source_type": "official_site",
             "source_url": "https://testwinkel.nl/reserveren",
             "page_type": "process"},
        ]
        result = review(row)
        self.assertEqual(result["mail_status"], "hold")
        self.assertIsNone(result["subject"])
        self.assertIsNone(result["body"])

    def test_one_good_fact_cannot_create_a_draft(self):
        for count in (1,):
            with self.subTest(count=count):
                result = review(candidate(count))
                self.assertEqual(result["mail_status"], "hold")
                self.assertIsNone(result["body"])
                self.assertIsNone(result["subject"])

    def test_three_different_facts_have_actual_fixes(self):
        item = review(candidate(3))
        self.assertEqual(item["mail_status"], "ready_for_human_review")
        self.assertEqual(item["copy_validation_status"], "green")
        self.assertEqual(item["subject"], "3 verbeterideeën voor jullie website")
        self.assertEqual(item["body"].count("Verbeteridee:"), 3)
        self.assertEqual(item["body"].count("?"), 1)
        self.assertTrue(item["body"].startswith("Beste,"))
        self.assertTrue(item["body"].endswith("Met vriendelijke groeten,\nAndrew"))
        self.assertIn("Als je geen interesse hebt, hoef je niet te reageren.", item["body"])
        self.assertFalse(item["automatic_send"])
        self.assertEqual(item["draft_status"], "not_created")
        for part in item["selected_findings"]:
            self.assertIn(part["observation"], item["body"])
            self.assertIn(part["suggested_improvement"], item["body"])
            self.assertTrue(part["source_url"].startswith("https://testwinkel.nl/"))

    def test_maximum_three_without_repetition_or_padding(self):
        item = review(candidate(6, store=True))
        self.assertEqual(item["mail_status"], "ready_for_human_review",
                         msg=str({"reason": item["copy_validation_reasons"],
                                  "outreach_hold": item.get("outreach_hold_reason"),
                                  "value_hold": item.get("value_action_hold_reason"),
                                  "count": len(item.get("selected_findings") or []),
                                  "categories": [f.get("category") for f in (item.get("selected_findings") or [])]}))
        self.assertEqual(item["subject"], "3 verbeterideeën voor jullie webshop")
        self.assertEqual(item["body"].count("Verbeteridee:"), 3)
        self.assertLessEqual(len(item["body"].split()), 320)
        self.assertEqual(len({f["category"] for f in item["selected_findings"]}), 3)

    def test_language_is_en_when_first_party_site_is_english(self):
        item = review(candidate(3, language="en", domain="example.org"))
        self.assertEqual(item["mail_status"], "ready_for_human_review")
        self.assertTrue(item["body"].startswith("Dear team,"))
        self.assertEqual(item["body"].count("Suggested improvement:"), 3)
        self.assertIn("If you're not interested, there's no need to reply.", item["body"])
        self.assertTrue(item["body"].endswith("Kind regards,\nAndrew"))

    def test_three_repetitions_of_one_feature_are_not_three_issues(self):
        row = candidate(3)
        appointment = row["evidence_candidates"][0]
        row["evidence_candidates"] = [
            {**appointment, "text": appointment["text"] + " Klanten krijgen een bericht."},
            {**appointment, "text": appointment["text"] + " Via onze website."},
            appointment,
        ]
        item = review(row)
        self.assertEqual(item["mail_status"], "hold")
        self.assertIsNone(item["body"])

    def test_automated_audit_does_not_claim_unsupported_defects(self):
        item = review(candidate(3))
        self.assertNotIn("is kapot", item["body"])
        self.assertNotIn("werkt niet", item["body"])
        self.assertNotIn("Ik heb alvast", item["body"])
        self.assertNotIn("Op jullie website viel me dit detail op", item["body"])
        changed = item["body"].replace(item["selected_findings"][1]["suggested_improvement"], "niet gecontroleerd", 1)
        reasons = validate_mail(item, item["subject"], changed)
        self.assertIn("sourced_improvement_missing_or_unreviewed", reasons)


if __name__ == "__main__":
    unittest.main()
