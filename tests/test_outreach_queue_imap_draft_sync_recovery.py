from __future__ import annotations

import sys
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import outreach_queue_imap_draft_sync as mod


class PersistentFakeImap:
    def __init__(self):
        self.messages: dict[str, bytes] = {}
        self.next_uid = 1
        self.fail_first_post_append_select = False
        self.failed_post_append_select = False
        self.append_calls = 0
        self._after_append = False

    def login(self, *_args):
        return "OK", []

    def list(self):
        return "OK", [b'(\\HasNoChildren \\Drafts) "/" "Drafts"']

    def select(self, *_args, **_kwargs):
        if self._after_append and self.fail_first_post_append_select and not self.failed_post_append_select:
            self.failed_post_append_select = True
            self._after_append = False
            return "NO", []
        self._after_append = False
        return "OK", []

    def uid(self, command, *args):
        command = str(command).lower()
        if command == "search":
            criteria = [str(value) for value in args]
            if "ALL" in criteria:
                ids = sorted(self.messages, key=int)
                return "OK", [" ".join(ids).encode()]
            if "HEADER" in criteria and "X-Webactueel-Draft-Test-ID" in criteria:
                target = criteria[-1].strip('"')
                ids = []
                for uid, payload in self.messages.items():
                    msg = BytesParser(policy=policy.default).parsebytes(payload)
                    if str(msg.get("X-Webactueel-Draft-Test-ID", "")).strip() == target:
                        ids.append(uid)
                return "OK", [" ".join(ids).encode()]
            return "OK", [b""]
        if command == "fetch":
            uid = str(args[0])
            payload = self.messages[uid]
            return "OK", [(b"payload", payload)]
        if command == "store":
            uid = str(args[0])
            self.messages.pop(uid, None)
            return "OK", []
        raise AssertionError(f"unexpected uid command: {command}")

    def append(self, _folder, _flags, _date, payload):
        uid = str(self.next_uid)
        self.next_uid += 1
        self.messages[uid] = bytes(payload)
        self.append_calls += 1
        self._after_append = True
        return "OK", []

    def expunge(self):
        return "OK", []

    def logout(self):
        return "BYE", []


def mailbox():
    return SimpleNamespace(
        mailbox_id="primary",
        sender_name="Andrew Baeten",
        sender_email="info@andrewbaeten.nl",
        mail_user="info@andrewbaeten.nl",
        mail_password="secret",
        imap_host="mail.example.test",
        imap_port=993,
    )


def queue_row(subject="Subject A"):
    return {
        "lead_id": "lead-a",
        "email": "sales@example.com",
        "subject": subject,
        "body": "Reviewed body",
        "status": "manual_review",
        "compliance_status": "COMPLIANCE_PASSED",
        "stage": "1",
        "sender_email": "info@andrewbaeten.nl",
        "sent_at": "",
        "replied_at": "",
        "bounced_at": "",
        "country": "NL",
    }


class DraftSyncRecoveryTests(unittest.TestCase):
    def _run(self, fake, row_provider, *, apply):
        def fake_get_values(_service, _spreadsheet_id, sheet):
            if sheet == mod.QUEUE_SHEET:
                row = row_provider()
                headers = list(row)
                return [headers, [row[key] for key in headers]]
            return [["email", "domain", "reason"]]

        mb = mailbox()
        with (
            patch.object(mod, "build_sheets_service", return_value=object()),
            patch.object(mod, "get_values", side_effect=fake_get_values),
            patch.object(mod, "enabled_mailboxes", return_value=[mb]),
            patch.object(mod, "load_mailboxes_from_env", return_value=[mb]),
            patch.object(mod, "choose_mailbox", return_value=mb),
            patch.object(mod, "validate_queue_row", return_value=[]),
            patch.object(mod, "inject_private_postal_for_draft", side_effect=lambda _row, body: body),
            patch.object(mod.imaplib, "IMAP4_SSL", side_effect=lambda *_a, **_k: fake),
        ):
            return mod.sync_queue_drafts(
                lead_prefix="lead-",
                expected_count=1,
                spreadsheet_id="sheet-id",
                apply=apply,
            )

    def test_retry_converges_after_append_succeeded_but_post_append_readback_failed(self):
        fake = PersistentFakeImap()
        fake.fail_first_post_append_select = True
        with self.assertRaisesRegex(RuntimeError, "reselect Drafts folder after append"):
            self._run(fake, lambda: queue_row(), apply=True)

        self.assertEqual(fake.append_calls, 1)
        self.assertEqual(len(fake.messages), 1)

        result = self._run(fake, lambda: queue_row(), apply=True)
        self.assertEqual(result["status"], "green")
        self.assertEqual(result["counts"]["unchanged"], 1)
        self.assertEqual(result["counts"]["final_readback"], 1)
        self.assertEqual(fake.append_calls, 1)
        self.assertEqual(len(fake.messages), 1)
        self.assertEqual(result["smtp_send"], "not_invoked")

    def test_apply_re_reads_queue_instead_of_trusting_stale_preflight(self):
        fake = PersistentFakeImap()
        state = {"subject": "Subject A"}

        dry_run = self._run(fake, lambda: queue_row(state["subject"]), apply=False)
        self.assertEqual(dry_run["status"], "preflight_green")
        self.assertEqual(fake.append_calls, 0)

        state["subject"] = "Subject B"
        result = self._run(fake, lambda: queue_row(state["subject"]), apply=True)
        self.assertEqual(result["status"], "green")
        self.assertEqual(fake.append_calls, 1)
        only_payload = next(iter(fake.messages.values()))
        msg = BytesParser(policy=policy.default).parsebytes(only_payload)
        self.assertEqual(str(msg.get("Subject", "")).strip(), "Subject B")
        self.assertEqual(result["smtp_send"], "not_invoked")


if __name__ == "__main__":
    unittest.main()
