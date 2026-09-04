import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import outreach_imap_draft as mod


class FakeIMAP:
    def __init__(self, rows=None, search_ids=b"41", login_status="OK", append_status="OK"):
        self.rows = rows or [b'(\\HasNoChildren \\Drafts) "/" "Drafts"']
        self.search_ids = search_ids
        self.login_status = login_status
        self.append_status = append_status
        self.append_calls = []
        self.selected = []
        self.search_calls = []
        self.logged_out = False

    def login(self, user, password):
        self.user = user
        self.password = password
        return self.login_status, [b"logged"]

    def list(self):
        return "OK", self.rows

    def append(self, folder, flags, date_time, message):
        self.append_calls.append((folder, flags, date_time, message))
        return self.append_status, [b"appended"]

    def select(self, folder, readonly=False):
        self.selected.append((folder, readonly))
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        self.search_calls.append((charset, criteria))
        return "OK", [self.search_ids]

    def logout(self):
        self.logged_out = True
        return "BYE", [b"logout"]


def mailbox(**overrides):
    values = dict(
        mailbox_id="primary",
        enabled=True,
        imap_host="mail.andrewbaeten.nl",
        imap_port=993,
        mail_user="info@andrewbaeten.nl",
        mail_password="secret",
        sender_name="Andrew Baeten",
        sender_email="info@andrewbaeten.nl",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class DraftTests(unittest.TestCase):
    def test_special_use_drafts_wins(self):
        rows = [
            b'(\\HasNoChildren) "/" "Concepten-oud"',
            b'(\\HasNoChildren \\Drafts) "/" "Drafts"',
        ]
        self.assertEqual(mod.detect_drafts_folder(rows), "Drafts")

    def test_dutch_concepten_fallback(self):
        rows = [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren) "/" "Concepten"']
        self.assertEqual(mod.detect_drafts_folder(rows), "Concepten")

    def test_ambiguous_fallback_fails_closed(self):
        rows = [b'(\\HasNoChildren) "/" "Drafts"', b'(\\HasNoChildren) "/" "Concepten"']
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            mod.detect_drafts_folder(rows)

    def test_explicit_folder_must_exist_exactly(self):
        rows = [b'(\\HasNoChildren) "/" "Drafts"']
        with self.assertRaisesRegex(RuntimeError, "not found"):
            mod.detect_drafts_folder(rows, explicit_folder="Concepten")

    def test_multiple_mailboxes_require_explicit_id(self):
        with self.assertRaisesRegex(RuntimeError, "OUTREACH_DRAFT_MAILBOX_ID"):
            mod.choose_mailbox([mailbox(), mailbox(mailbox_id="secondary", sender_email="two@andrewbaeten.nl")])

    def test_self_only_rejects_non_self_recipient(self):
        with self.assertRaisesRegex(RuntimeError, "self-only"):
            mod.append_verified_draft(
                mailbox(), recipient="prospect@example.com", subject="Test", body="Body", test_id="t-1",
                imap_factory=lambda *a, **k: FakeIMAP(), sleep=lambda _s: None,
            )

    def test_missing_password_blocks_before_network(self):
        called = []
        with self.assertRaisesRegex(RuntimeError, "OUTREACH_MAIL_PASSWORD"):
            mod.append_verified_draft(
                mailbox(mail_password=""), recipient="info@andrewbaeten.nl", subject="Test", body="Body", test_id="t-1",
                imap_factory=lambda *a, **k: called.append(True), sleep=lambda _s: None,
            )
        self.assertEqual(called, [])

    def test_append_uses_draft_flag_and_readback_header(self):
        fake = FakeIMAP(search_ids=b"41 42")
        receipt = mod.append_verified_draft(
            mailbox(), recipient="info@andrewbaeten.nl", subject="TEST draft", body="Only a draft", test_id="run-123",
            imap_factory=lambda *a, **k: fake, sleep=lambda _s: None,
        )
        self.assertEqual(receipt.folder, "Drafts")
        self.assertEqual(receipt.message_ids, ("41", "42"))
        self.assertEqual(fake.append_calls[0][1], r"(\Draft)")
        self.assertIn(b"X-Webactueel-Draft-Test-ID: run-123", fake.append_calls[0][3])
        self.assertIn("X-Webactueel-Draft-Test-ID", fake.search_calls[0][1])
        self.assertTrue(fake.logged_out)

    def test_append_failure_does_not_claim_success(self):
        fake = FakeIMAP(append_status="NO")
        with self.assertRaisesRegex(RuntimeError, "APPEND failed"):
            mod.append_verified_draft(
                mailbox(), recipient="info@andrewbaeten.nl", subject="Test", body="Body", test_id="t-1",
                imap_factory=lambda *a, **k: fake, sleep=lambda _s: None,
            )

    def test_readback_failure_is_blocked(self):
        fake = FakeIMAP(search_ids=b"")
        with self.assertRaisesRegex(RuntimeError, "readback"):
            mod.append_verified_draft(
                mailbox(), recipient="info@andrewbaeten.nl", subject="Test", body="Body", test_id="t-1",
                imap_factory=lambda *a, **k: fake, retries=2, delay_seconds=0, sleep=lambda _s: None,
            )

    def test_module_has_no_smtp_send_dependency(self):
        text = (ROOT / "scripts" / "outreach_imap_draft.py").read_text(encoding="utf-8")
        self.assertNotIn("smtplib", text)
        self.assertNotIn("sendmail(", text)
        self.assertNotIn("send_message(", text)


if __name__ == "__main__":
    unittest.main()
