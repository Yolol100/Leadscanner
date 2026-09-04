import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from outreach_optout import message_has_optout


class OutreachOptOutTests(unittest.TestCase):
    def test_detects_explicit_phrase(self):
        self.assertTrue(message_has_optout("Please remove me from this list."))
        self.assertTrue(message_has_optout("Geen mails meer graag"))

    def test_detects_short_reply_after_greeting(self):
        self.assertTrue(message_has_optout("Hallo Andrew,\n\nNee bedankt.\n\nGroet"))
        self.assertTrue(message_has_optout("Beste Andrew,\n\nGeen interesse.\n\nMet vriendelijke groet"))

    def test_does_not_use_quoted_outbound_cta_as_optout(self):
        quoted = 'Op 4 sep schreef Andrew:\nGeen interesse? Een kort "nee" is genoeg.'
        self.assertFalse(message_has_optout(quoted))

    def test_keeps_ambiguous_negative_reply_for_manual_triage(self):
        self.assertFalse(message_has_optout("Not interested right now."))


if __name__ == "__main__":
    unittest.main()
