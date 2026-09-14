import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import outreach_copy_v17_2 as c


class V1722BoundaryMatrixTests(unittest.TestCase):
    def _body_at_words(self, target: int) -> str:
        body = (
            "Hi team,\n\n"
            "I noticed your site quote form.\n\n"
            "This may create avoidable friction.\n\n"
            "I made one small example for your team.\n\n"
            "Want me to send the example?\n\n"
            'Not interested? A quick "no" is enough.\n\n'
            "This is a commercial message.\n\n"
            "Best regards,\nAndrew Baeten"
        )
        base = c._word_count(body)
        self.assertLessEqual(base, target)
        filler = " ".join(["detail"] * (target - base))
        if filler:
            body = body.replace(
                "This may create avoidable friction.",
                f"This may create avoidable friction {filler}.",
            )
        self.assertEqual(c._word_count(body), target)
        return body

    def test_body_word_boundaries_49_50_100_101(self):
        self.assertTrue(any("50-100" in e for e in c.initial_copy_errors("Quote request flow", self._body_at_words(49))))
        self.assertEqual(c.initial_copy_errors("Quote request flow", self._body_at_words(50)), [])
        self.assertEqual(c.initial_copy_errors("Quote request flow", self._body_at_words(100)), [])
        self.assertTrue(any("50-100" in e for e in c.initial_copy_errors("Quote request flow", self._body_at_words(101))))

    def test_subject_boundaries_1_2_6_7_words(self):
        self.assertTrue(c._subject_errors("Quote"))
        self.assertEqual(c._subject_errors("Quote flow"), [])
        self.assertEqual(c._subject_errors("Quote request flow for machine parts"), [])
        self.assertTrue(c._subject_errors("Quote request flow for machine parts today"))

    def test_permission_cta_boundary_one_vs_two(self):
        body = self._body_at_words(50)
        self.assertEqual(c.initial_copy_errors("Quote request flow", body), [])
        doubled = body.replace(
            "Want me to send the example?",
            "Want me to send the example?\n\nWould you like me to send the example?",
        )
        self.assertTrue(any("exactly one permission CTA" in e for e in c.initial_copy_errors("Quote request flow", doubled)))


if __name__ == "__main__":
    unittest.main()
