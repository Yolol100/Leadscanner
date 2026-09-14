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

    def test_generator_is_curiosity_first(self):
        draft = self._good()
        self.assertEqual(draft.contract_id, "curiosity_first_v17_2")
        self.assertEqual(c.initial_copy_errors(draft.subject, draft.body), [])
        self.assertIn("één klein mini-flow", draft.body)
        self.assertIn("Zal ik het voorbeeld sturen?", draft.body)
        self.assertNotIn("zou dat bijvoorbeeld kunnen betekenen:", draft.body.casefold())
        self.assertNotIn("klanten beantwoorden", draft.body.casefold())

    def test_solution_spoiler_is_blocked(self):
        draft = self._good()
        body = draft.body.replace(
            "Ik heb voor Demo Dak één klein mini-flow gemaakt dat de mogelijke verbetering concreet maakt.",
            "Voor jullie zou dat bijvoorbeeld kunnen betekenen: klanten beantwoorden eerst vijf vragen en daarna krijgt het team een complete aanvraag.",
        )
        errors = c.initial_copy_errors(draft.subject, body)
        self.assertTrue(any("full solution" in error for error in errors))

    def test_vague_mystery_is_blocked(self):
        draft = self._good()
        body = draft.body.replace(
            'Ik zag op jullie site de route "Offerte aanvragen" direct naast dakrenovatie.',
            "Ik zag jullie website.",
        )
        errors = c.initial_copy_errors(draft.subject, body)
        self.assertTrue(any("too vague" in error for error in errors))

    def test_price_first_touch_is_blocked(self):
        draft = self._good()
        body = draft.body.replace(
            "Ik heb voor Demo Dak één klein mini-flow gemaakt dat de mogelijke verbetering concreet maakt.",
            "Ik heb voor Demo Dak één klein mini-flow gemaakt voor €750 dat de mogelijke verbetering concreet maakt.",
        )
        errors = c.initial_copy_errors(draft.subject, body)
        self.assertTrue(any("price" in error for error in errors))

    def test_meeting_first_touch_is_blocked(self):
        draft = self._good()
        body = draft.body.replace(
            "Zal ik het voorbeeld sturen?",
            "Plan een meeting van 15 minuten.\n\nZal ik het voorbeeld sturen?",
        )
        errors = c.initial_copy_errors(draft.subject, body)
        self.assertTrue(any("meeting" in error for error in errors))

    def test_generic_subject_length_is_blocked(self):
        draft = self._good()
        self.assertTrue(c.initial_copy_errors("Vraag", draft.body))

    def test_followup_stays_permission_only(self):
        draft = self._good()
        self.assertEqual(c.followup_copy_errors(draft.followup_body), [])
        self.assertNotIn("stap 1", draft.followup_body.casefold())


if __name__ == "__main__":
    unittest.main()
