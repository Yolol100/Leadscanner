from __future__ import annotations

import unittest
from unittest.mock import patch

import outreach_mailbox_connectivity as connectivity
from outreach_mailboxes import MailboxConfig


class MailboxConnectivityTests(unittest.TestCase):
    def mailbox(self) -> MailboxConfig:
        return MailboxConfig(
            mailbox_id="primary",
            enabled=True,
            smtp_host="mail.example.test",
            smtp_port=587,
            imap_host="mail.example.test",
            imap_port=993,
            mail_user="info@example.test",
            mail_password="secret-from-env",
            sender_name="Example",
            sender_email="info@example.test",
            daily_limit=20,
            min_wait_minutes=1,
            dkim_selector="x",
            required_spf_token="include:example.test",
        )

    @patch.object(connectivity, "check_mailbox_auth")
    @patch.object(connectivity, "load_mailboxes_from_env")
    def test_connectivity_only_calls_auth_check(self, load_mailboxes, check_auth):
        mailbox = self.mailbox()
        load_mailboxes.return_value = [mailbox]
        check_auth.return_value = ["mailbox:primary:smtp-auth", "mailbox:primary:imap-auth"]

        checks = connectivity.run_connectivity_check()

        self.assertEqual(
            checks,
            ("mailbox:primary:smtp-auth", "mailbox:primary:imap-auth"),
        )
        load_mailboxes.assert_called_once_with(mode="live", default_daily_limit=20)
        check_auth.assert_called_once_with(mailbox, "live")


if __name__ == "__main__":
    unittest.main()
