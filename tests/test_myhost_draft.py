from __future__ import annotations

import unittest
from email.parser import BytesParser
from email.policy import default
from unittest.mock import patch

from myhost_draft import build_message, create_drafts, exact_message_matches


class FakeIMAP:
    def __init__(self):
        self.messages = []

    def list(self):
        return "OK", [b'(\\HasNoChildren \\Drafts) "/" "Drafts"']

    def select(self, folder, readonly=True):
        return "OK", [str(len(self.messages)).encode()]

    def search(self, charset, *criteria):
        lead_id = str(criteria[-1]).strip('"')
        found = []
        for index, raw in enumerate(self.messages, start=1):
            msg = BytesParser(policy=default).parsebytes(raw)
            if str(msg.get("X-Webactueel-Lead-ID", "")) == lead_id:
                found.append(str(index).encode())
        return "OK", [b" ".join(found)]

    def fetch(self, message_id, query):
        raw = self.messages[int(message_id) - 1]
        return "OK", [(b"1 (RFC822)", raw)]

    def append(self, folder, flags, date_time, raw):
        self.messages.append(raw)
        return "OK", [b"APPEND completed"]

    def logout(self):
        return "BYE", [b"logout"]


class DraftTests(unittest.TestCase):
    def row(self):
        return {
            "company": "Voorbeeld BV",
            "website": "https://voorbeeld.nl",
            "email": "info@voorbeeld.nl",
            "subject": "Korte vraag over online groei",
            "body": "Hoi Voorbeeld BV, dit is een geldig concept.",
            "status": "draft_ready",
            "contact_basis_status": "pass",
        }

    def test_only_draft_ready_pass_row_builds_message(self):
        lead_id, msg = build_message(self.row())
        self.assertTrue(lead_id.startswith("growth-"))
        self.assertEqual(msg["To"], "info@voorbeeld.nl")
        self.assertEqual(msg["Subject"], "Korte vraag over online groei")

    def test_unapproved_row_is_rejected(self):
        row = self.row()
        row["contact_basis_status"] = "unverified"
        with self.assertRaises(RuntimeError):
            build_message(row)

    def test_zero_ready_rows_needs_no_mail_password(self):
        result = create_drafts({"rows": [{"status": "needs_contact_basis"}]})
        self.assertEqual(result["eligible_count"], 0)
        self.assertEqual(result["created_count"], 0)
        self.assertEqual(result["smtp_send"], "not_available")

    def test_create_and_readback_is_idempotent(self):
        client = FakeIMAP()
        with patch("myhost_draft.connect_imap", return_value=client):
            first = create_drafts({"rows": [self.row()]})
        self.assertEqual(first["created_count"], 1)
        self.assertEqual(len(client.messages), 1)

        client2 = client
        with patch("myhost_draft.connect_imap", return_value=client2):
            second = create_drafts({"rows": [self.row()]})
        self.assertEqual(second["existing_count"], 1)
        self.assertEqual(len(client.messages), 1)

        _, expected = build_message(self.row())
        actual = BytesParser(policy=default).parsebytes(client.messages[0])
        self.assertTrue(exact_message_matches(actual, expected))


if __name__ == "__main__":
    unittest.main()
