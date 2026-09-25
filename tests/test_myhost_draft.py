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
        return "OK", [(b"1 (RFC822)", self.messages[int(message_id) - 1])]

    def append(self, folder, flags, date_time, raw):
        self.messages.append(raw)
        return "OK", [b"APPEND completed"]

    def logout(self):
        return "BYE", [b"logout"]


class DraftTests(unittest.TestCase):
    def row(self, status="review_draft", basis="review_required"):
        return {
            "lead_id": "growth-0123456789abcdefabcd",
            "company": "Voorbeeld BV",
            "website": "https://voorbeeld.nl",
            "email": "info@voorbeeld.nl",
            "subject": "Idee voor Voorbeeld BV",
            "body": "Volledig mailconcept voor handmatige beoordeling.",
            "status": status,
            "contact_basis_status": basis,
        }

    def test_review_draft_builds_message_with_review_header(self):
        _, msg = build_message(self.row())
        self.assertEqual(msg["To"], "info@voorbeeld.nl")
        self.assertEqual(msg["Subject"], "Idee voor Voorbeeld BV")
        self.assertEqual(msg["X-Webactueel-Review-Required"], "contact-basis")

    def test_passed_draft_ready_has_no_review_header(self):
        _, msg = build_message(self.row(status="draft_ready", basis="pass"))
        self.assertIsNone(msg["X-Webactueel-Review-Required"])

    def test_noncanonical_growth_lead_id_is_rejected(self):
        row = self.row()
        row["lead_id"] = "lead-0123456789abcdefabcd"
        with self.assertRaises(RuntimeError):
            build_message(row)

    def test_invalid_status_is_rejected(self):
        with self.assertRaises(RuntimeError):
            build_message(self.row(status="email_found_not_selected"))

    def test_zero_ready_rows_needs_no_mail_password(self):
        result = create_drafts({"rows": [{"status": "no_public_email"}]})
        self.assertEqual(result["eligible_count"], 0)
        self.assertEqual(result["smtp_send"], "not_available")

    def test_create_readback_and_idempotency(self):
        client = FakeIMAP()
        with patch("myhost_draft.connect_imap", return_value=client):
            first = create_drafts({"rows": [self.row()]})
        self.assertEqual(first["created_count"], 1)
        self.assertEqual(first["review_required_count"], 1)

        with patch("myhost_draft.connect_imap", return_value=client):
            second = create_drafts({"rows": [self.row()]})
        self.assertEqual(second["existing_count"], 1)
        self.assertEqual(len(client.messages), 1)

        _, expected = build_message(self.row())
        actual = BytesParser(policy=default).parsebytes(client.messages[0])
        self.assertTrue(exact_message_matches(actual, expected))


if __name__ == "__main__":
    unittest.main()
