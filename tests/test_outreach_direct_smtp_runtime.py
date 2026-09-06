import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import outreach_direct_smtp_runtime as d
import outreach_mailboxes as m


ADDRESS = "123 Main Street, Example City"


def mailbox():
    return m.MailboxConfig(
        mailbox_id="primary",
        enabled=True,
        smtp_host="mail.example.com",
        smtp_port=587,
        imap_host="mail.example.com",
        imap_port=993,
        mail_user="sender@example.com",
        mail_password="secret",
        sender_name="Andrew",
        sender_email="sender@example.com",
        daily_limit=20,
        min_wait_minutes=1,
        dkim_selector="x",
        required_spf_token="include:spf.example.com",
    )


class DirectSmtpRuntimeTests(unittest.TestCase):
    def test_no_external_verifier_required(self):
        self.assertTrue(d._no_external_verifier_required({}, None, 0))

    def test_us_postal_address_is_injected_only_into_mime_message(self):
        row = {
            "lead_id": "lead-us",
            "country": "US",
            "email": "lead@example.org",
            "subject": "Idea",
            "body": f"This is a commercial message.\n{d.POSTAL_PLACEHOLDER}\nNot interested? A quick no is enough.",
        }
        stored_body = row["body"]
        with patch.dict(os.environ, {"OUTREACH_POSTAL_ADDRESS": ADDRESS}, clear=False):
            msg = d._build_message_with_private_postal(row, mailbox(), 1)
        content = msg.get_content()
        self.assertIn(ADDRESS, content)
        self.assertNotIn(d.POSTAL_PLACEHOLDER, content)
        self.assertEqual(row["body"], stored_body)
        self.assertNotIn(ADDRESS, row["body"])

    def test_us_followup_gets_private_commercial_footer_without_mutating_sheet_copy(self):
        row = {
            "lead_id": "lead-us",
            "country": "US",
            "email": "lead@example.org",
            "subject": "Idea",
            "body": f"This is a commercial message.\n{d.POSTAL_PLACEHOLDER}",
            "followup_body": "Hi team,\n\nJust following up once.\n\nBest regards,\nAndrew Baeten",
            "message_id": "<initial@example.com>",
        }
        stored_followup = row["followup_body"]
        with patch.dict(os.environ, {"OUTREACH_POSTAL_ADDRESS": ADDRESS}, clear=False):
            msg = d._build_message_with_private_postal(row, mailbox(), 2)
        content = msg.get_content()
        self.assertIn("This is a commercial message.", content)
        self.assertIn(ADDRESS, content)
        self.assertEqual(row["followup_body"], stored_followup)
        self.assertNotIn(ADDRESS, row["followup_body"])

    def test_us_postal_injection_fails_closed_without_private_config(self):
        row = {"country": "US"}
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "OUTREACH_POSTAL_ADDRESS"):
                d._inject_private_postal(row, d.POSTAL_PLACEHOLDER)

    def test_us_postal_injection_requires_placeholder(self):
        row = {"country": "US"}
        with patch.dict(os.environ, {"OUTREACH_POSTAL_ADDRESS": ADDRESS}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "private postal placeholder"):
                d._inject_private_postal(row, "This is a commercial message.")

    def test_non_us_body_is_unchanged(self):
        self.assertEqual(d._inject_private_postal({"country": "NL"}, "Body"), "Body")
        self.assertEqual(d._append_private_us_footer({"country": "NL"}, "Body"), "Body")

    def test_process_replaces_external_verification_and_message_gates(self):
        original_process = d.runtime.process
        original_gate = d.runtime.verification_is_fresh
        original_message = d.runtime.build_message
        original_sequence = d.runtime.build_sequence_message
        try:
            d.runtime.process = lambda: 7
            result = d.process()
            self.assertEqual(result, 7)
            self.assertIs(d.runtime.verification_is_fresh, d._no_external_verifier_required)
            self.assertIs(d.runtime.build_message, d._build_message_with_private_postal)
            self.assertIs(d.runtime.build_sequence_message, d._build_sequence_message_with_private_postal)
        finally:
            d.runtime.process = original_process
            d.runtime.verification_is_fresh = original_gate
            d.runtime.build_message = original_message
            d.runtime.build_sequence_message = original_sequence


if __name__ == "__main__":
    unittest.main()
