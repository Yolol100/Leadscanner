import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import outreach_mailboxes as m
import outreach_sender as o


def mailbox(mailbox_id="one", sender_email="one@example.com", enabled=True):
    return m.MailboxConfig(
        mailbox_id=mailbox_id, enabled=enabled, smtp_host="mail.example.com", smtp_port=587,
        imap_host="mail.example.com", imap_port=993, mail_user=sender_email, mail_password="secret",
        sender_name="Andrew", sender_email=sender_email, daily_limit=20, min_wait_minutes=1,
        dkim_selector="x", required_spf_token="include:spf.example.com",
    )


class OutreachSenderTests(unittest.TestCase):
    def test_verification_decision(self):
        self.assertEqual(o.verification_decision({"status":"safe","is_safe_to_send":True}), "safe")
        self.assertEqual(o.verification_decision({"status":"catch_all","is_safe_to_send":False}), "manual_review")
        self.assertEqual(o.verification_decision({"status":"invalid","is_safe_to_send":False}), "blocked")
        self.assertEqual(o.verification_decision({"status":"safe","is_safe_to_send":False}), "manual_review")

    def test_opt_out_detection_is_conservative(self):
        self.assertTrue(o.message_has_optout("Please remove me from this list."))
        self.assertTrue(o.message_has_optout("Geen mails meer graag"))
        self.assertTrue(o.message_has_optout('nee\n\nOp 4 sep schreef Andrew:\nGeen interesse? Een kort "nee" is genoeg.'))
        self.assertFalse(o.message_has_optout("Not interested right now."))

    def test_sender_has_no_verifier_api_surface(self):
        self.assertFalse(hasattr(o, "reoon_verify"))
        self.assertNotIn("reoon_api_key", o.Settings.__dataclass_fields__)

    def test_next_action(self):
        now = datetime(2026,9,4,10,0,tzinfo=timezone.utc)
        self.assertEqual(o.next_action({"status":"approved"}, now), "initial")
        self.assertIsNone(o.next_action({"status":"sending"}, now))
        self.assertIsNone(o.next_action({"status":"replied"}, now))
        self.assertEqual(o.next_action({"status":"sent","followup_body":"x","next_send_at":"2026-09-04T09:00:00Z"}, now), "followup")
        self.assertIsNone(o.next_action({"status":"sent","followup_body":"x","next_send_at":"2026-09-05T09:00:00Z"}, now))

    def test_daily_count_counts_both_stages(self):
        now=datetime(2026,9,4,12,0,tzinfo=timezone.utc)
        rows=[{"sent_at":"2026-09-04T07:00:00Z","followup_sent_at":"2026-09-04T08:00:00Z"},{"sent_at":"2026-09-03T07:00:00Z","followup_sent_at":""}]
        self.assertEqual(o.count_sends_today(rows, now, "Europe/Amsterdam"), 2)

    def test_suppression(self):
        self.assertTrue(o.suppression_match("A@Example.com", {"a@example.com"}, set()))
        self.assertTrue(o.suppression_match("a@example.com", set(), {"example.com"}))
        self.assertFalse(o.suppression_match("a@example.com", set(), {"other.com"}))

    def test_message_id_is_deterministic(self):
        first=o.deterministic_message_id("lead-1",1,"info@example.com"); second=o.deterministic_message_id("lead-1",1,"info@example.com"); follow=o.deterministic_message_id("lead-1",2,"info@example.com")
        self.assertEqual(first, second); self.assertNotEqual(first, follow); self.assertTrue(first.endswith("@example.com>"))

    def test_build_message_uses_selected_mailbox_identity(self):
        selected=mailbox("sales-1","sales1@example.com")
        row={"lead_id":"lead-1","email":"lead@example.org","subject":"Subject","body":"Body"}
        msg=o.build_message(row,selected,1)
        self.assertEqual(msg["From"], "Andrew <sales1@example.com>"); self.assertEqual(msg["To"], "lead@example.org")

    def test_followup_stays_on_assigned_mailbox(self):
        one=mailbox("one","one@example.com"); two=mailbox("two","two@example.com")
        resolved,reason=o.resolve_followup_mailbox({"sender_mailbox_id":"two","sender_email":"two@example.com"}, configured={"one":one,"two":two}, enabled=[one,two])
        self.assertEqual(reason, ""); self.assertEqual(resolved.mailbox_id, "two")

    def test_followup_without_assignment_fails_closed_with_multiple_mailboxes(self):
        one=mailbox("one","one@example.com"); two=mailbox("two","two@example.com")
        resolved,reason=o.resolve_followup_mailbox({}, configured={"one":one,"two":two}, enabled=[one,two])
        self.assertIsNone(resolved); self.assertIn("requires sender_mailbox_id", reason)

    def test_followup_detects_sender_identity_change(self):
        one=mailbox("one","new@example.com")
        resolved,reason=o.resolve_followup_mailbox({"sender_mailbox_id":"one","sender_email":"old@example.com"}, configured={"one":one}, enabled=[one])
        self.assertIsNone(resolved); self.assertIn("sender_email changed", reason)

    def test_fresh_verification(self):
        now=datetime(2026,9,4,12,0,tzinfo=timezone.utc)
        self.assertTrue(o.verification_is_fresh({"verification_status":"safe","verification_checked_at":"2026-09-01T12:00:00Z"}, now, 30))
        self.assertFalse(o.verification_is_fresh({"verification_status":"safe","verification_checked_at":"2026-07-01T12:00:00Z"}, now, 30))

    def test_send_window_blocks_weekend(self):
        friday=datetime(2026,9,4,10,0,tzinfo=timezone.utc); sunday=friday+timedelta(days=2)
        self.assertTrue(o.within_send_window(friday,"Europe/Amsterdam","08:00","18:00")); self.assertFalse(o.within_send_window(sunday,"Europe/Amsterdam","08:00","18:00"))

    def test_direct_smtp_rejects_provider_required_without_one_click_provider(self):
        row={"lead_id":"lead-1","email":"a@example.com","compliance_status":"approved","opt_out_mode":"provider_required","subject":"Subject","body":"Body"}
        self.assertTrue(any("provider_required" in item for item in o.validate_row(row,"initial")))

    def test_column_name(self):
        self.assertEqual(o.column_name(1),"A"); self.assertEqual(o.column_name(26),"Z"); self.assertEqual(o.column_name(27),"AA"); self.assertEqual(o.column_name(28),"AB")


if __name__ == "__main__": unittest.main()
