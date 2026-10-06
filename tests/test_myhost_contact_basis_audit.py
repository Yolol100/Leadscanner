from __future__ import annotations

import unittest
from email.message import EmailMessage
from pathlib import Path

from myhost_contact_basis_audit import (
    email_hash,
    is_ready,
    is_review,
    make_ready,
    make_review,
    message_matches,
    remove_and_verify,
    replace_and_verify,
    validate_hashes,
)


class FakeNoUIDPlus:
    capabilities = (b"IMAP4REV1",)

    def __init__(self):
        self.append_calls = 0

    def select(self, folder, readonly=True):
        return "OK", [b"1"]

    def append(self, folder, flags, date_time, raw):
        self.append_calls += 1
        return "OK", [b""]


class ContactBasisAuditTests(unittest.TestCase):
    def message(self) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = "Andrew <info@andrewbaeten.nl>"
        msg["To"] = "sales@example.com"
        msg["Subject"] = "Idea for Example"
        msg["X-Webactueel-Lead-ID"] = "growth-1234567890abcdef1234"
        msg["X-Webactueel-Review-Required"] = "contact-basis"
        msg.set_content("Hello\n")
        return msg

    def test_hash_is_stable_and_casefolded(self):
        self.assertEqual(email_hash(" Sales@Example.com "), email_hash("sales@example.com"))

    def test_validate_hashes_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            validate_hashes(["not-a-hash"])

    def test_contact_basis_mutations_require_uidplus_before_write(self):
        lead_id = "growth-1234567890abcdef1234"
        expected = self.message()
        for operation in ("replace", "remove"):
            with self.subTest(operation=operation):
                client = FakeNoUIDPlus()
                with self.assertRaisesRegex(RuntimeError, "UIDPLUS"):
                    if operation == "replace":
                        replace_and_verify(client, "Drafts", lead_id, b"1", expected)
                    else:
                        remove_and_verify(client, "Drafts", lead_id, b"1")
                self.assertEqual(client.append_calls, 0)

    def test_all_myhost_scripts_forbid_global_expunge_and_sequence_store(self):
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        offenders = []
        for path in sorted(scripts.glob("myhost_*.py")):
            text = path.read_text(encoding="utf-8")
            if ".expunge(" in text:
                offenders.append(f"{path.name}: global expunge")
            if "client.store(" in text:
                offenders.append(f"{path.name}: sequence store")
        self.assertEqual(offenders, [])

    def test_review_to_ready_and_back_is_exact(self):
        review = self.message()
        self.assertTrue(is_review(review))
        ready = make_ready(review)
        self.assertTrue(is_ready(ready))
        self.assertEqual(ready.get("X-Webactueel-Contact-Basis-Source"), "registry-approved-official-web")
        self.assertTrue(message_matches(ready, ready))
        restored = make_review(ready)
        self.assertTrue(is_review(restored))
        self.assertIsNone(restored.get("X-Webactueel-Contact-Basis"))
        self.assertIsNone(restored.get("X-Webactueel-Contact-Basis-Source"))
        self.assertEqual(restored.get("To"), review.get("To"))
        self.assertEqual(restored.get("Subject"), review.get("Subject"))
        self.assertEqual(restored.get_content().strip(), review.get_content().strip())


if __name__ == "__main__":
    unittest.main()
