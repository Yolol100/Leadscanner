from __future__ import annotations

import unittest

from prepare_growth_batch import build_opening, exact_nl_opening_from_existing, infer_focus_from_observation, prepare_batch, subject_for_company


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
            "verified_observation": "Fysiotherapie in Utrecht" if language == "nl" else "Physical therapy in Utrecht",
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
            ('Op jullie website staat “Fysiotherapie in Utrecht”. Met één compact Groeiabonnement help ik bedrijven.', "Ik zag op jullie website dat Fysiotherapie in Utrecht."),
            ('Op jullie website zag ik “Fysiotherapie in Utrecht”.', "Ik zag op jullie website dat Fysiotherapie in Utrecht."),
            ('Ik heb de website van Voorbeeld Fysio bekeken en zag “Fysiotherapie in Utrecht”. Ik heb een idee om jullie online aanpak sterker te maken.', "Ik zag op jullie website dat Fysiotherapie in Utrecht."),
            ('Ik kwam Voorbeeld Fysio tegen en heb jullie website bekeken. Eén detail dat opviel was “Fysiotherapie in Utrecht”. Mijn idee voor Voorbeeld Fysio: website en content laten samenwerken.', "Ik zag op jullie website dat Fysiotherapie in Utrecht."),
            ('Ik zag dat Voorbeeld Fysio zich richt op fysiotherapie. Ik heb een idee om jullie online aanpak sterker te maken.', "Ik zag op jullie website dat Voorbeeld Fysio zich richt op fysiotherapie."),
            ('Ik kwam Voorbeeld Fysio tegen en heb jullie website bekeken. Jullie site draait duidelijk om fysiotherapie. Mijn idee voor Voorbeeld Fysio: website en content laten samenwerken.', "Ik zag op jullie website dat Voorbeeld Fysio zich richt op fysiotherapie."),
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
        contact["verified_observation"] = "Fysiotherapie in Utrecht"
        opening = build_opening(
            "Voorbeeld Fysiotherapie",
            "nl",
            contact["verified_observation"],
            contact["category_hint"],
        )
        self.assertEqual(opening, "Wat me opviel op jullie website: Fysiotherapie in Utrecht.")

    def test_review_required_contact_becomes_personal_review_draft(self):
        row = prepare_batch({"candidates": [self.contact()]}, self.config(), draft_limit=1)["rows"][0]
        self.assertEqual(row["status"], "review_draft")
        self.assertTrue(row["lead_id"].startswith("growth-"))
        self.assertEqual(row["subject"], "Idee voor Voorbeeld Fysiotherapie")
        self.assertEqual(row["copy_company_label"], "Voorbeeld Fysiotherapie")
        self.assertTrue(row["body"].startswith("Hallo,\n\n"))
        self.assertIn(
            "Ik zag op jullie website dat Fysiotherapie in Utrecht.",
            row["body"],
        )
        self.assertIn(
            "Met mijn Groeiabonnement kan ik meerdere onderdelen van jullie online aanpak oppakken:",
            row["body"],
        )
        self.assertIn("Geen interesse? Laat het gerust weten.", row["body"])
        self.assertNotIn("Op jullie website staat", row["body"])
        self.assertEqual(row["verified_observation_source_type"], "official_site")
        bullets = [line for line in row["body"].splitlines() if line.startswith("• ")]
        self.assertEqual(len(bullets), 6)
        for value in (
            "€250–€500 per maand, afhankelijk van wat jullie nodig hebben",
            "voorbeeld design maken voor Voorbeeld Fysiotherapie",
            "Groet,\nAndrew",
        ):
            self.assertIn(value, row["body"])
        self.assertNotIn("30%", row["body"])
        self.assertNotIn("Webactueel B.V.", row["body"])

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
        contact["verified_observation"] = "À LA CARTE RESTAURANT"
        row = prepare_batch({"candidates": [contact]}, self.config(), draft_limit=1)["rows"][0]
        self.assertIn("Ik zag op jullie website dat À LA CARTE RESTAURANT.", row["body"])
        self.assertNotIn("sieraden en juwelierswerk", row["body"])

    def test_pass_contact_becomes_draft_ready(self):
        row = prepare_batch(
            {"candidates": [self.contact(language="en", basis="pass")]},
            self.config(),
            draft_limit=1,
        )["rows"][0]
        self.assertEqual(row["status"], "draft_ready")
        self.assertEqual(row["subject"], "An idea for Example Physiotherapy")
        self.assertIn(
            "What stood out to me on your website: Physical therapy in Utrecht.",
            row["body"],
        )
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
            self.assertLessEqual(len(row["subject"].split()), 6)
            self.assertLessEqual(len(row["body"].split()), 125)

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
            "Idee voor Steakhouse The Longhorn Rib",
        )

    def test_body_company_label_never_ends_in_connector(self):
        contact = self.contact()
        contact["name_hint"] = "Steakhouse The Longhorn Rib and"
        contact["category_hint"] = "restaurant"
        contact["verified_observation"] = "Steakhouse met grillgerechten in Utrecht"
        row = prepare_batch({"candidates": [contact]}, self.config(), draft_limit=1)["rows"][0]
        self.assertEqual(row["copy_company_label"], "Steakhouse The Longhorn Rib")
        self.assertIn("voorbeeld design maken voor Steakhouse The Longhorn Rib?", row["body"])
        self.assertNotIn("Rib and?", row["body"])

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
        first["verified_observation"] = "Fysiotherapie in Utrecht"
        second["verified_observation"] = "Revalidatie en dry needling in Utrecht"
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
        offer_a = body_a.split(
            "Met mijn Groeiabonnement kan ik meerdere onderdelen van jullie online aanpak oppakken:",
            1,
        )[1]
        offer_b = body_b.split(
            "Met mijn Groeiabonnement kan ik meerdere onderdelen van jullie online aanpak oppakken:",
            1,
        )[1]
        self.assertEqual(offer_a, offer_b)

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
