from __future__ import annotations

import unittest
from email.parser import BytesParser
from email.policy import default
from unittest.mock import patch

from myhost_draft import build_message, create_drafts, exact_message_matches


class FakeIMAP:
    def __init__(self):
        self.messages = []
        self.deleted = set()

    def list(self):
        return "OK", [b'(\\HasNoChildren \\Drafts) "/" "Drafts"']

    def select(self, folder, readonly=True):
        return "OK", [str(len(self.messages)).encode()]

    def search(self, charset, *criteria):
        if criteria == ("ALL",):
            return "OK", [b" ".join(str(i).encode() for i in range(1, len(self.messages) + 1))]
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

    def store(self, message_id, command, flags):
        self.deleted.add(int(message_id) - 1)
        return "OK", [b"STORE completed"]

    def expunge(self):
        self.messages = [
            raw for index, raw in enumerate(self.messages) if index not in self.deleted
        ]
        self.deleted.clear()
        return "OK", [b"EXPUNGE completed"]

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

    def test_review_draft_requires_explicit_review_required_basis(self):
        for basis in ("", "unverified", "unknown", "pass"):
            with self.subTest(basis=basis):
                with self.assertRaises(RuntimeError):
                    build_message(self.row(status="review_draft", basis=basis))

    def test_invalid_draft_ready_basis_is_not_silently_skipped(self):
        with self.assertRaises(RuntimeError):
            create_drafts({"rows": [self.row(status="draft_ready", basis="review_required")]})

    def test_batch_is_fully_preflighted_before_first_imap_write(self):
        client = FakeIMAP()
        good = self.row()
        bad = self.row(basis="unverified")
        bad["lead_id"] = "growth-1123456789abcdefabcd"
        bad["email"] = "other@voorbeeld.nl"
        with patch("myhost_draft.connect_imap", return_value=client):
            with self.assertRaises(RuntimeError):
                create_drafts({"rows": [good, bad]})
        self.assertEqual(client.messages, [])

    def test_zero_ready_rows_needs_no_mail_password(self):
        result = create_drafts({"rows": [{"status": "no_public_email"}]})
        self.assertEqual(result["eligible_count"], 0)
        self.assertEqual(result["smtp_send"], "not_available")

    def test_rewrite_existing_only_does_not_create_missing_draft(self):
        client = FakeIMAP()
        with patch("myhost_draft.connect_imap", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "exactly one existing draft"):
                create_drafts({"rows": [self.row()]}, rewrite_existing_only=True)
        self.assertEqual(client.messages, [])

    def test_rewrite_existing_only_preflights_entire_batch_before_updates(self):
        client = FakeIMAP()
        original = self.row()
        with patch("myhost_draft.connect_imap", return_value=client):
            create_drafts({"rows": [original]})

        updated = {**original, "body": "Gewijzigde gecontroleerde versie."}
        missing = {
            **self.row(),
            "lead_id": "growth-1123456789abcdefabcd",
            "email": "ander@voorbeeld.nl",
            "subject": "Idee voor ander",
        }
        with patch("myhost_draft.connect_imap", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "exactly one existing draft"):
                create_drafts(
                    {"rows": [updated, missing]},
                    rewrite_existing_only=True,
                )

        self.assertEqual(len(client.messages), 1)
        actual = BytesParser(policy=default).parsebytes(client.messages[0])
        self.assertEqual(actual.get("Subject"), original["subject"])
        self.assertEqual(actual.get_content().strip(), original["body"])

    def test_create_readback_and_idempotency(self):
        client = FakeIMAP()
        with patch("myhost_draft.connect_imap", return_value=client):
            first = create_drafts({"rows": [self.row()]})
        self.assertEqual(first["created_count"], 1)
        self.assertEqual(first["review_required_count"], 1)
        self.assertEqual(len(first["items"]), 1)
        self.assertEqual(first["items"][0]["lead_id"], self.row()["lead_id"])
        self.assertEqual(first["items"][0]["to"], self.row()["email"])
        self.assertEqual(first["items"][0]["subject"], self.row()["subject"])
        self.assertEqual(first["items"][0]["body"], self.row()["body"])
        self.assertEqual(first["items"][0]["review_status"], "contact-basis")
        self.assertEqual(first["items"][0]["outcome"], "created")

        with patch("myhost_draft.connect_imap", return_value=client):
            second = create_drafts({"rows": [self.row()]})
        self.assertEqual(second["existing_count"], 1)
        self.assertEqual(second["items"][0]["outcome"], "existing")
        self.assertEqual(len(client.messages), 1)

        _, expected = build_message(self.row())
        actual = BytesParser(policy=default).parsebytes(client.messages[0])
        self.assertTrue(exact_message_matches(actual, expected))

    def test_changed_existing_draft_is_safely_replaced(self):
        client = FakeIMAP()
        with patch("myhost_draft.connect_imap", return_value=client):
            create_drafts({"rows": [self.row()]})

        updated = self.row()
        updated["body"] = "Nieuwe gecontroleerde versie."
        with patch("myhost_draft.connect_imap", return_value=client):
            result = create_drafts({"rows": [updated]})

        self.assertEqual(result["replaced_count"], 1)
        self.assertEqual(result["items"][0]["outcome"], "replaced")
        self.assertEqual(result["items"][0]["body"], updated["body"])
        self.assertEqual(len(client.messages), 1)
        _, expected = build_message(updated)
        actual = BytesParser(policy=default).parsebytes(client.messages[0])
        self.assertTrue(exact_message_matches(actual, expected))


if __name__ == "__main__":
    unittest.main()
