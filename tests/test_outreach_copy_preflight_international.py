import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import outreach_copy_preflight as c


GOOD_INITIAL_EN = '''Hi Demo team,

Demo sells handmade lighting and home accessories through its online store.

One idea: make the mobile category navigation visible above the product grid so shoppers can reach the right collection faster.

If you want to take this further, I can build a complete, mobile-friendly webshop for Demo for €750.

A few examples:
https://andrewbaeten.nl/category/cases

Would you like me to send one more concrete idea?

Not interested? A quick "no" is enough.

Best regards,
Andrew Baeten'''

GOOD_FOLLOWUP_EN = '''Hi Demo team,

Just following up once. If useful, I'm happy to send the concrete idea for Demo.

Not interested? A quick "no" is enough.

Best regards,
Andrew Baeten'''


class InternationalCopyPreflightTests(unittest.TestCase):
    def test_good_english_initial(self):
        self.assertEqual(c.initial_copy_errors("Idea for Demo", GOOD_INITIAL_EN), [])

    def test_good_english_followup(self):
        self.assertEqual(c.followup_copy_errors(GOOD_FOLLOWUP_EN), [])

    def test_mixed_language_cta_is_blocked(self):
        body = GOOD_INITIAL_EN.replace(
            "Would you like me to send one more concrete idea?",
            "Would you like me to send one more concrete idea?\nZal ik nog één concreet idee sturen?",
        )
        self.assertTrue(c.initial_copy_errors("Idea for Demo", body))

    def test_english_wrong_optout_is_blocked(self):
        body = GOOD_INITIAL_EN.replace(
            'Not interested? A quick "no" is enough.',
            'Geen interesse? Een kort "nee" is genoeg.',
        )
        self.assertTrue(c.initial_copy_errors("Idea for Demo", body))

    def test_english_meeting_pressure_is_blocked(self):
        body = GOOD_INITIAL_EN.replace(
            "Would you like me to send one more concrete idea?",
            "Schedule a 15 minute meeting.\n\nWould you like me to send one more concrete idea?",
        )
        self.assertTrue(c.initial_copy_errors("Idea for Demo", body))


if __name__ == "__main__":
    unittest.main()
