import unittest
from unittest.mock import patch

from outreach_mailboxes import MailboxConfig
import outreach_sender_readiness as m


class SenderReadinessTests(unittest.TestCase):
    def mailbox(self, password="secret", required_spf_token="include:spf.example.com"):
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
            required_spf_token=required_spf_token,
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

    @patch.object(m, "check_mx", return_value="green")
    @patch.object(m, "check_mailbox_auth", return_value=["auth"])
    @patch.object(m, "check_mailbox_transport", return_value=["mailbox:primary:smtp-tls", "mailbox:primary:imap-tls"])
    @patch.object(m, "_dns_auth_state", return_value=({"spf": "green", "dkim": "green", "dmarc": "green"}, []))
    def test_mijn_host_shared_relay_is_automatic_without_outbound_ip(self, *_):
        mailbox = self.mailbox(required_spf_token="include:spf.mijn.host")
        with patch.object(m, "check_ptr_fcrdns") as ptr_check, patch.object(m, "check_dnsbl") as dnsbl_check:
            row = m.build_readiness_row(mailbox)
        ptr_check.assert_not_called()
        dnsbl_check.assert_not_called()
        self.assertEqual(row["ptr"], "provider_managed")
        self.assertEqual(row["fcrdns"], "provider_managed")
        self.assertEqual(row["dnsbl"], "provider_managed")
        self.assertEqual(row["state"], "green")
        self.assertIn("provider_managed:mijn.host", row["note"])
        self.assertIn("no per-egress-IP DNSBL clearance is claimed", row["note"])

    @patch.object(m, "check_mx", return_value="green")
    @patch.object(m, "check_mailbox_auth", return_value=["auth"])
    @patch.object(m, "check_mailbox_transport", return_value=["mailbox:primary:smtp-tls", "mailbox:primary:imap-tls"])
    @patch.object(m, "_dns_auth_state", return_value=({"spf": "green", "dkim": "green", "dmarc": "green"}, []))
    def test_generic_shared_relay_without_outbound_ip_stays_review(self, *_):
        row = m.build_readiness_row(self.mailbox())
        self.assertEqual(row["ptr"], "not_configured")
        self.assertEqual(row["fcrdns"], "not_configured")
        self.assertEqual(row["dnsbl"], "not_configured")
        self.assertEqual(row["state"], "review")

    @patch.object(m, "check_dnsbl", return_value=("clear", "ok"))
    @patch.object(m, "check_ptr_fcrdns", return_value=m.PtrReport("green", "green", "relay.example"))
    @patch.object(m, "check_mx", return_value="green")
    @patch.object(m, "check_mailbox_auth", return_value=["auth"])
    @patch.object(m, "check_mailbox_transport", return_value=["mailbox:primary:smtp-tls", "mailbox:primary:imap-tls"])
    @patch.object(m, "_dns_auth_state", return_value=({"spf": "green", "dkim": "green", "dmarc": "green"}, []))
    def test_explicit_ip_overrides_mijn_host_provider_managed_mode(self, *_):
        mailbox = self.mailbox(required_spf_token="include:spf.mijn.host")
        row = m.build_readiness_row(mailbox, outbound_ip="8.8.8.8", dnsbl_zones=["dnsbl.example"])
        self.assertEqual(row["ptr"], "green")
        self.assertEqual(row["fcrdns"], "green")
        self.assertEqual(row["dnsbl"], "clear")
        self.assertEqual(row["state"], "green")
        self.assertIn("Relay mode: explicit_ip", row["note"])

    def test_provider_managed_relay_requires_proven_spf(self):
        mailbox = self.mailbox(required_spf_token="include:spf.mijn.host")
        self.assertEqual(m.provider_managed_relay(mailbox, {"spf": "blocked"}), "")
        self.assertEqual(m.provider_managed_relay(mailbox, {"spf": "green"}), "mijn.host")

    def test_monitor_allows_review_when_green_is_not_required(self):
        error = m.readiness_gate_error(
            [{"state": "review"}],
            fail_on_blocked=True,
            require_green=False,
        )
        self.assertEqual(error, "")

    def test_live_gate_rejects_review_when_green_is_required(self):
        error = m.readiness_gate_error(
            [{"state": "review"}],
            fail_on_blocked=True,
            require_green=True,
        )
        self.assertIn("must be green", error)
        self.assertIn("review=1", error)

    def test_green_only_gate_accepts_green(self):
        error = m.readiness_gate_error(
            [{"state": "green"}],
            fail_on_blocked=True,
            require_green=True,
        )
        self.assertEqual(error, "")


if __name__ == "__main__":
    unittest.main()
