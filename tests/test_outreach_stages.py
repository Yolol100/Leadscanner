import unittest

from outreach_stages import (
    choose_value_actions,
    generate_mails,
    select_reasons,
    validate_mail,
    body_for,
)


def candidate_with_evidence(items):
    return {
        "name_hint": "Acme Fietsen",
        "official_domain": "acmefietsen.nl",
        "public_business_email": "info@acmefietsen.nl",
        "research_status": "ready",
        "evidence_candidates": items,
    }


def three_evidence(language="nl"):
    """Three distinct site routes with real, bounded first-party observations."""
    if language == "en":
        rows = [
            ("Customers can book a service appointment using our online form.", "booking"),
            ("Visitors can request a quote for repairs using our online form.", "quote"),
            ("Customers can order spare parts online and choose a pickup time.", "ordering"),
        ]
    else:
        rows = [
            ("Klanten kunnen online een werkplaatsafspraak aanvragen voor onderhoud of reparatie.", "afspraak"),
            ("Vraag online een offerte aan voor een reparatie via ons formulier.", "offerte"),
            ("Bestel onderdelen online en kies daarna het afhaalmoment in onze winkel.", "bestellen"),
        ]
    return [
        {"text": text, "source_url": "https://acmefietsen.nl/" + path,
         "source_type": "official_site", "page_type": "process"}
        for text, path in rows
    ]


class OutreachStagesTests(unittest.TestCase):
    def test_future_first_mail_uses_verified_fact_action_and_one_soft_cta(self):
        for language in ("nl", "en"):
            with self.subTest(language=language):
                row = candidate_with_evidence(three_evidence(language))
                mail = generate_mails(choose_value_actions(select_reasons({
                    "candidates": [row],
                })))["candidates"][0]
                self.assertEqual(mail["mail_status"], "ready_for_human_review")
                body = mail["body"]
                self.assertEqual(len(mail["selected_findings"]), 3)
                self.assertIn("1. ", body)
                self.assertIn("2. ", body)
                self.assertIn("3. ", body)
                self.assertEqual(body.count("?"), 1)
                self.assertIn("Andrew", body)
                self.assertNotIn("example variant", body.lower())
                self.assertNotIn("ROI", body)
                if language == "nl":
                    self.assertTrue(body.startswith("Beste,"))
                    self.assertTrue(body.endswith("Met vriendelijke groeten,\\nAndrew"))
                    self.assertIn("Als je geen interesse hebt, hoef je niet te reageren.", body)
                else:
                    self.assertTrue(body.startswith("Dear team,"))
                    self.assertTrue(body.endswith("Kind regards,\\nAndrew"))
                    self.assertIn("If you're not interested, there's no need to reply.", body)

    def test_ambiguous_website_language_is_held_regardless_of_domain(self):
        from unittest.mock import patch
        from outreach_stages import detect_language, select_one_reason
        candidate = {"official_domain": "example.nl", "research_status": "ready",
                     "evidence_candidates": [{"text": "Customers can book an appointment online via our booking form.",
                                              "source_type": "official_site",
                                              "source_url": "https://example.nl/booking",
                                              "page_type": "process"}]}
        self.assertEqual(detect_language(candidate, "ZXQ-4519"), "unknown")
        with patch("outreach_stages.detect_language", return_value="unknown"):
            selected = select_one_reason(candidate)
        self.assertEqual(selected["outreach_status"], "hold")
        self.assertEqual(selected["outreach_hold_reason"], "observation_language_ambiguous")

    def test_language_of_neutral_observation_uses_only_official_site_context(self):
        from outreach_stages import detect_language, select_one_reason
        ambiguous = "Bezorging van boeketten gebeurt dagelijks in Utrecht."
        row = {
            "research_status": "ready", "official_domain": "example.nl",
            "evidence_candidates": [{
                "text": ambiguous, "source_type": "official_site",
                "source_url": "https://example.nl/bezoek", "page_type": "detail",
            }, {
                "text": "Onze klanten kunnen online een afspraak aanvragen voor het ophalen van bloemen.",
                "source_url": "https://example.nl/afhalen",
                "source_type": "official_site", "page_type": "process",
            }, {
                "text": "Wij verzorgen vanuit onze winkel een bezorgservice voor alle bezoekers.",
                "source_url": "https://example.nl/diensten",
                "source_type": "official_site", "page_type": "services",
            }],
        }
        self.assertEqual(detect_language(row, ambiguous), "nl")
        selected = select_one_reason(row)
        self.assertEqual(selected["outreach_status"], "hold")
        self.assertEqual(selected["outreach_hold_reason"],
                         "fewer_than_three_distinct_verified_improvements")

    def test_cross_domain_context_cannot_override_unknown_language(self):
        from outreach_stages import detect_language
        ambiguous = "Bezorging van boeketten gebeurt dagelijks in Utrecht."
        row = {
            "official_domain": "example.nl",
            "evidence_candidates": [{
                "text": "Onze klanten kunnen online een afspraak aanvragen voor het ophalen.",
                "source_type": "official_site",
                "source_url": "https://unrelated.example/aanvraag",
            }],
        }
        self.assertEqual(detect_language(row, ambiguous), "unknown")

    def test_generated_first_mail_has_verified_sender_and_no_bogus_claims(self):
        from outreach_stages import generate_one_mail
        for lang in ("nl", "en"):
            row = candidate_with_evidence(three_evidence(lang))
            ranked = select_reasons({"candidates": [row]})["candidates"][0]
            valued = choose_value_actions({"candidates": [ranked]})["candidates"][0]
            mail = generate_one_mail(valued)
            body = mail["body"]
            self.assertEqual(body.count("Andrew"), 1)
            self.assertTrue(body.endswith("\\nAndrew"))
            self.assertEqual(body.count("?"), 1)
            self.assertNotIn("Webactueel", body)
            self.assertNotIn("ROI", body)

    def test_missing_email_does_not_hide_site_opportunity_but_holds_mail(self):
        candidate = candidate_with_evidence(three_evidence())
        candidate["public_business_email"] = None
        candidate["contact_status"] = "no_public_contact_found"
        opportunities = select_reasons({"candidates": [candidate]})
        self.assertEqual(opportunities["ready_count"], 1)
        mails = generate_mails(choose_value_actions(opportunities))
        self.assertEqual(mails["ready_for_human_review_count"], 0)
        self.assertEqual(
            mails["candidates"][0]["copy_validation_reasons"],
            ["no_published_business_contact"],
        )
        self.assertIsNone(mails["candidates"][0]["body"])

    def test_named_owner_receives_personalized_greeting_not_generic_mailbox(self):
        candidate = candidate_with_evidence(three_evidence())
        candidate["public_business_email"] = "jan@acmefietsen.nl"
        candidate["contact_person_name"] = "Jan Jansen"
        candidate["contact_role"] = "named_owner"
        candidate["contact_status"] = "verified_official_site"
        row = generate_mails(choose_value_actions(select_reasons({
            "candidates": [candidate],
        })))["candidates"][0]
        self.assertEqual(row["mail_status"], "ready_for_human_review")
        self.assertTrue(row["body"].startswith("Beste Jan,\\n\\n"))
        self.assertFalse(row["automatic_send"])

    def test_generic_company_description_is_hold(self):
        payload = {
            "candidates": [
                candidate_with_evidence([
                    {
                        "text": "Wij zijn een familiebedrijf in Rotterdam met jarenlange ervaring.",
                        "source_url": "https://acmefietsen.nl/",
                        "source_type": "official_site",
                        "page_type": "home",
                    }
                ])
            ]
        }
        result = select_reasons(payload)
        self.assertEqual(result["ready_count"], 0)
        self.assertEqual(
            result["candidates"][0]["outreach_hold_reason"],
            "weak_generic_marketing_signal",
        )

    def test_stronger_process_signal_beats_generic_service_signal(self):
        candidate = candidate_with_evidence([
            {"text": "Onze werkplaats biedt onderhoud en reparatie voor verschillende soorten fietsen.",
             "source_url": "https://acmefietsen.nl/diensten",
             "source_type": "official_site", "page_type": "services"},
            {"text": "Klanten kunnen online een werkplaatsafspraak aanvragen voor onderhoud of reparatie.",
             "source_url": "https://acmefietsen.nl/afspraak",
             "source_type": "official_site", "page_type": "process"},
        ])
        item = select_reasons({"candidates": [candidate]})["candidates"][0]
        self.assertEqual(item["outreach_status"], "hold")
        self.assertEqual(item["selected_findings"][0]["category"], "appointment")
        self.assertIn("werkplaatsafspraak", item["selected_findings"][0]["observation"])

    def test_generic_quality_service_and_catalog_copy_are_hold(self):
        payload = {
            "candidates": [
                candidate_with_evidence([
                    {
                        "text": "Kwaliteit en goede service staan centraal bij al onze werkzaamheden.",
                        "source_url": "https://acmefietsen.nl/",
                        "source_type": "official_site",
                        "page_type": "home",
                    },
                    {
                        "text": "Bekijk ons overzicht van diensten voor onderhoud reparatie en advies.",
                        "source_url": "https://acmefietsen.nl/diensten",
                        "source_type": "official_site",
                        "page_type": "services",
                    },
                ])
            ]
        }
        result = select_reasons(payload)
        self.assertEqual(result["ready_count"], 0)
        self.assertEqual(
            result["candidates"][0]["outreach_hold_reason"],
            "weak_generic_marketing_signal",
        )

    def test_appointment_word_without_customer_action_is_hold(self):
        payload = {
            "candidates": [
                candidate_with_evidence([
                    {
                        "text": "Wij werken op afspraak en leveren professionele service aan onze klanten.",
                        "source_url": "https://acmefietsen.nl/",
                        "source_type": "official_site",
                        "page_type": "home",
                    }
                ])
            ]
        }
        result = select_reasons(payload)
        self.assertEqual(result["ready_count"], 0)

    def test_quote_request_is_real_evidence_but_not_enough_for_mail(self):
        row = candidate_with_evidence([{
            "text": "Vraag online een offerte aan via het formulier voor uw schilderwerk.",
            "source_url": "https://acmefietsen.nl/offerte",
            "source_type": "official_site", "page_type": "process",
        }])
        result = select_reasons({"candidates": [row]})
        self.assertEqual(result["ready_count"], 0)
        self.assertEqual(result["candidates"][0]["selected_findings"][0]["category"],
                         "quote_request")

    def test_single_reservation_or_ordering_signal_is_not_a_mail(self):
        cases = [
            ("Reserveer online een tafel voor vanavond via onze reserveringspagina.",
             "https://acmefietsen.nl/reserveren", "reservation"),
            ("Bestel online uw maaltijd en kies daarna het gewenste afhaalmoment.",
             "https://acmefietsen.nl/bestellen", "ordering"),
        ]
        for text, source_url, expected in cases:
            row = candidate_with_evidence([{
                "text": text, "source_url": source_url,
                "source_type": "official_site", "page_type": "process",
            }])
            result = select_reasons({"candidates": [row]})
            self.assertEqual(result["ready_count"], 0)
            self.assertEqual(result["candidates"][0]["selected_findings"][0]["category"],
                             expected)

    def test_opening_hours_and_price_are_not_outreach_signals(self):
        payload = {
            "candidates": [
                candidate_with_evidence([
                    {
                        "text": "Maandag zijn wij geopend van 09:00 tot 17:00 voor klanten.",
                        "source_url": "https://acmefietsen.nl/contact",
                        "source_type": "official_site",
                        "page_type": "detail",
                    },
                    {
                        "text": "Een onderhoudsbeurt kost €49 en kan online worden aangevraagd.",
                        "source_url": "https://acmefietsen.nl/onderhoud",
                        "source_type": "official_site",
                        "page_type": "services",
                    },
                ])
            ]
        }
        result = select_reasons(payload)
        self.assertEqual(result["ready_count"], 0)

    def test_value_action_is_proposed_not_claimed_created(self):
        row = candidate_with_evidence(three_evidence())
        selected = select_reasons({"candidates": [row]})
        result = choose_value_actions(selected)
        item = result["candidates"][0]
        self.assertEqual(item["value_action_status"], "proposed")
        self.assertIn("nieuwe voorbeeldopzet", item["value_first_action"])
        self.assertNotIn("gemaakt", item["value_first_action"])
        self.assertEqual(len(item["selected_findings"]), 3)
        self.assertTrue(all(f.get("suggested_improvement") for f in item["selected_findings"]))

    def test_mail_is_three_to_six_specific_points_and_one_cta(self):
        row = candidate_with_evidence(three_evidence())
        item = generate_mails(choose_value_actions(select_reasons({
            "candidates": [row],
        })))["candidates"][0]
        self.assertEqual(item["mail_status"], "ready_for_human_review")
        self.assertEqual(item["copy_validation_status"], "green")
        self.assertLessEqual(len(item["subject"].split()), 8)
        self.assertEqual(item["subject"], item["subject"].casefold())
        self.assertLessEqual(len(item["body"].split()), 320)
        self.assertEqual(item["body"].count("?"), 1)
        for point in item["selected_findings"]:
            self.assertIn(point["observation"], item["body"])
            self.assertIn(point["suggested_improvement"], item["body"])
        self.assertIn(item["value_first_action"], item["body"])
        self.assertFalse(item["automatic_send"])
        self.assertEqual(item["draft_status"], "not_created")

    def test_draft_includes_all_four_to_six_verified_observations(self):
        from outreach_stages import finding_excerpt
        texts = [
            ("Klanten kunnen online een afspraak maken voor onderhoud aan hun fietsen.", "afspraak"),
            ("Vraag online een offerte aan voor maatwerk aan uw elektrische fiets.", "offerte"),
            ("Bestel online onderdelen en kies uw afleveradres bij de bestelling.", "bestel"),
            ("Onze klanten vinden actuele antwoorden in de kennisbank met veelgestelde vragen.", "faq"),
            ("Wij bezorgen en leveren fietsonderdelen op afspraak bij zakelijke klanten.", "bezorg"),
        ]
        candidate = candidate_with_evidence([
            {"text": text, "source_type": "official_site",
             "source_url": "https://acmefietsen.nl/" + route, "page_type": "process"}
            for text, route in texts
        ])
        result = generate_mails(choose_value_actions(select_reasons({"candidates": [candidate]})))
        row = result["candidates"][0]
        self.assertEqual(row["mail_status"], "ready_for_human_review")
        self.assertGreaterEqual(len(row["selected_findings"]), 4)
        for item in row["selected_findings"]:
            self.assertIn(finding_excerpt(item), row["body"])
        self.assertEqual(row["body"].count("?"), 1)
        self.assertLessEqual(len(row["body"].split()), 320)
        self.assertEqual(validate_mail(row, row["subject"], row["body"]), [])

    def test_validator_blocks_fake_created_artifact_meeting_and_roi(self):
        candidate = {
            "verified_observation": "Klanten kunnen online een afspraak aanvragen voor onderhoud.",
            "verified_observation_source_type": "official_site",
            "value_action_status": "proposed",
            "value_first_action": "een korte voorbeeldvariant voor de afspraakroute",
            "public_business_email": "info@acme.nl",
        }
        body = (
            "Hallo, Ik heb alvast een voorbeeld gemaakt. "
            "Dat verhoogt de ROI. Zullen we een meeting plannen?"
        )
        reasons = validate_mail(candidate, "idee voor afspraakroute", body)
        self.assertIn("unsupported_or_robotic_marketing_claim", reasons)
        self.assertIn("requires_three_to_six_sourced_improvements", reasons)
        self.assertIn("value_action_missing_from_body", reasons)

    def test_only_first_party_evidence_can_drive_mail(self):
        payload = {
            "candidates": [
                candidate_with_evidence([
                    {
                        "text": "Klanten kunnen online een afspraak aanvragen voor onderhoud of reparatie.",
                        "source_url": "https://directory.example/acme",
                        "source_type": "directory",
                        "page_type": "process",
                    }
                ])
            ]
        }
        selected = select_reasons(payload)
        self.assertEqual(selected["ready_count"], 0)


if __name__ == "__main__":
    unittest.main()
