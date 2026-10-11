import unittest

from outreach_stages import (
    choose_value_actions,
    generate_mails,
    generate_sequence_facts,
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


class OutreachStagesTests(unittest.TestCase):
    def test_future_first_mail_uses_verified_fact_action_and_one_soft_cta(self):
        samples=[
            ("nl","Op onze site kunnen klanten online een afspraak maken.","een korte voorbeeldvariant voor de afspraakroute"),
            ("en","Customers can book appointments directly on our website.","a short example for the appointment flow"),
        ]
        for lang,obs,action in samples:
            mail=body_for({"language":lang,"verified_observation":obs,
                           "value_first_action":action})
            self.assertIn(obs,mail)
            self.assertIn(action,mail)
            self.assertEqual(mail.count("?"),1)
            self.assertIn("Andrew Baeten",mail)
            self.assertNotIn("Andrew\\n",mail)
            self.assertLess(len(mail.split()),100)
            self.assertNotIn("ROI",mail)
            self.assertNotIn("guarantee",mail.lower())


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
        site_context = [
            {
                "text": "Onze klanten kunnen online een afspraak aanvragen voor het ophalen van bloemen.",
                "source_url": "https://example.nl/afhalen",
                "source_type": "official_site", "page_type": "process",
            },
            {
                "text": "Wij verzorgen vanuit onze winkel een bezorgservice voor alle bezoekers.",
                "source_url": "https://example.nl/diensten",
                "source_type": "official_site", "page_type": "services",
            },
        ]
        candidate = {
            "research_status": "ready", "official_domain": "example.nl",
            "evidence_candidates": [{
                "text": ambiguous, "source_type": "official_site",
                "source_url": "https://example.nl/bezoek", "page_type": "detail",
            }] + site_context,
        }
        self.assertEqual(detect_language(candidate, ambiguous), "nl")
        selected = select_one_reason(candidate)
        self.assertEqual(selected["outreach_status"], "ready")
        self.assertEqual(selected["language"], "nl")

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

    def test_generated_first_mail_has_only_andrew_baeten_branding(self):
        from outreach_stages import body_for
        for language, observation, action in (
            ("nl", "Klanten kunnen online een afspraak maken.",
             "een korte voorbeeldvariant voor de afspraakroute"),
            ("en", "Customers can book an appointment online.",
             "a short example for the booking flow"),
        ):
            body = body_for({"language": language,
                             "verified_observation": observation,
                             "value_first_action": action})
            self.assertEqual(body.count("Andrew Baeten"), 1)
            self.assertTrue(body.endswith("Andrew Baeten"))
            self.assertEqual(body.count("?"), 1)

    def test_sequence_facts_skip_per_lead_mail_generation(self):
        source = {
            "public_business_email": "info@example.nl",
            "outreach_status": "ready",
            "value_action_status": "proposed",
            "verified_observation_source_type": "official_site",
            "verified_observation": "Klanten kunnen een afspraak aanvragen.",
            "verified_observation_source_url": "https://example.nl/afspraak",
            "value_first_action": "een korte voorbeeldvariant",
            "signal_type": "appointment",
        }
        report = generate_sequence_facts({"candidates": [source]})
        self.assertEqual(report["ready_for_human_review_count"], 1)
        self.assertEqual(report["review_mode"], "instantly_sequence")
        row = report["candidates"][0]
        self.assertEqual(row["mail_status"], "ready_for_sequence_review")
        self.assertIsNone(row["subject"])
        self.assertIsNone(row["body"])
        self.assertFalse(row["automatic_send"])

    def test_missing_email_does_not_hide_site_opportunity_but_holds_mail(self):
        candidate = candidate_with_evidence([{
            "text": "Klanten kunnen online een afspraak aanvragen via onze website.",
            "source_url": "https://acmefietsen.nl/afspraak",
            "source_type": "official_site",
            "page_type": "process",
        }])
        candidate["public_business_email"] = None
        candidate["contact_status"] = "no_public_contact_found"
        opportunities = select_reasons({"candidates": [candidate]})
        self.assertEqual(opportunities["ready_count"], 1)
        valued = choose_value_actions(opportunities)
        mails = generate_mails(valued)
        self.assertEqual(mails["ready_for_human_review_count"], 0)
        self.assertEqual(
            mails["candidates"][0]["copy_validation_reasons"], ["no_published_business_contact"]
        )
        self.assertIsNone(mails["candidates"][0]["body"])
        facts = generate_sequence_facts(valued)
        self.assertEqual(facts["ready_for_human_review_count"], 0)

    def test_named_owner_receives_personalized_greeting_not_generic_mailbox(self):
        candidate = candidate_with_evidence([{
            "text": "Klanten kunnen online een afspraak aanvragen via onze website.",
            "source_url": "https://acmefietsen.nl/afspraak",
            "source_type": "official_site",
            "page_type": "process",
        }])
        candidate["public_business_email"] = "jan@acmefietsen.nl"
        candidate["contact_person_name"] = "Jan Jansen"
        candidate["contact_role"] = "named_owner"
        candidate["contact_status"] = "verified_official_site"
        result = generate_mails(choose_value_actions(select_reasons({"candidates": [candidate]})))
        row = result["candidates"][0]
        self.assertEqual(row["mail_status"], "ready_for_human_review")
        self.assertTrue(row["body"].startswith("Hoi Jan,\n\n"))
        self.assertFalse(row["automatic_send"])

    def test_sequence_facts_hold_without_official_evidence(self):
        source = {
            "outreach_status": "ready",
            "value_action_status": "proposed",
            "verified_observation_source_type": "directory",
            "verified_observation": "Example",
            "verified_observation_source_url": "https://example.nl",
            "value_first_action": "een voorbeeld",
            "signal_type": "appointment",
        }
        report = generate_sequence_facts({"candidates": [source]})
        self.assertEqual(report["ready_for_human_review_count"], 0)
        self.assertEqual(report["candidates"][0]["mail_status"], "hold")


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
        payload = {
            "candidates": [
                candidate_with_evidence([
                    {
                        "text": "Onze werkplaats biedt onderhoud en reparatie voor verschillende soorten fietsen.",
                        "source_url": "https://acmefietsen.nl/diensten",
                        "source_type": "official_site",
                        "page_type": "services",
                    },
                    {
                        "text": "Klanten kunnen online een werkplaatsafspraak aanvragen voor onderhoud of reparatie.",
                        "source_url": "https://acmefietsen.nl/afspraak",
                        "source_type": "official_site",
                        "page_type": "process",
                    },
                ])
            ]
        }
        result = select_reasons(payload)
        item = result["candidates"][0]
        self.assertEqual(item["outreach_status"], "ready")
        self.assertEqual(item["signal_type"], "appointment")
        self.assertIn("werkplaatsafspraak", item["verified_observation"])
        self.assertEqual(item["reason_for_outreach"], item["verified_observation"])

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

    def test_concrete_quote_request_is_ready(self):
        payload = {
            "candidates": [
                candidate_with_evidence([
                    {
                        "text": "Vraag online een offerte aan via het formulier voor uw schilderwerk.",
                        "source_url": "https://acmefietsen.nl/offerte",
                        "source_type": "official_site",
                        "page_type": "process",
                    }
                ])
            ]
        }
        result = select_reasons(payload)
        self.assertEqual(result["ready_count"], 1)
        self.assertEqual(result["candidates"][0]["signal_type"], "quote_request")

    def test_reservation_and_ordering_signals_are_ready(self):
        cases = [
            (
                "Reserveer online een tafel voor vanavond via onze reserveringspagina.",
                "https://acmefietsen.nl/reserveren",
                "reservation",
            ),
            (
                "Bestel online uw maaltijd en kies daarna het gewenste afhaalmoment.",
                "https://acmefietsen.nl/bestellen",
                "ordering",
            ),
        ]
        for text, source_url, expected in cases:
            with self.subTest(signal=expected):
                payload = {
                    "candidates": [
                        candidate_with_evidence([
                            {
                                "text": text,
                                "source_url": source_url,
                                "source_type": "official_site",
                                "page_type": "process",
                            }
                        ])
                    ]
                }
                result = select_reasons(payload)
                self.assertEqual(result["ready_count"], 1)
                self.assertEqual(result["candidates"][0]["signal_type"], expected)

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
        selected = select_reasons({
            "candidates": [
                candidate_with_evidence([
                    {
                        "text": "Klanten kunnen online een werkplaatsafspraak aanvragen voor onderhoud of reparatie.",
                        "source_url": "https://acmefietsen.nl/afspraak",
                        "source_type": "official_site",
                        "page_type": "process",
                    }
                ])
            ]
        })
        result = choose_value_actions(selected)
        item = result["candidates"][0]
        self.assertEqual(item["value_action_status"], "proposed")
        self.assertIn("voorbeeldvariant", item["value_first_action"])
        self.assertNotIn("gemaakt", item["value_first_action"])

    def test_mail_is_short_specific_and_one_cta(self):
        selected = select_reasons({
            "candidates": [
                candidate_with_evidence([
                    {
                        "text": "Klanten kunnen online een werkplaatsafspraak aanvragen voor onderhoud of reparatie.",
                        "source_url": "https://acmefietsen.nl/afspraak",
                        "source_type": "official_site",
                        "page_type": "process",
                    }
                ])
            ]
        })
        valued = choose_value_actions(selected)
        result = generate_mails(valued)
        item = result["candidates"][0]
        self.assertEqual(item["mail_status"], "ready_for_human_review")
        self.assertEqual(item["copy_validation_status"], "green")
        self.assertLessEqual(len(item["subject"].split()), 8)
        self.assertEqual(item["subject"], item["subject"].casefold())
        self.assertLessEqual(len(item["body"].split()), 100)
        self.assertEqual(item["body"].count("?"), 1)
        self.assertIn(item["verified_observation"], item["body"])
        self.assertIn(item["value_first_action"], item["body"])
        self.assertNotIn("meeting", item["body"].lower())
        self.assertNotIn("€", item["body"])
        self.assertFalse(item["automatic_send"])
        self.assertEqual(item["draft_status"], "not_created")

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
        self.assertIn("unsupported_or_high_friction_claim", reasons)
        self.assertIn("verified_observation_missing_from_body", reasons)
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
