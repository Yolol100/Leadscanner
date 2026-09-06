from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from outreach_reply_triage import ADVISORY_ONLY_NOTE, advisory_reply_triage, classify_reply_intent


class OutreachReplyTriageTests(unittest.TestCase):
    def test_positive_interest(self):
        self.assertEqual(classify_reply_intent("Sounds good, let's talk next week."), "positive_interest")

    def test_out_of_office_has_priority(self):
        self.assertEqual(classify_reply_intent("Automatic reply: I am out of office until Monday."), "out_of_office")

    def test_referral(self):
        self.assertEqual(classify_reply_intent("Please contact my colleague for this."), "referral")

    def test_question(self):
        self.assertEqual(classify_reply_intent("What is your pricing?"), "question")

    def test_not_interested(self):
        self.assertEqual(classify_reply_intent("Not interested at this time."), "not_interested")

    def test_neutral_and_advisory_boundary(self):
        result = advisory_reply_triage("Thanks for your email.")
        self.assertEqual(result["intent"], "neutral")
        self.assertEqual(result["note"], ADVISORY_ONLY_NOTE)
        self.assertIn("never canonical sales outcome", result["note"])


if __name__ == "__main__":
    unittest.main()
