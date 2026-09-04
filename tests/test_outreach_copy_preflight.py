import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import outreach_copy_preflight as c


GOOD_INITIAL = '''Beste team van Demo,

Demo helpt bedrijven met interieurprojecten.

Eén idee: maak op mobiel direct zichtbaar welke projecttypes jullie aannemen, zodat bezoekers sneller de juiste dienst kunnen kiezen en zonder zoeken bij de relevante informatie uitkomen.

Als je dit breder wilt doorvoeren, kan ik voor Demo een complete, mobielvriendelijke website maken voor €500.

Een paar voorbeelden:
https://andrewbaeten.nl/category/cases

Zal ik nog één concreet idee sturen?

Geen interesse? Een kort "nee" is genoeg.

Met vriendelijke groet,
Andrew Baeten'''

GOOD_FOLLOWUP = '''Beste team van Demo,

Ik kom hier nog één keer op terug. Als het nuttig is, stuur ik het concrete idee voor Demo graag door.

Geen interesse? Een kort "nee" is genoeg.

Met vriendelijke groet,
Andrew Baeten'''


class CopyPreflightTests(unittest.TestCase):
    def test_good_initial(self):
        self.assertEqual(c.initial_copy_errors("Idee voor Demo", GOOD_INITIAL), [])

    def test_cross_contaminated_cta_blocked(self):
        body = GOOD_INITIAL.replace(
            "Zal ik nog één concreet idee sturen?",
            "Zal ik nog één concreet idee sturen?\nMag ik nog één concreet idee sturen?",
        )
        self.assertTrue(c.initial_copy_errors("Idee voor Demo", body))

    def test_missing_opt_out_blocked(self):
        body = GOOD_INITIAL.replace('Geen interesse? Een kort "nee" is genoeg.\n\n', "")
        self.assertTrue(c.initial_copy_errors("Idee voor Demo", body))

    def test_fake_reply_subject_blocked(self):
        self.assertTrue(c.initial_copy_errors("RE: Idee voor Demo", GOOD_INITIAL))

    def test_extra_url_blocked(self):
        body = GOOD_INITIAL.replace("Een paar voorbeelden:", "Bekijk ook https://example.com\n\nEen paar voorbeelden:")
        self.assertTrue(c.initial_copy_errors("Idee voor Demo", body))

    def test_meeting_pressure_blocked(self):
        body = GOOD_INITIAL.replace(
            "Zal ik nog één concreet idee sturen?",
            "Plan een meeting van 15 minuten.\n\nZal ik nog één concreet idee sturen?",
        )
        self.assertTrue(c.initial_copy_errors("Idee voor Demo", body))

    def test_good_followup(self):
        self.assertEqual(c.followup_copy_errors(GOOD_FOLLOWUP), [])

    def test_followup_url_blocked(self):
        self.assertTrue(c.followup_copy_errors(GOOD_FOLLOWUP + "\nhttps://example.com"))

    def test_followup_placeholder_blocked(self):
        self.assertTrue(c.followup_copy_errors(GOOD_FOLLOWUP.replace("Demo", "[mailnaam]", 1)))

    def test_followup_meeting_ask_blocked(self):
        self.assertTrue(c.followup_copy_errors(GOOD_FOLLOWUP.replace("graag door.", "graag door. Plan daarna een meeting van 15 minuten.")))

    def test_queue_custom_followup_subject_blocked(self):
        row = {"status": "sent", "followup_body": GOOD_FOLLOWUP, "followup_subject": "Nieuwe pitch"}
        self.assertTrue(c.queue_copy_errors(row))

    def test_third_touch_blocked_by_default(self):
        row = {"enabled": "true", "status": "approved", "step_number": "3", "body": GOOD_FOLLOWUP}
        self.assertTrue(c.sequence_copy_errors(row))


if __name__ == "__main__":
    unittest.main()
