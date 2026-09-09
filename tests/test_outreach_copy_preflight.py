import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import outreach_copy_preflight as c


GOOD_INITIAL = '''Beste team van Demo,

Ik zag dat jullie website bezoekers direct naar een offerteaanvraag stuurt.

Ik help bedrijven dit soort processen eenvoudiger te maken met een kleine AI-ondersteunde workflow, terwijl het team de belangrijke stappen zelf blijft controleren.

Voor Demo zou dat bijvoorbeeld kunnen betekenen: klanten beantwoorden een paar gerichte vragen en je team krijgt een completere aanvraag om te beoordelen.

Zal ik een kort voorbeeld sturen van hoe dat er voor Demo uit kan zien?

Geen interesse? Een kort "nee" is genoeg.

Dit is een commercieel bericht.

Met vriendelijke groet,
Andrew Baeten
andrewbaeten.nl'''

GOOD_FOLLOWUP = '''Beste team van Demo,

Ik kom hier nog één keer op terug. Ik heb het korte voorbeeld voor Demo nog liggen.

Zal ik een kort voorbeeld sturen van hoe dat er voor Demo uit kan zien?

Geen interesse? Een kort "nee" is genoeg.

Met vriendelijke groet,
Andrew Baeten'''


class CopyPreflightTests(unittest.TestCase):
    def test_good_initial(self):
        self.assertEqual(c.initial_copy_errors("Offerteaanvragen bij Demo", GOOD_INITIAL), [])

    def test_old_ai_jargon_blocked_under_human_contract(self):
        body = GOOD_INITIAL.replace(
            "Ik help bedrijven dit soort processen eenvoudiger te maken met een kleine AI-ondersteunde workflow, terwijl het team de belangrijke stappen zelf blijft controleren.",
            "I build bounded digital agents for workflows like this, with human handoff where needed.",
        )
        self.assertTrue(any("jargon" in e for e in c.initial_copy_errors("Offerteaanvragen bij Demo", body)))

    def test_missing_commercial_identification_blocked(self):
        body = GOOD_INITIAL.replace("Dit is een commercieel bericht.\n\n", "")
        self.assertTrue(c.initial_copy_errors("Offerteaanvragen bij Demo", body))

    def test_missing_opt_out_blocked(self):
        body = GOOD_INITIAL.replace('Geen interesse? Een kort "nee" is genoeg.\n\n', "")
        self.assertTrue(c.initial_copy_errors("Offerteaanvragen bij Demo", body))

    def test_fake_reply_subject_blocked(self):
        self.assertTrue(c.initial_copy_errors("RE: Offerteaanvragen bij Demo", GOOD_INITIAL))

    def test_context_free_subject_blocked(self):
        self.assertTrue(c.initial_copy_errors("Quick question", GOOD_INITIAL))

    def test_extra_url_blocked(self):
        body = GOOD_INITIAL.replace("Dit is een commercieel bericht.", "Bekijk https://example.com\n\nDit is een commercieel bericht.")
        self.assertTrue(c.initial_copy_errors("Offerteaanvragen bij Demo", body))

    def test_meeting_pressure_blocked(self):
        body = GOOD_INITIAL.replace(
            "Zal ik een kort voorbeeld sturen van hoe dat er voor Demo uit kan zien?",
            "Plan een meeting van 15 minuten.\n\nZal ik een kort voorbeeld sturen van hoe dat er voor Demo uit kan zien?",
        )
        self.assertTrue(c.initial_copy_errors("Offerteaanvragen bij Demo", body))

    def test_good_followup(self):
        self.assertEqual(c.followup_copy_errors(GOOD_FOLLOWUP), [])

    def test_followup_url_blocked(self):
        self.assertTrue(c.followup_copy_errors(GOOD_FOLLOWUP + "\nhttps://example.com"))

    def test_followup_placeholder_blocked(self):
        self.assertTrue(c.followup_copy_errors(GOOD_FOLLOWUP.replace("Demo", "[mailnaam]", 1)))

    def test_followup_meeting_ask_blocked(self):
        self.assertTrue(c.followup_copy_errors(GOOD_FOLLOWUP.replace("nog liggen.", "nog liggen. Plan daarna een meeting van 15 minuten.")))

    def test_queue_custom_followup_subject_blocked(self):
        row = {"status": "sent", "followup_body": GOOD_FOLLOWUP, "followup_subject": "Nieuwe pitch"}
        self.assertTrue(c.queue_copy_errors(row))

    def test_third_touch_blocked_by_default(self):
        row = {"enabled": "true", "status": "approved", "step_number": "3", "body": GOOD_FOLLOWUP}
        self.assertTrue(c.sequence_copy_errors(row))


if __name__ == "__main__":
    unittest.main()
