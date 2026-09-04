from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch

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
    @patch.object(connectivity, "check_mailbox_transport")
    @patch.object(connectivity, "load_mailboxes_from_env")
    def test_connectivity_probes_transport_then_auth(self, load_mailboxes, check_transport, check_auth):
        mailbox = self.mailbox()
        load_mailboxes.return_value = [mailbox]
        check_transport.return_value = ["mailbox:primary:smtp-tls", "mailbox:primary:imap-tls"]
        check_auth.return_value = ["mailbox:primary:smtp-auth", "mailbox:primary:imap-auth"]

        report = connectivity.run_connectivity_check(require_auth=True)

        self.assertEqual(report.auth_status, "green")
        self.assertEqual(
            report.checks,
            (
                "mailbox:primary:smtp-tls",
                "mailbox:primary:imap-tls",
                "mailbox:primary:smtp-auth",
                "mailbox:primary:imap-auth",
            ),
        )
        load_mailboxes.assert_called_once_with(mode="validate", default_daily_limit=20)
        check_transport.assert_called_once_with(mailbox)
        check_auth.assert_called_once_with(mailbox, "live")

    @patch.object(connectivity, "check_mailbox_auth")
    @patch.object(connectivity, "check_mailbox_transport")
    @patch.object(connectivity, "load_mailboxes_from_env")
    def test_missing_secret_keeps_transport_evidence_without_auth(self, load_mailboxes, check_transport, check_auth):
        mailbox = replace(self.mailbox(), mail_password="")
        load_mailboxes.return_value = [mailbox]
        check_transport.return_value = ["mailbox:primary:smtp-tls", "mailbox:primary:imap-tls"]

        report = connectivity.run_connectivity_check(require_auth=False)

        self.assertEqual(report.auth_status, "blocked_missing_secret")
        self.assertIn("mailbox:primary:auth-blocked-missing-secret", report.checks)
        check_transport.assert_called_once_with(mailbox)
        check_auth.assert_not_called()

    @patch.object(connectivity, "check_mailbox_transport")
    @patch.object(connectivity, "load_mailboxes_from_env")
    def test_missing_secret_fails_when_auth_is_required(self, load_mailboxes, check_transport):
        mailbox = replace(self.mailbox(), mail_password="")
        load_mailboxes.return_value = [mailbox]
        check_transport.return_value = ["mailbox:primary:smtp-tls", "mailbox:primary:imap-tls"]

        with self.assertRaisesRegex(RuntimeError, "OUTREACH_MAIL_PASSWORD is required"):
            connectivity.run_connectivity_check(require_auth=True)

    def test_transport_probe_never_authenticates_or_sends(self):
        mailbox = self.mailbox()
        smtp = MagicMock()
        smtp.__enter__.return_value = smtp
        smtp.has_extn.return_value = True
        imap = MagicMock()
        imap.__enter__.return_value = imap
        smtp_factory = MagicMock(return_value=smtp)
        imap_factory = MagicMock(return_value=imap)

        checks = connectivity.check_mailbox_transport(
            mailbox,
            smtp_factory=smtp_factory,
            imap_factory=imap_factory,
        )

        self.assertEqual(checks, ["mailbox:primary:smtp-tls", "mailbox:primary:imap-tls"])
        smtp.login.assert_not_called()
        smtp.sendmail.assert_not_called()
        smtp.send_message.assert_not_called()
        imap.login.assert_not_called()
        imap.fetch.assert_not_called()

    @patch.dict("os.environ", {"OUTREACH_CONNECTIVITY_REQUIRE_AUTH": "maybe"})
    def test_invalid_require_auth_flag_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must be true or false"):
            connectivity._env_bool("OUTREACH_CONNECTIVITY_REQUIRE_AUTH", True)


if __name__ == "__main__":
    unittest.main()
