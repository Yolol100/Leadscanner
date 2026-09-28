from __future__ import annotations

import unittest
from email.message import EmailMessage
from unittest.mock import patch

from myhost_growth_inventory import inventory_growth_drafts


class FakeIMAP:
    def __init__(self):
        self.messages = []

    def list(self):
        return "OK", [b'(\\HasNoChildren \\Drafts) "/" "Drafts"']

    def select(self, folder, readonly=True):
        self.readonly = readonly
        return "OK", [str(len(self.messages)).encode()]

    def search(self, charset, *criteria):
        if criteria == ("ALL",):
            return "OK", [b" ".join(str(i).encode() for i in range(1, len(self.messages) + 1))]
        return "OK", [b""]

    def fetch(self, message_id, query):
        return "OK", [(b"1 (RFC822)", self.messages[int(message_id) - 1])]

    def logout(self):
        return "BYE", [b"logout"]


def raw_message(lead_id: str | None) -> bytes:
    msg = EmailMessage()
    msg["From"] = "Andrew <info@andrewbaeten.nl>"
    msg["To"] = "info@example.nl"
    msg["Subject"] = "Test"
    if lead_id:
        msg["X-Webactueel-Lead-ID"] = lead_id
    msg.set_content("Body")
    return msg.as_bytes()


class InventoryTests(unittest.TestCase):
    def test_inventory_reads_growth_ids_only_and_is_read_only(self):
        client = FakeIMAP()
        client.messages = [
            raw_message("growth-0123456789abcdefabcd"),
            raw_message("not-growth"),
            raw_message(None),
        ]
        with patch("myhost_growth_inventory.connect_imap", return_value=client):
            result = inventory_growth_drafts()
        self.assertEqual(result["growth_draft_count"], 1)
        self.assertEqual(result["growth_lead_ids"], ["growth-0123456789abcdefabcd"])
        self.assertTrue(result["safety"]["read_only"])
        self.assertFalse(result["safety"]["draft_created"])
        self.assertFalse(result["safety"]["draft_deleted"])
        self.assertEqual(result["safety"]["smtp_send"], "not_available")
        self.assertTrue(client.readonly)


if __name__ == "__main__":
    unittest.main()
