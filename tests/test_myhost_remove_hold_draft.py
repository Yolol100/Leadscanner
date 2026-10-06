from __future__ import annotations

import unittest
from email.message import EmailMessage
from unittest.mock import patch

from myhost_remove_hold_draft import remove_hold_draft


class FakeIMAP:
    def __init__(self, raw: bytes, count: int = 1, *, uidplus: bool = True):
        self.raw = raw
        self.capabilities = (b"IMAP4REV1", b"UIDPLUS") if uidplus else (b"IMAP4REV1",)
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
        return (
            "OK",
            [b" ".join(str(i).encode() for i in range(1, self.count + 1))],
        )

    def fetch(self, message_id, query):
        if query == "(UID)":
            return "OK", [(b"1 (UID 10)", b"")]
        return "OK", [(b"1 (RFC822)", self.raw)]

    def uid(self, command, *args):
        command = command.casefold()
        if command == "fetch":
            return "OK", [(b"1 (UID 10 RFC822)", self.raw)]
        if command == "store":
            self.deleted = True
            return "OK", [b""]
        if command == "expunge":
            return "OK", [b"10"]
        raise AssertionError((command, args))

    def store(self, message_id, op, flags):
        raise AssertionError("sequence STORE must not be used")

    def expunge(self):
        raise AssertionError("global EXPUNGE must not be used")

    def logout(self):
        return "BYE", [b"logout"]


class RemoveHoldDraftTests(unittest.TestCase):
    def _message(self, lead_id: str, review: str = "contact-basis"):
        msg = EmailMessage()
        msg["From"] = "Andrew <info@andrewbaeten.nl>"
        msg["To"] = "info@example.nl"
        msg["Subject"] = "Updated draft version"
        msg["X-Webactueel-Lead-ID"] = lead_id
        msg["X-Webactueel-Review-Required"] = review
        msg.set_content("A legitimately changed body")
        return msg

    def test_removes_exact_identity_review_draft(self):
        lead_id = "growth-0123456789abcdefabcd"
        client = FakeIMAP(self._message(lead_id).as_bytes())

        with patch(
            "myhost_remove_hold_draft.connect_imap",
            return_value=client,
        ):
            result = remove_hold_draft(lead_id)

        self.assertEqual(result["removed_count"], 1)
        self.assertEqual(result["final_count"], 0)
        self.assertFalse(result["automatic_send"])
        self.assertEqual(result["smtp_send"], "not_available")
        self.assertTrue(client.deleted)

    def test_already_absent_is_idempotent(self):
        lead_id = "growth-0123456789abcdefabcd"
        client = FakeIMAP(b"", count=0)

        with patch(
            "myhost_remove_hold_draft.connect_imap",
            return_value=client,
        ):
            result = remove_hold_draft(lead_id)

        self.assertEqual(result["removed_count"], 0)
        self.assertEqual(result["final_count"], 0)

    def test_multiple_matches_block_removal(self):
        lead_id = "growth-0123456789abcdefabcd"
        client = FakeIMAP(self._message(lead_id).as_bytes(), count=2)

        with patch(
            "myhost_remove_hold_draft.connect_imap",
            return_value=client,
        ):
            with self.assertRaisesRegex(RuntimeError, "at most one"):
                remove_hold_draft(lead_id)

        self.assertFalse(client.deleted)

    def test_uidplus_missing_blocks_before_hold_mutation(self):
        lead_id = "growth-0123456789abcdefabcd"
        client = FakeIMAP(self._message(lead_id).as_bytes(), uidplus=False)
        with patch("myhost_remove_hold_draft.connect_imap", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "UIDPLUS"):
                remove_hold_draft(lead_id)
        self.assertFalse(client.deleted)

    def test_non_review_draft_blocks_removal(self):
        lead_id = "growth-0123456789abcdefabcd"
        client = FakeIMAP(
            self._message(lead_id, review="pass").as_bytes()
        )

        with patch(
            "myhost_remove_hold_draft.connect_imap",
            return_value=client,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "not review-required",
            ):
                remove_hold_draft(lead_id)

        self.assertFalse(client.deleted)


if __name__ == "__main__":
    unittest.main()
