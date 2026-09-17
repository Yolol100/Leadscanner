import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import outreach_copy_v17_2 as c


class CuriosityFirstCopyTests(unittest.TestCase):
    def _good(self):
        return c.build_curiosity_first_copy(
            company="Demo Dak",
            language="nl",
            subject="Offerte aanvragen Demo",
            observation='Ik zag op jullie site de route "Offerte aanvragen" direct naast dakrenovatie',
            friction="Dat kan onnodig heen-en-weer opleveren voordat de basisinformatie voor een eerste aanvraag compleet is",
            example_label="mini-flow",
        )

    def test_generator_is_v17_2_3_and_human(self):
        draft = self._good()
        self.assertEqual(c.POLICY_VERSION, "17.2.3")
        self.assertEqual(draft.contract_id, "curiosity_first_v17_2")
        self.assertEqual(c.initial_copy_errors(draft.subject, draft.body), [])
        self.assertIn("één korte flow", draft.body)
        self.assertNotIn("één klein mini-flow", draft.body)
        self.assertNotIn("Demo Dak één", draft.body)

    def test_solution_spoiler_is_blocked(self):
        draft = self._good()
        body = draft.body.replace(
            "Ik heb één korte flow uitgewerkt die dit punt concreet maakt.",
            "Voor jullie zou dat bijvoorbeeld kunnen betekenen: klanten beantwoorden eerst vijf vragen en daarna krijgt het team een complete aanvraag.",
        )
        self.assertTrue(any("full solution" in e for e in c.initial_copy_errors(draft.subject, body)))

    def test_vague_mystery_is_blocked(self):
        draft = self._good()
        body = draft.body.replace('Ik zag op jullie site de route "Offerte aanvragen" direct naast dakrenovatie.', "Ik zag jullie website.")
        self.assertTrue(any("too vague" in e for e in c.initial_copy_errors(draft.subject, body)))

    def test_price_first_touch_is_blocked(self):
        draft = self._good()
        body = draft.body.replace(
            "Ik heb één korte flow uitgewerkt die dit punt concreet maakt.",
            "Ik heb één korte flow voor €750 uitgewerkt die dit punt concreet maakt.",
        )
        self.assertTrue(any("price" in e for e in c.initial_copy_errors(draft.subject, body)))

    def test_discount_first_touch_is_blocked(self):
        draft = self._good()
        body = draft.body.replace("dit punt concreet", "dit punt met korting concreet")
        self.assertTrue(any("price" in e for e in c.initial_copy_errors(draft.subject, body)))

    def test_meeting_first_touch_is_blocked(self):
        draft = self._good()
        body = draft.body.replace("Zal ik het voorbeeld sturen?", "Plan een meeting van 15 minuten.\n\nZal ik het voorbeeld sturen?")
        self.assertTrue(any("meeting" in e for e in c.initial_copy_errors(draft.subject, body)))

    def test_unsupported_severity_is_blocked(self):
        draft = self._good()
        body = draft.body.replace(
            "Dat kan onnodig heen-en-weer opleveren voordat de basisinformatie voor een eerste aanvraag compleet is.",
            "Dit is cruciaal en moet direct gefixt worden voordat iemand verdergaat.",
        )
        self.assertTrue(any("severity or loss" in e for e in c.initial_copy_errors(draft.subject, body)))

    def test_unproven_loss_is_blocked(self):
        draft = self._good()
        body = draft.body.replace(
            "Dat kan onnodig heen-en-weer opleveren voordat de basisinformatie voor een eerste aanvraag compleet is.",
            "Hierdoor verliezen jullie klanten en omzet zonder dat je het ziet.",
        )
        self.assertTrue(any("severity or loss" in e for e in c.initial_copy_errors(draft.subject, body)))

    def test_calibrated_seriousness_is_allowed(self):
        draft = c.build_curiosity_first_copy(
            company="Demo Dak",
            language="nl",
            subject="Offerte aanvragen Demo",
            observation='Ik zag op jullie site de route "Offerte aanvragen" direct naast dakrenovatie',
            friction="Daar viel me één punt op dat ik zelf serieus zou laten checken, omdat het precies op een belangrijk moment in de offerteaanvraag zit",
            example_label="mini-flow",
        )
        self.assertEqual(c.initial_copy_errors(draft.subject, draft.body), [])

    def test_machine_like_request_pricing_is_blocked(self):
        with self.assertRaisesRegex(ValueError, "machine-like label"):
            c.build_curiosity_first_copy(
                company="Teton Machining Solutions",
                language="en",
                subject="Quote request flow",
                observation="I noticed that your site offers request-pricing for CNC machining projects",
                friction="One point there may be creating avoidable friction at an important moment in that process",
                example_label="mini-flow",
                postal_address="Example address",
            )

    def test_humanized_request_pricing_is_allowed(self):
        draft = c.build_curiosity_first_copy(
            company="Teton Machining Solutions",
            language="en",
            subject="Quote request flow",
            observation="I noticed that your site lets customers request pricing for CNC machining projects",
            friction="One point there may be creating avoidable friction at an important moment in that process",
            example_label="mini-flow",
            postal_address="Example address",
        )
        self.assertEqual(c.initial_copy_errors(draft.subject, draft.body), [])

    def test_official_quote_pricing_observation_is_allowed(self):
        draft = c.build_curiosity_first_copy(
            company="Gates Albert",
            language="en",
            subject="Request intake idea",
            observation="I noticed that your quote route asks customers to send a print or describe the part for pricing, lead time and manufacturability feedback",
            friction="One point there is worth checking because it sits at an important moment in that process and may be creating avoidable friction",
            example_label="mini-flow",
            postal_address="Example address",
        )
        self.assertEqual(c.initial_copy_errors(draft.subject, draft.body), [])

    def test_official_faq_guarantee_observation_is_allowed(self):
        draft = c.build_curiosity_first_copy(
            company="MijnIJzerwaren",
            language="nl",
            subject="Sneller naar het antwoord",
            observation="Op jullie site viel me dit op: jullie FAQ behandelt onder meer retourneren en garantie en vermeldt dat maatwerkproducten niet geretourneerd kunnen worden",
            friction="Daar viel me één punt op dat mogelijk onnodige frictie geeft op een belangrijk moment in het serviceproces",
            example_label="mini-flow",
        )
        self.assertEqual(c.initial_copy_errors(draft.subject, draft.body), [])

    def test_scrape_residue_is_blocked(self):
        with self.assertRaisesRegex(ValueError, "scrape or navigation residue"):
            c.build_curiosity_first_copy(
                company="Demo Dak",
                language="nl",
                subject="Offerte aanvragen Demo",
                observation="Skip to content Offerte aanvragen",
                friction="Daar kan onnodige frictie ontstaan",
                example_label="mini-flow",
            )

    def test_language_mix_is_blocked(self):
        draft = self._good()
        body = draft.body.replace(
            "Dat kan onnodig heen-en-weer opleveren voordat de basisinformatie voor een eerste aanvraag compleet is.",
            "I noticed one point in that process.",
        )
        self.assertTrue(any("language mixing" in e for e in c.initial_copy_errors(draft.subject, body)))

    def test_redundant_mini_flow_wording_is_blocked(self):
        draft = self._good()
        body = draft.body.replace("één korte flow", "één klein mini-flow")
        self.assertTrue(any("redundant mini-flow" in e for e in c.initial_copy_errors(draft.subject, body)))

    def test_seller_pricing_claim_without_currency_is_blocked(self):
        draft = self._good()
        body = draft.body.replace(
            "Dat kan onnodig heen-en-weer opleveren voordat de basisinformatie voor een eerste aanvraag compleet is.",
            "Onze pricing is laag en dit kan snel worden opgelost.",
        )
        self.assertTrue(any("price" in e for e in c.initial_copy_errors(draft.subject, body)))

    def test_guarantee_claim_is_blocked(self):
        draft = self._good()
        body = draft.body.replace(
            "Dat kan onnodig heen-en-weer opleveren voordat de basisinformatie voor een eerste aanvraag compleet is.",
            "Wij garanderen resultaat als dit wordt aangepast.",
        )
        self.assertTrue(any("hype" in e for e in c.initial_copy_errors(draft.subject, body)))

    def test_english_unsupported_loss_is_blocked(self):
        with self.assertRaisesRegex(ValueError, "severity or loss"):
            c.build_curiosity_first_copy(
                company="Demo Roofing",
                language="en",
                subject="Quote request flow",
                observation="I noticed the quote request sits directly next to the roof replacement service",
                friction="This is critical and you are losing customers and revenue here",
                example_label="mini-flow",
                postal_address="Example address",
            )

    def test_generic_subject_length_is_blocked(self):
        draft = self._good()
        self.assertTrue(c.initial_copy_errors("Vraag", draft.body))

    def test_followup_stays_permission_only(self):
        draft = self._good()
        self.assertEqual(c.followup_copy_errors(draft.followup_body), [])


if __name__ == "__main__":
    unittest.main()
