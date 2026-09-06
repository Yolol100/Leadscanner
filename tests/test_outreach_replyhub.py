import sys
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import outreach_mailboxes as m
import outreach_replyhub as r
import outreach_sender as s


def mailbox():
    return m.MailboxConfig(
        mailbox_id="primary", enabled=True, smtp_host="mail.example.com", smtp_port=587,
        imap_host="mail.example.com", imap_port=993, mail_user="info@example.com",
        mail_password="secret", sender_name="Andrew", sender_email="info@example.com",
        daily_limit=20, min_wait_minutes=1, dkim_selector="x", required_spf_token="",
    )


def settings(mode="live"):
    return s.Settings(
        spreadsheet_id="sheet", mode=mode, timezone_name="Europe/Amsterdam",
        send_window_start="08:00", send_window_end="18:00", daily_send_limit=20,
        max_sends_per_run=2, verification_max_age_days=30, smtp_host="mail.example.com",
        smtp_port=587, imap_host="mail.example.com", imap_port=993,
        mail_user="info@example.com", mail_password="secret", sender_name="Andrew",
        sender_email="info@example.com",
    )


def message(sender="lead@example.org", body="Thanks, interested"):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "info@example.com"
    msg["Subject"] = "Re: Idee"
    msg["Message-ID"] = "<reply-1@example.org>"
    msg.set_content(body)
    return msg.as_bytes()


class FakeIMAP:
    payload = message()
    def __init__(self, *args, **kwargs): pass
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): return False
    def login(self, *args): return "OK", [b"ok"]
    def select(self, *args, **kwargs): return "OK", [b""]
    def search(self, *args): return "OK", [b"1"]
    def fetch(self, *args): return "OK", [(b"1", self.payload)]


class ReplyHubTests(unittest.TestCase):
    def test_validate_mode_never_opens_imap(self):
        with patch.object(r.imaplib, "IMAP4_SSL", side_effect=AssertionError("IMAP must not open")):
            self.assertEqual(r.sync_replyhub_for_mailbox(object(), settings("validate"), [], [], [], mailbox()), 0)

    def test_real_reply_stops_sequence_state(self):
        queue = [{"lead_id":"lead-1","company":"Example","email":"lead@example.org","status":"sent"}]
        with patch.object(r.imaplib, "IMAP4_SSL", FakeIMAP), patch.object(r, "_append_reply"), patch.object(r, "update_row") as update, patch.object(r, "log_event"):
            count = r.sync_replyhub_for_mailbox(object(), settings(), ["lead_id","email","status","reply_at"], queue, [], mailbox())
        self.assertEqual(count, 1)
        self.assertEqual(queue[0]["status"], "replied")
        update.assert_called()

    def test_reply_intent_is_written_as_advisory_metadata_only(self):
        msg = EmailMessage()
        msg["Subject"] = "Re: Idee"
        msg["Message-ID"] = "<reply-advisory@example.org>"
        with patch.object(r, "append_row") as append:
            r._append_reply(
                object(), settings(), reply_id="reply-1", mailbox=mailbox(),
                lead_row={"lead_id":"lead-1","company":"Example"},
                email_address="lead@example.org", msg=msg,
                classification="reply", text="Sounds good, let's talk next week.",
            )
        payload = append.call_args.args[4]
        self.assertEqual(payload["classification"], "reply")
        self.assertEqual(payload["triage_status"], "new")
        self.assertEqual(payload["owner_label"], "positive_interest")
        self.assertIn("advisory_only", payload["notes"])
        self.assertIn("never canonical sales outcome", payload["notes"])

    def test_not_interested_advisory_does_not_become_optout_or_sales_outcome(self):
        queue = [{"lead_id":"lead-1","company":"Example","email":"lead@example.org","status":"sent"}]
        FakeIMAP.payload = message(body="Not interested at this time.")
        try:
            with patch.object(r.imaplib, "IMAP4_SSL", FakeIMAP), patch.object(r, "append_row") as append, patch.object(r, "update_row"), patch.object(r, "add_suppression") as suppress, patch.object(r, "log_event"):
                count = r.sync_replyhub_for_mailbox(object(), settings(), ["lead_id","email","status","reply_at"], queue, [], mailbox())
            self.assertEqual(count, 1)
            self.assertEqual(queue[0]["status"], "replied")
            suppress.assert_not_called()
            payload = append.call_args.args[4]
            self.assertEqual(payload["classification"], "reply")
            self.assertEqual(payload["owner_label"], "not_interested")
            self.assertIn("advisory_only", payload["notes"])
        finally:
            FakeIMAP.payload = message()

    def test_optout_adds_suppression_and_stops(self):
        queue = [{"lead_id":"lead-1","company":"Example","email":"lead@example.org","status":"sent"}]
        FakeIMAP.payload = message(body="Nee bedankt")
        try:
            with patch.object(r.imaplib, "IMAP4_SSL", FakeIMAP), patch.object(r, "_append_reply"), patch.object(r, "update_row"), patch.object(r, "add_suppression") as suppress, patch.object(r, "log_event"):
                r.sync_replyhub_for_mailbox(object(), settings(), ["lead_id","email","status","reply_at"], queue, [], mailbox())
            self.assertEqual(queue[0]["status"], "opted_out")
            suppress.assert_called_once()
        finally:
            FakeIMAP.payload = message()

    def test_bounce_adds_suppression_and_stops(self):
        queue = [{"lead_id":"lead-1","company":"Example","email":"lead@example.org","status":"sent"}]
        with patch.object(r.imaplib, "IMAP4_SSL", FakeIMAP), patch.object(r, "extract_bounced_recipient", return_value="lead@example.org"), patch.object(r, "_append_reply"), patch.object(r, "update_row"), patch.object(r, "add_suppression") as suppress, patch.object(r, "log_event"):
            r.sync_replyhub_for_mailbox(object(), settings(), ["lead_id","email","status","bounce_at","last_error"], queue, [], mailbox())
        self.assertEqual(queue[0]["status"], "bounced")
        suppress.assert_called_once()


if __name__ == "__main__": unittest.main()
