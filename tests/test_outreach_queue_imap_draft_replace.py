from __future__ import annotations

import unittest
from dataclasses import dataclass

from outreach_queue_imap_draft_replace import replace_verified_draft


@dataclass
class Mailbox:
    mailbox_id: str = "primary"
    sender_name: str = "Andrew Baeten"
    sender_email: str = "info@andrewbaeten.nl"
    mail_user: str = "info@andrewbaeten.nl"
    mail_password: str = "secret"
    imap_host: str = "mail.example.test"
    imap_port: int = 993


class FakeImap:
    def __init__(self, *_args, **_kwargs):
        self.messages = {"1": {"test_id": "old-test", "deleted": False}}
        self.next_id = 2
        self.append_calls = 0
        self.store_calls = 0

    def login(self, *_args): return "OK", []
    def list(self): return "OK", [b'(\\Drafts) "/" "Drafts"']
    def select(self, *_args, **_kwargs): return "OK", []
    def search(self, _charset, _header, _name, value):
        target = value.strip('"')
        ids = [mid for mid, data in self.messages.items() if data["test_id"] == target and not data["deleted"]]
        return "OK", [" ".join(ids).encode()]
    def append(self, _folder, _flags, _date, payload):
        text = payload.decode("utf-8", errors="replace")
        marker = "X-Webactueel-Draft-Test-ID: "
        test_id = next(line[len(marker):].strip() for line in text.splitlines() if line.startswith(marker))
        self.messages[str(self.next_id)] = {"test_id": test_id, "deleted": False}
        self.next_id += 1
        self.append_calls += 1
        return "OK", []
    def store(self, message_id, *_args):
        self.messages[str(message_id)]["deleted"] = True
        self.store_calls += 1
        return "OK", []
    def expunge(self):
        self.messages = {mid: data for mid, data in self.messages.items() if not data["deleted"]}
        return "OK", []
    def logout(self): return "BYE", []


class DraftReplaceTests(unittest.TestCase):
    def test_append_verify_then_delete_exact_old_draft(self):
        fake = FakeImap()
        receipt = replace_verified_draft(
            Mailbox(),
            recipient="sales@example.com",
            subject="Quote requests at Example Co",
            body="Current reviewed copy",
            old_test_id="old-test",
            new_test_id="new-test",
            imap_factory=lambda *_args, **_kwargs: fake,
        )
        self.assertEqual(receipt.old_test_id, "old-test")
        self.assertEqual(receipt.new_test_id, "new-test")
        self.assertEqual(fake.append_calls, 1)
        self.assertEqual(fake.store_calls, 1)
        self.assertFalse(any(data["test_id"] == "old-test" for data in fake.messages.values()))
        self.assertEqual(sum(data["test_id"] == "new-test" for data in fake.messages.values()), 1)

    def test_refuses_missing_old_draft_without_appending(self):
        fake = FakeImap()
        fake.messages.clear()
        with self.assertRaises(RuntimeError):
            replace_verified_draft(
                Mailbox(), recipient="sales@example.com", subject="Subject", body="Body",
                old_test_id="old-test", new_test_id="new-test",
                imap_factory=lambda *_args, **_kwargs: fake,
            )
        self.assertEqual(fake.append_calls, 0)

    def test_refuses_duplicate_new_id_without_appending(self):
        fake = FakeImap()
        fake.messages["2"] = {"test_id": "new-test", "deleted": False}
        with self.assertRaises(RuntimeError):
            replace_verified_draft(
                Mailbox(), recipient="sales@example.com", subject="Subject", body="Body",
                old_test_id="old-test", new_test_id="new-test",
                imap_factory=lambda *_args, **_kwargs: fake,
            )
        self.assertEqual(fake.append_calls, 0)


if __name__ == "__main__":
    unittest.main()
