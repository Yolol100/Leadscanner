import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import outreach_mailboxes as m
import outreach_sender as o


def mailbox(mailbox_id: str, *, daily_limit: int = 20, min_wait_minutes: int = 1, enabled: bool = True):
    return m.MailboxConfig(
        mailbox_id=mailbox_id, enabled=enabled, smtp_host="mail.example.com", smtp_port=587,
        imap_host="mail.example.com", imap_port=993, mail_user=f"{mailbox_id}@example.com",
        mail_password="secret", sender_name="Andrew", sender_email=f"{mailbox_id}@example.com",
        daily_limit=daily_limit, min_wait_minutes=min_wait_minutes, dkim_selector="x",
        required_spf_token="include:spf.example.com",
    )


class OutreachMailboxTests(unittest.TestCase):
    def test_legacy_environment_remains_supported(self):
        env = {
            "OUTREACH_SMTP_HOST":"mail.example.com","OUTREACH_SMTP_PORT":"587",
            "OUTREACH_IMAP_HOST":"mail.example.com","OUTREACH_IMAP_PORT":"993",
            "OUTREACH_MAIL_USER":"info@example.com","OUTREACH_MAIL_PASSWORD":"secret",
            "OUTREACH_SENDER_NAME":"Andrew","OUTREACH_SENDER_EMAIL":"info@example.com",
            "OUTREACH_DKIM_SELECTOR":"x","OUTREACH_REQUIRED_SPF_TOKEN":"include:spf.example.com",
        }
        with patch.dict(os.environ, env, clear=True):
            result = m.load_mailboxes_from_env(mode="live", default_daily_limit=20)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].mailbox_id, "primary")
        self.assertEqual(result[0].sender_email, "info@example.com")
        self.assertEqual(result[0].daily_limit, 20)

    def test_legacy_environment_uses_50_day_campaign_capacity(self):
        env = {
            "OUTREACH_SMTP_HOST":"mail.example.com","OUTREACH_SMTP_PORT":"587",
            "OUTREACH_IMAP_HOST":"mail.example.com","OUTREACH_IMAP_PORT":"993",
            "OUTREACH_MAIL_USER":"info@example.com","OUTREACH_MAIL_PASSWORD":"secret",
            "OUTREACH_SENDER_NAME":"Andrew","OUTREACH_SENDER_EMAIL":"info@example.com",
            "OUTREACH_DKIM_SELECTOR":"x","OUTREACH_REQUIRED_SPF_TOKEN":"include:spf.example.com",
        }
        with patch.dict(os.environ, env, clear=True):
            result = m.load_mailboxes_from_env(mode="live", default_daily_limit=50)
        self.assertEqual(result[0].daily_limit, 50)

    def test_json_pool_loads_multiple_mailboxes(self):
        payload = [
            {"id":"sales-1","smtp_host":"mail.example.com","imap_host":"mail.example.com","mail_user":"sales1@example.com","password":"one","sender_name":"Andrew","sender_email":"sales1@example.com","daily_limit":12,"min_wait_minutes":3,"dkim_selector":"x"},
            {"id":"sales-2","smtp_host":"mail.example.com","imap_host":"mail.example.com","mail_user":"sales2@example.com","password":"two","sender_name":"Andrew","sender_email":"sales2@example.com","daily_limit":8,"dkim_selector":"x"},
        ]
        with patch.dict(os.environ, {"OUTREACH_MAILBOXES_JSON": json.dumps(payload)}, clear=True):
            result = m.load_mailboxes_from_env(mode="live", default_daily_limit=20)
        self.assertEqual([item.mailbox_id for item in result], ["sales-1", "sales-2"])
        self.assertEqual(result[0].daily_limit, 12)
        self.assertEqual(result[0].min_wait_minutes, 3)

    def test_duplicate_sender_is_rejected(self):
        payload = [
            {"id":"one","smtp_host":"mail.example.com","imap_host":"mail.example.com","mail_user":"one@example.com","sender_name":"Andrew","sender_email":"same@example.com"},
            {"id":"two","smtp_host":"mail.example.com","imap_host":"mail.example.com","mail_user":"two@example.com","sender_name":"Andrew","sender_email":"same@example.com"},
        ]
        with patch.dict(os.environ, {"OUTREACH_MAILBOXES_JSON": json.dumps(payload)}, clear=True):
            with self.assertRaisesRegex(ValueError, "duplicate sender_email"):
                m.load_mailboxes_from_env(mode="verify", default_daily_limit=20)

    def test_live_enabled_mailbox_requires_password_and_dkim(self):
        payload = [{"id":"one","smtp_host":"mail.example.com","imap_host":"mail.example.com","mail_user":"one@example.com","sender_name":"Andrew","sender_email":"one@example.com"}]
        with patch.dict(os.environ, {"OUTREACH_MAILBOXES_JSON": json.dumps(payload)}, clear=True):
            with self.assertRaisesRegex(ValueError, "password is required"):
                m.load_mailboxes_from_env(mode="live", default_daily_limit=20)

    def test_rotation_uses_available_capacity(self):
        now = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
        pool = [mailbox("one", daily_limit=2), mailbox("two", daily_limit=2)]
        first = m.choose_initial_mailbox(pool, sent_today={"one":0,"two":0}, last_sent_at={}, now=now, lead_id="lead-1")
        self.assertIsNotNone(first)
        counts = {"one":0,"two":0}; counts[first.mailbox_id] = 1
        second = m.choose_initial_mailbox(pool, sent_today=counts, last_sent_at={first.mailbox_id: now - timedelta(minutes=5)}, now=now, lead_id="lead-2")
        self.assertIsNotNone(second)
        self.assertNotEqual(first.mailbox_id, second.mailbox_id)

    def test_rotation_respects_daily_limit_and_wait(self):
        now = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
        selected = m.choose_initial_mailbox(
            [mailbox("one", daily_limit=1, min_wait_minutes=5), mailbox("two", daily_limit=5, min_wait_minutes=5)],
            sent_today={"one":1,"two":0}, last_sent_at={"two": now - timedelta(minutes=1)}, now=now, lead_id="lead-3")
        self.assertIsNone(selected)

    def test_mailbox_counts_include_initial_and_followup(self):
        rows = [
            {"sender_mailbox_id":"one","sent_at":"2026-09-04T07:00:00Z","followup_sent_at":"2026-09-04T08:00:00Z"},
            {"sender_mailbox_id":"two","sent_at":"2026-09-03T07:00:00Z","followup_sent_at":""},
        ]
        counts = m.count_mailbox_sends_today(rows, now=datetime(2026,9,4,12,0,tzinfo=timezone.utc), timezone_name="Europe/Amsterdam", parse_dt=o.parse_dt)
        self.assertEqual(counts, {"one":2})


if __name__ == "__main__":
    unittest.main()
