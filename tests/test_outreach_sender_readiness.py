import unittest
from unittest.mock import patch

from outreach_mailboxes import MailboxConfig
import outreach_sender_readiness as m


class SenderReadinessTests(unittest.TestCase):
    def mailbox(self, password="secret"):
        return MailboxConfig(
            mailbox_id="primary",
            enabled=True,
            sender_name="Andrew",
            sender_email="info@example.com",
            smtp_host="smtp.example.com",
            smtp_port=587,
            imap_host="imap.example.com",
            imap_port=993,
            mail_user="info@example.com",
            mail_password=password,
            dkim_selector="x",
            required_spf_token="include:spf.example.com",
            daily_limit=20,
            min_wait_minutes=1,
        )

    @patch.object(m, "check_dnsbl", return_value=("clear", "ok"))
    @patch.object(m, "check_ptr_fcrdns", return_value=m.PtrReport("green", "green", "mail.example.com"))
    @patch.object(m, "check_mx", return_value="green")
    @patch.object(m, "check_mailbox_auth", return_value=["auth"])
    @patch.object(m, "check_mailbox_transport", return_value=["mailbox:primary:smtp-tls", "mailbox:primary:imap-tls"])
    @patch.object(m, "_dns_auth_state", return_value=({"spf": "green", "dkim": "green", "dmarc": "green"}, []))
    def test_all_proven_is_green(self, *_):
        row = m.build_readiness_row(self.mailbox(), outbound_ip="8.8.8.8", dnsbl_zones=["dnsbl.example"])
        self.assertEqual(row["state"], "green")

    @patch.object(m, "check_dnsbl", return_value=("not_configured", "none"))
    @patch.object(m, "check_ptr_fcrdns", return_value=m.PtrReport("not_configured", "not_configured", "none"))
    @patch.object(m, "check_mx", return_value="green")
    @patch.object(m, "check_mailbox_transport", return_value=["mailbox:primary:smtp-tls", "mailbox:primary:imap-tls"])
    @patch.object(m, "_dns_auth_state", return_value=({"spf": "green", "dkim": "green", "dmarc": "green"}, []))
    def test_missing_optional_proof_and_auth_is_review(self, *_):
        row = m.build_readiness_row(self.mailbox(password=""))
        self.assertEqual(row["auth"], "blocked_missing_secret")
        self.assertEqual(row["state"], "review")

    @patch.object(m, "check_dnsbl", return_value=("listed", "listed"))
    @patch.object(m, "check_ptr_fcrdns", return_value=m.PtrReport("green", "green", "mail.example.com"))
    @patch.object(m, "check_mx", return_value="green")
    @patch.object(m, "check_mailbox_auth", return_value=["auth"])
    @patch.object(m, "check_mailbox_transport", return_value=["mailbox:primary:smtp-tls", "mailbox:primary:imap-tls"])
    @patch.object(m, "_dns_auth_state", return_value=({"spf": "green", "dkim": "green", "dmarc": "green"}, []))
    def test_dnsbl_listing_blocks(self, *_):
        row = m.build_readiness_row(self.mailbox(), outbound_ip="8.8.8.8", dnsbl_zones=["dnsbl.example"])
        self.assertEqual(row["state"], "blocked")


if __name__ == "__main__":
    unittest.main()
