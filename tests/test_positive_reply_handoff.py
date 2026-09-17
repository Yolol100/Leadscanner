import unittest

from outreach_positive_reply_handoff import (
    DONE,
    PENDING,
    draft_test_id,
    eligible_reply,
    followup_body,
    reply_subject,
)


class PositiveReplyHandoffTests(unittest.TestCase):
    def test_positive_new_is_eligible(self):
        self.assertTrue(eligible_reply({"classification":"reply","owner_label":"positive_interest","triage_status":"new"}))

    def test_pending_retry_is_eligible_and_done_is_not(self):
        base={"classification":"reply","owner_label":"positive_interest"}
        self.assertTrue(eligible_reply({**base,"triage_status":PENDING}))
        self.assertFalse(eligible_reply({**base,"triage_status":DONE}))

    def test_negative_ambiguous_and_optout_never_create_followup(self):
        for row in (
            {"classification":"reply","owner_label":"not_interested","triage_status":"new"},
            {"classification":"reply","owner_label":"neutral","triage_status":"new"},
            {"classification":"opt_out","owner_label":"positive_interest","triage_status":"closed"},
        ):
            self.assertFalse(eligible_reply(row))

    def test_reply_id_becomes_stable_idempotency_key(self):
        rid="a"*32
        self.assertEqual(draft_test_id(rid), "positive-reply-"+rid)
        with self.assertRaises(ValueError):
            draft_test_id("not-safe")

    def test_subject_strips_header_injection(self):
        self.assertEqual(reply_subject("Hello\r\nBcc: attacker@example.test"), "Re: Hello Bcc: attacker@example.test")

    def test_english_followup_is_one_focused_question_without_artifact_claim(self):
        body=followup_body().lower()
        self.assertIn("first message", body)
        self.assertIn("?", body)
        self.assertIn("make concrete first", body)
        self.assertNotIn("is ready", body)
        self.assertNotIn("i made", body)
        self.assertNotIn("send now", body)
        self.assertNotIn("guarantee", body)

    def test_dutch_followup_uses_original_outbound_language(self):
        body=followup_body("Geen interesse? Een kort \"nee\" is genoeg.")
        self.assertIn("Bedankt voor je reactie", body)
        self.assertIn("welk onderdeel", body.lower())
        self.assertIn("?", body)
        self.assertNotIn("ligt klaar", body.lower())


if __name__ == "__main__":
    unittest.main()
