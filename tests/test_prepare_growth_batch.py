from __future__ import annotations

import unittest

from prepare_growth_batch import build_opening, build_short_first_touch, build_short_first_touch_from_opening, exact_nl_opening_from_existing, infer_focus_from_observation, observation_is_low_signal, prepare_batch, subject_for_company


class GrowthBatchTests(unittest.TestCase):
    def config(self):
        return {"monthly_price_eur": {"min": 250, "max": 500}}

    def contact(self, language="nl", basis="review_required"):
        return {
            "name_hint": "Voorbeeld Fysiotherapie" if language == "nl" else "Example Physiotherapy",
            "website_hint": "https://voorbeeld.nl" if language == "nl" else "https://example.com",
            "category_hint": "physical_medicine_and_rehabilitation",
            "official_domain_hint": "voorbeeld.nl" if language == "nl" else "example.com",
            "public_business_emails": ["info@voorbeeld.nl" if language == "nl" else "sales@example.com"],
            "email_source_urls": ["https://voorbeeld.nl/contact"],
            "email_source_types": ["official_site"],
            "email_source_refs": ["https://voorbeeld.nl/contact"],
            "verified_observation": "Wij bieden fysiotherapie in Utrecht." if language == "nl" else "We provide physical therapy in Utrecht.",
            "verified_observation_source_url": "https://voorbeeld.nl" if language == "nl" else "https://example.com",
            "verified_observation_source_type": "official_site",
            "language": language,
            "language_source": "html_lang",
            "excluded_competitor": False,
            "contact_basis_status": basis,
            "contact_basis_hint": "public_email_review_required",
        }

    def test_exact_nl_opening_recovers_legacy_verified_fact_forms(self):
        cases = (
            ('Op jullie website staat “Wij bieden fysiotherapie in Utrecht.”. Met één compact Groeiabonnement help ik bedrijven.', "Ik zag op jullie website dat jullie fysiotherapie in Utrecht aanbieden."),
            ('Op jullie website zag ik “Wij bieden fysiotherapie in Utrecht.”.', "Ik zag op jullie website dat jullie fysiotherapie in Utrecht aanbieden."),
            ('Ik heb de website van Voorbeeld Fysio bekeken en zag “Wij bieden fysiotherapie in Utrecht.”. Ik heb een idee om jullie online aanpak sterker te maken.', "Ik zag op jullie website dat jullie fysiotherapie in Utrecht aanbieden."),
            ('Ik kwam Voorbeeld Fysio tegen en heb jullie website bekeken. Eén detail dat opviel was “Wij bieden fysiotherapie in Utrecht.”. Mijn idee voor Voorbeeld Fysio: website en content laten samenwerken.', "Ik zag op jullie website dat jullie fysiotherapie in Utrecht aanbieden."),
        )
        for opening, expected in cases:
            with self.subTest(opening=opening):
                self.assertEqual(
                    exact_nl_opening_from_existing(opening, "Voorbeeld Fysio"),
                    expected,
                )

    def test_exact_nl_opening_rejects_legacy_copy_without_verified_fact(self):
        with self.assertRaisesRegex(ValueError, "unsupported existing Dutch verified opening"):
            exact_nl_opening_from_existing(
                "Ik kwam Voorbeeld Fysio online tegen. Met één compact Groeiabonnement help ik bedrijven.",
                "Voorbeeld Fysio",
            )

    def test_specific_verified_observation_is_used_in_opening(self):
        contact = self.contact()
        contact["verified_observation"] = "Wij bieden fysiotherapie in Utrecht."
        opening = build_opening(
            "Voorbeeld Fysiotherapie",
            "nl",
            contact["verified_observation"],
            contact["category_hint"],
        )
        self.assertEqual(opening, "Ik zag op jullie website dat jullie fysiotherapie in Utrecht aanbieden.")

    def test_review_required_contact_becomes_personal_review_draft(self):
        row = prepare_batch({"candidates": [self.contact()]}, self.config(), draft_limit=1)["rows"][0]
        self.assertEqual(row["status"], "review_draft")
        self.assertTrue(row["lead_id"].startswith("growth-"))
        self.assertEqual(row["subject"], "idee voor voorbeeld fysiotherapie")
        self.assertEqual(row["copy_company_label"], "Voorbeeld Fysiotherapie")
        self.assertTrue(row["body"].startswith("Hallo,\n\n"))
        self.assertIn("Jullie zijn actief in fysiotherapie en revalidatie.", row["body"])
        self.assertIn("Wat me opviel: jullie bieden fysiotherapie in Utrecht.", row["body"])
        self.assertIn(
            "Zal ik vrijblijvend een voorbeeld laten zien hoe dit er voor jullie uit kan zien?",
            row["body"],
        )
        self.assertIn("Geen interesse? Laat het gerust weten.", row["body"])
        self.assertLessEqual(len(row["body"].split()), 100)
        self.assertNotIn("€", row["body"])
        self.assertNotIn("• ", row["body"])
        self.assertNotIn("40%", row["body"])
        self.assertEqual(row["verified_observation_source_type"], "official_site")


    def test_short_copy_never_invents_problem_or_result(self):
        subject, body = build_short_first_touch(
            "Voorbeeld Fysiotherapie",
            "nl",
            "Wij bieden fysiotherapie in Utrecht.",
        )
        self.assertEqual(subject, "idee voor voorbeeld fysiotherapie")
        self.assertNotRegex(body, r"\b(meer omzet|meer intakes|verliest|mist|40%|8 weken)\b")
        self.assertNotIn("€", body)
        self.assertNotIn("• ", body)

    def test_social_proof_requires_verified_source(self):
        with self.assertRaisesRegex(ValueError, "social_proof_requires_verified_source"):
            build_short_first_touch(
                "Voorbeeld Fysiotherapie",
                "nl",
                "Wij bieden fysiotherapie in Utrecht.",
                proof_text="Een vergelijkbare praktijk kreeg 40% meer intakes.",
            )

    def test_verified_social_proof_can_be_rendered(self):
        _subject, body = build_short_first_touch(
            "Voorbeeld Fysiotherapie",
            "nl",
            "Wij bieden fysiotherapie in Utrecht.",
            proof_text="Bij een vergelijkbare praktijk steeg het aantal online intakes met 24%.",
            proof_source_url="https://example.com/case",
        )
        self.assertIn("24%", body)
        self.assertLessEqual(len(body.split()), 100)

    def test_verified_contact_name_requires_source(self):
        with self.assertRaisesRegex(ValueError, "contact_name_requires_verified_source"):
            build_short_first_touch(
                "Voorbeeld Fysiotherapie",
                "nl",
                "Wij bieden fysiotherapie in Utrecht.",
                contact_name="Marieke",
            )

    def test_existing_opening_migrates_without_price_or_features(self):
        subject, body = build_short_first_touch_from_opening(
            "Idee voor Voorbeeld Fysiotherapie",
            "Ik zag op jullie website dat jullie fysiotherapie in Utrecht aanbieden.",
            "nl",
        )
        self.assertEqual(subject, "idee voor voorbeeld fysiotherapie")
        self.assertIn("Jullie zijn actief in fysiotherapie en revalidatie.", body)
        self.assertIn(
            "Wat me opviel: op jullie website staat dat jullie fysiotherapie in Utrecht aanbieden.",
            body,
        )
        self.assertNotIn("€", body)
        self.assertNotIn("• ", body)
        self.assertLessEqual(len(body.split()), 100)

    def test_low_signal_observation_blocks_instead_of_inventing_focus(self):
        contact = self.contact()
        contact["name_hint"] = "030 Fietsen – Tweedehands Fietsen Utrecht"
        contact["verified_observation"] = "Home - 030 Fietsen"
        with self.assertRaisesRegex(
            ValueError,
            "No specific verified site detail",
        ):
            prepare_batch(
                {"candidates": [contact]},
                self.config(),
                draft_limit=1,
            )

    def test_weak_observation_without_reliable_fact_blocks_copy(self):
        contact = self.contact()
        contact["name_hint"] = "Acme BV"
        contact["category_hint"] = None
        contact["verified_observation"] = "Nu tot 30% voordeel op geselecteerde producten"
        with self.assertRaisesRegex(
            ValueError,
            "No specific verified site detail",
        ):
            prepare_batch(
                {"candidates": [contact]},
                self.config(),
                draft_limit=1,
            )

    def test_observation_overrides_misleading_company_name_for_focus(self):
        contact = self.contact()
        contact["name_hint"] = "De Juwelier"
        contact["verified_observation"] = "Wij serveren à la carte gerechten."
        row = prepare_batch({"candidates": [contact]}, self.config(), draft_limit=1)["rows"][0]
        self.assertIn("Ik zag op jullie website dat jullie à la carte gerechten serveren.", row["body"])
        self.assertNotIn("sieraden en juwelierswerk", row["body"])

    def test_pass_contact_becomes_draft_ready(self):
        row = prepare_batch(
            {"candidates": [self.contact(language="en", basis="pass")]},
            self.config(),
            draft_limit=1,
        )["rows"][0]
        self.assertEqual(row["status"], "draft_ready")
        self.assertEqual(row["subject"], "an idea for example physiotherapy")
        self.assertIn("You operate in physical therapy and rehabilitation.", row["body"])
        self.assertIn("What stood out: you provide physical therapy in Utrecht.", row["body"])
        self.assertIn(
            "Would you like me to show you a no-obligation example of what this could look like for you?",
            row["body"],
        )
        self.assertNotIn("€", row["body"])
        self.assertNotIn("• ", row["body"])
        self.assertLessEqual(len(row["body"].split()), 100)

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
            self.assertLessEqual(len(row["body"].split()), 100)
            self.assertLessEqual(len(row["subject"].split()), 6)
            self.assertLessEqual(len(row["body"].split()), 100)

    def test_long_company_uses_personal_short_label(self):
        self.assertEqual(
            subject_for_company("030 Fietsen – Tweedehands Fietsen Utrecht elektrische fietsen", "nl"),
            "idee voor 030 fietsen",
        )

    def test_long_company_without_separator_keeps_personal_subject(self):
        row = prepare_batch(
            {"candidates": [{**self.contact(), "name_hint": "Kindergarden Voormalige Stadstimmertuin Amsterdam"}]},
            self.config(),
            draft_limit=1,
        )["rows"][0]
        self.assertEqual(row["copy_subject_label"], "Kindergarden Voormalige Stadstimmertuin Amsterdam")
        self.assertEqual(row["subject"], "idee voor kindergarden voormalige stadstimmertuin amsterdam")
        self.assertNotIn("jullie online aanpak", row["subject"])

    def test_low_signal_observation_does_not_turn_category_hint_into_site_claim(self):
        contact = self.contact()
        contact["name_hint"] = "David Lloyd Amsterdam"
        contact["verified_observation"] = "Welkom bij David Lloyd Amsterdam"
        contact["category_hint"] = "gym"
        with self.assertRaisesRegex(
            ValueError,
            "No specific verified site detail",
        ):
            prepare_batch(
                {"candidates": [contact]},
                self.config(),
                draft_limit=1,
            )

    def test_subject_trims_connector_even_without_word_limit_truncation(self):
        self.assertEqual(
            subject_for_company("Steakhouse The Longhorn Rib and", "nl"),
            "idee voor steakhouse the longhorn rib",
        )

    def test_body_company_label_never_ends_in_connector(self):
        contact = self.contact()
        contact["name_hint"] = "Steakhouse The Longhorn Rib and"
        contact["category_hint"] = "restaurant"
        contact["verified_observation"] = "Wij serveren grillgerechten in Utrecht."
        row = prepare_batch({"candidates": [contact]}, self.config(), draft_limit=1)["rows"][0]
        self.assertEqual(row["copy_company_label"], "Steakhouse The Longhorn Rib")
        self.assertNotIn("Rib and?", row["body"])
        self.assertIn("Zal ik vrijblijvend een voorbeeld laten zien", row["body"])

    def test_ambiguous_heading_does_not_turn_category_into_site_claim(self):
        contact = self.contact()
        contact["name_hint"] = "Camping Ganspoort"
        contact["category_hint"] = "restaurant"
        contact["verified_observation"] = "Welkom op de Camping!"
        with self.assertRaisesRegex(
            ValueError,
            "No specific verified site detail",
        ):
            prepare_batch(
                {"candidates": [contact]},
                self.config(),
                draft_limit=1,
            )

    def test_substring_false_positives_do_not_assign_business_focus(self):
        self.assertIsNone(infer_focus_from_observation("Hoogvliet Houten", "nl"))
        self.assertIsNone(infer_focus_from_observation("De Bloemhof", "nl"))
        self.assertEqual(
            infer_focus_from_observation("Dierenkliniek Oog in Al", "nl"),
            "dierenzorg",
        )
        self.assertIsNone(infer_focus_from_observation("Het Goudkantoor", "nl"))
        self.assertIsNone(infer_focus_from_observation("De Orchidee", "nl"))
        self.assertIsNone(infer_focus_from_observation("Plato", "nl"))
        self.assertIsNone(infer_focus_from_observation("Gewoon een goede service", "nl"))
        self.assertIsNone(infer_focus_from_observation("Grill", "nl"))
        self.assertEqual(
            infer_focus_from_observation("Hengelsport en fishing tackle", "nl"),
            "hengelsport en visbenodigdheden",
        )

    def test_supermarket_category_hint_does_not_replace_verified_site_fact(self):
        with self.assertRaisesRegex(
            ValueError,
            "No specific verified site detail",
        ):
            build_opening(
                "Hoogvliet Houten",
                "nl",
                "Welkom bij Hoogvliet Houten",
                "supermarket",
            )

    def test_subject_removes_decorative_emoji_and_avoids_dangling_connector(self):
        self.assertEqual(subject_for_company("Piccola Italia 🇮🇹", "nl"), "Idee voor Piccola Italia")
        self.assertEqual(subject_for_company("Bistro De Buik Van Parijs | Zwolle", "nl"), "Idee voor Bistro De Buik")
        self.assertEqual(subject_for_company("Busch & van der Worp", "nl"), "Idee voor Busch")


    def test_canonical_nl_growth_template_bullets_are_fixed(self):
        row = prepare_batch(
            {"candidates": [self.contact(language="nl")]},
            self.config(),
            draft_limit=1,
        )["rows"][0]
        bullets = [
            line
            for line in row["body"].splitlines()
            if line.startswith("• ")
        ]
        self.assertEqual(
            bullets,
            [
                "• Website/webshop — verbeteren of nieuw maken waar nodig",
                "• Zoekbaarheid — beter vindbaar worden",
                "• Social content — passende content",
                "• Automatisering — geschikte processen deels automatiseren waar haalbaar",
                "• Hosting — beheren of overnemen waar passend",
                "• Ik als vast contactpersoon",
            ],
        )

    def test_canonical_en_growth_template_bullets_are_fixed(self):
        row = prepare_batch(
            {"candidates": [self.contact(language="en")]},
            self.config(),
            draft_limit=1,
        )["rows"][0]
        bullets = [
            line
            for line in row["body"].splitlines()
            if line.startswith("• ")
        ]
        self.assertEqual(
            bullets,
            [
                "• Website/webshop — improve or build new where needed",
                "• Search visibility — improve findability",
                "• Social content — relevant content",
                "• Automation — partially automate suitable processes where feasible",
                "• Hosting — manage or take over where appropriate",
                "• Me as your fixed point of contact",
            ],
        )

    def test_verified_fact_changes_opening_not_growth_offer(self):
        first = self.contact(language="nl")
        second = self.contact(language="nl")
        first["verified_observation"] = "Wij bieden fysiotherapie in Utrecht."
        second["verified_observation"] = "Wij bieden revalidatie en dry needling in Utrecht."
        body_a = prepare_batch(
            {"candidates": [first]},
            self.config(),
            draft_limit=1,
        )["rows"][0]["body"]
        body_b = prepare_batch(
            {"candidates": [second]},
            self.config(),
            draft_limit=1,
        )["rows"][0]["body"]
        self.assertNotEqual(body_a, body_b)
        self.assertIn(
            "Voor fysiotherapie en revalidatie brengt mijn Groeiabonnement website, vindbaarheid, content, automatisering en hosting samen met één vast aanspreekpunt:",
            body_a,
        )
        self.assertIn(
            "Voor fysiotherapie en revalidatie brengt mijn Groeiabonnement website, vindbaarheid, content, automatisering en hosting samen met één vast aanspreekpunt:",
            body_b,
        )
        offer_a = body_a.split("• Website/webshop — verbeteren of nieuw maken waar nodig", 1)[1]
        offer_b = body_b.split("• Website/webshop — verbeteren of nieuw maken waar nodig", 1)[1]
        self.assertEqual(offer_a, offer_b)

    def test_value_sentence_uses_verified_observation_focus_only(self):
        self.assertEqual(
            build_value_sentence("Wij bieden fysiotherapie in Utrecht.", "nl"),
            "Voor fysiotherapie en revalidatie brengt mijn Groeiabonnement website, vindbaarheid, content, automatisering en hosting samen met één vast aanspreekpunt:",
        )
        self.assertEqual(
            build_value_sentence("We provide physical therapy in Utrecht.", "en"),
            "For physical therapy and rehabilitation, my Growth Subscription brings website, search visibility, content, automation and hosting together with one fixed point of contact:",
        )

    def test_value_sentence_falls_back_when_verified_observation_has_no_reliable_focus(self):
        self.assertEqual(
            build_value_sentence("Wij leveren industriële componenten.", "nl"),
            "Met mijn Groeiabonnement kan ik meerdere onderdelen van jullie online aanpak oppakken:",
        )

    def test_category_hint_never_creates_relevance_sentence(self):
        contact = self.contact()
        contact["name_hint"] = "Voorbeeld BV"
        contact["category_hint"] = "restaurant"
        contact["verified_observation"] = "Wij leveren industriële componenten."
        row = prepare_batch({"candidates": [contact]}, self.config(), draft_limit=1)["rows"][0]
        self.assertIn(
            "Met mijn Groeiabonnement kan ik meerdere onderdelen van jullie online aanpak oppakken:",
            row["body"],
        )
        self.assertNotIn("restaurant en gastvrijheid", row["body"])

    def test_template_follows_growth_policy_order_and_single_offer(self):
        row = prepare_batch({"candidates": [self.contact()]}, self.config())["rows"][0]
        body = row["body"]
        bullets = [line for line in body.splitlines() if line.startswith("• ")]
        self.assertEqual(len(bullets), 6)
        self.assertLess(body.index(bullets[0]), body.index("€250–€500 per maand"))
        self.assertIn("Website/webshop — verbeteren of nieuw maken waar nodig", body)
        self.assertIn("Zoekbaarheid — beter vindbaar worden", body)
        self.assertIn("voorbeeld design maken voor Voorbeeld Fysiotherapie", body)
        self.assertIn("richting interessant is", body)
        self.assertNotIn("30%", body)
        self.assertNotIn("meeting", body.casefold())

    def test_non_business_observations_are_low_signal(self):
        observations = (
            "Product toegevoegd aan jouw offerte.",
            "Samen werken aan jouw talent!",
            "Prima locatie, maar te klein. Dank.",
        )
        for observation in observations:
            self.assertTrue(
                observation_is_low_signal(
                    "Voorbeeld BV", observation
                )
            )

    def test_navigation_labels_are_low_signal(self):
        for observation in (
            "Contact",
            "Openingstijden",
            "Route en adres",
            "Vacatures",
            "Privacybeleid",
        ):
            contact = self.contact()
            contact["name_hint"] = "Acme BV"
            contact["category_hint"] = None
            contact["verified_observation"] = observation
            with self.subTest(observation=observation):
                with self.assertRaisesRegex(
                    ValueError,
                    "No specific verified site detail",
                ):
                    prepare_batch(
                        {"candidates": [contact]},
                        self.config(),
                        draft_limit=1,
                    )

    def test_temporary_campaign_heading_is_low_signal(self):
        contact = self.contact()
        contact["name_hint"] = "Acme BV"
        contact["category_hint"] = None
        contact["verified_observation"] = "Tijdelijk voordeel op geselecteerde producten"
        with self.assertRaisesRegex(
            ValueError,
            "No specific verified site detail",
        ):
            prepare_batch(
                {"candidates": [contact]},
                self.config(),
                draft_limit=1,
            )

    def test_weak_website_titles_block_copy(self):
        contact = self.contact()
        contact["name_hint"] = "KU Kitchen & Bar"
        contact["verified_observation"] = "🔒 Beveiligde Website"
        with self.assertRaisesRegex(
            ValueError,
            "No specific verified site detail",
        ):
            prepare_batch(
                {"candidates": [contact]},
                self.config(),
            )


if __name__ == "__main__":
    unittest.main()

