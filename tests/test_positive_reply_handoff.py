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

    def test_followup_copy_contains_no_send_instruction_or_claim(self):
        body=followup_body().lower()
        self.assertIn("first message", body)
        self.assertNotIn("send now", body)
        self.assertNotIn("guarantee", body)


if __name__ == "__main__":
    unittest.main()
