from __future__ import annotations

import unittest
from email.message import EmailMessage
from unittest.mock import patch

from myhost_remove_duplicate_draft import remove_growth_draft


class FakeIMAP:
    def __init__(self, raw: bytes, count: int = 1):
        self.raw = raw
        self.count = count
        self.deleted = False
        self.readonly = True

    def list(self):
        return "OK", [b'(\\HasNoChildren \\Drafts) "/" "Drafts"']

    def select(self, folder, readonly=True):
        self.readonly = readonly
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        if self.deleted or self.count == 0:
            return "OK", [b""]
        return "OK", [b" ".join(str(i).encode() for i in range(1, self.count + 1))]

    def fetch(self, message_id, query):
        return "OK", [(b"1 (RFC822)", self.raw)]

    def store(self, message_id, op, flags):
        self.deleted = True
        return "OK", [b""]

    def expunge(self):
        return "OK", [b"1"]

    def logout(self):
        return "BYE", [b"logout"]


class RemoveDuplicateDraftTests(unittest.TestCase):
    def test_removes_exact_growth_draft_and_never_sends(self):
        lead_id = "growth-0123456789abcdefabcd"
        msg = EmailMessage()
        msg["From"] = "Andrew <info@andrewbaeten.nl>"
        msg["To"] = "info@example.nl"
        msg["Subject"] = "Test"
        msg["X-Webactueel-Lead-ID"] = lead_id
        msg["X-Webactueel-Review-Required"] = "contact-basis"
        msg.set_content("Body")
        expected = [{"to": "info@example.nl", "subject": "Test", "body": "Body", "review_status": "contact-basis"}]
        client = FakeIMAP(msg.as_bytes())

        with patch("myhost_remove_duplicate_draft.connect_imap", return_value=client):
            result = remove_growth_draft(lead_id, expected)

        self.assertEqual(result["removed_count"], 1)
        self.assertEqual(result["final_count"], 0)
        self.assertFalse(result["automatic_send"])
        self.assertEqual(result["smtp_send"], "not_available")
        self.assertTrue(client.deleted)

    def test_mismatch_stops_without_deleting(self):
        lead_id = "growth-0123456789abcdefabcd"
        msg = EmailMessage()
        msg["To"] = "info@example.nl"
        msg["Subject"] = "Changed"
        msg["X-Webactueel-Lead-ID"] = lead_id
        msg["X-Webactueel-Review-Required"] = "contact-basis"
        msg.set_content("Body")
        client = FakeIMAP(msg.as_bytes())
        expected = [{"to": "info@example.nl", "subject": "Test", "body": "Body", "review_status": "contact-basis"}]

        with patch("myhost_remove_duplicate_draft.connect_imap", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "version mismatch"):
                remove_growth_draft(lead_id, expected)

        self.assertFalse(client.deleted)

    def test_already_absent_is_idempotent(self):
        lead_id = "growth-0123456789abcdefabcd"
        client = FakeIMAP(b"", count=0)
        expected = [{"to": "info@example.nl", "subject": "Test", "body": "Body", "review_status": "contact-basis"}]

        with patch("myhost_remove_duplicate_draft.connect_imap", return_value=client):
            result = remove_growth_draft(lead_id, expected)

        self.assertEqual(result["removed_count"], 0)
        self.assertEqual(result["final_count"], 0)

    def test_duplicate_matches_block_removal(self):
        lead_id = "growth-0123456789abcdefabcd"
        msg = EmailMessage()
        msg["To"] = "info@example.nl"
        msg["Subject"] = "Test"
        msg["X-Webactueel-Lead-ID"] = lead_id
        msg["X-Webactueel-Review-Required"] = "contact-basis"
        msg.set_content("Body")
        client = FakeIMAP(msg.as_bytes(), count=2)
        expected = [{"to": "info@example.nl", "subject": "Test", "body": "Body", "review_status": "contact-basis"}]

        with patch("myhost_remove_duplicate_draft.connect_imap", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "at most one"):
                remove_growth_draft(lead_id, expected)

        self.assertFalse(client.deleted)


if __name__ == "__main__":
    unittest.main()

