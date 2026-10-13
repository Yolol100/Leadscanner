"""Read-only and synthetic IMAP regression tests for recoverable Draft isolation."""
from __future__ import annotations

import unittest
from unittest.mock import patch
from email.parser import BytesParser
from email.policy import default

from _once_myhost_safe_hold import (
    HOLD_FOLDER, _one_uid, ensure_hold_folder, move_to_hold,
    validate_hold_inventory,
)
from _once_myhost_existing_rewrite import inventory_existing
from myhost_draft import build_message


class HoldIMAP:
    capabilities = (b"IMAP4REV1", b"UIDPLUS")

    def __init__(self):
        self.folders = {"Drafts": {}, HOLD_FOLDER: {}}
        self.next_uid = 1
        self.selected = None
        self.mutate_copy = False
        self.fail_copy = False
        self.no_uidplus = False
        self.calls = []

    def add(self, folder, raw):
        uid = str(self.next_uid).encode()
        self.next_uid += 1
        self.folders[folder][uid] = [raw, set([r"\Draft"])]
        return uid

    def select(self, folder, readonly=True):
        folder = folder.strip('"')
        if folder not in self.folders:
            return "NO", []
        self.selected = folder
        return "OK", [str(len(self.folders[folder])).encode()]

    def create(self, folder):
        self.folders[folder.strip('"')] = {}
        return "OK", []

    def capability(self):
        return "OK", [b"IMAP4REV1" + (b" UIDPLUS" if not self.no_uidplus else b"")]

    def search(self, charset, *args):
        found = []
        for i, (uid, (raw, _)) in enumerate(self.folders[self.selected].items(), 1):
            msg = BytesParser(policy=default).parsebytes(raw)
            if args[0] == "ALL" or (args[0] == "HEADER" and
               str(msg.get(args[1], "")).startswith(args[2].strip('"'))):
                found.append(str(i).encode())
        return "OK", [b" ".join(found)]

    def fetch(self, sequences, expr):
        ids = [int(x) for x in sequences.decode().split(",")] if isinstance(sequences, bytes) else [int(x) for x in str(sequences).split(",")]
        out = []
        for i in ids:
            uid, row = list(self.folders[self.selected].items())[i - 1]
            if expr == "(UID)":
                out.append((b"1 (UID " + uid + b")", b""))
            elif "HEADER.FIELDS" in expr:
                out.append((b"1 (HEADER)", row[0]))
            else:
                out.append((b"1 (RFC822)", row[0]))
        return "OK", out

    def uid(self, operation, value, *args):
        uid = str(value).encode()
        self.calls.append(operation.lower())
        items = self.folders[self.selected]
        if operation.lower() == "fetch":
            if uid not in items:
                return "OK", []
            if args[0] == "(FLAGS)":
                return "OK", [(b"1 (UID " + uid + b" FLAGS (\\Draft))", b"")]
            return "OK", [(b"1 (BODY[])", items[uid][0])]
        if operation.lower() == "copy":
            if self.fail_copy:
                return "NO", []
            if uid not in items:
                return "NO", []
            folder = args[0].strip('"')
            raw = items[uid][0]
            if self.mutate_copy:
                raw += b"\ncorruption"
            self.add(folder, raw)
            return "OK", []
        if operation.lower() == "store":
            items[uid][1].add(r"\Deleted")
            return "OK", []
        if operation.lower() == "expunge":
            if uid in items and r"\Deleted" in items[uid][1]:
                del items[uid]
            return "OK", []
        raise AssertionError(operation)

    def expunge(self):
        raise AssertionError("never globally expunge")


class HoldTests(unittest.TestCase):
    def setUp(self):
        self.client = HoldIMAP()
        self.lead = "growth-0123456789abcdefabcd"
        self.to = "hello@example.org"
        self.sender = "info@andrewbaeten.nl"
        _, self.message = build_message({
            "lead_id": self.lead, "email": self.to, "company": "Example",
            "website": "https://example.org", "subject": "Question",
            "body": "Hi there", "status": "review_draft",
            "contact_basis_status": "review_required",
        })
        self.client.add("Drafts", self.message.as_bytes(policy=default))

    def act(self):
        return move_to_hold(self.client, "Drafts", HOLD_FOLDER, self.lead,
                            self.to, self.sender, self.message)

    def test_byte_verified_copy_precedes_target_uid_only_delete(self):
        self.assertTrue(self.act())
        self.assertEqual(len(self.client.folders["Drafts"]), 0)
        self.assertEqual(len(self.client.folders[HOLD_FOLDER]), 1)
        self.assertIn("copy", self.client.calls)
        self.assertEqual(self.client.calls.count("expunge"), 1)
        active, held = validate_hold_inventory(
            self.client, "Drafts", HOLD_FOLDER, inventory_existing, 1)
        self.assertEqual((len(active), len(held)), (0, 1))

    def test_corrupt_copy_blocks_original_deletion(self):
        self.client.mutate_copy = True
        with self.assertRaisesRegex(RuntimeError, "readback_failed"):
            self.act()
        self.assertEqual(len(self.client.folders["Drafts"]), 1)
        self.assertNotIn("expunge", self.client.calls)

    def test_copy_failure_blocks_original_deletion(self):
        self.client.fail_copy = True
        with self.assertRaisesRegex(RuntimeError, "uid_copy_failed"):
            self.act()
        self.assertEqual(len(self.client.folders["Drafts"]), 1)
        self.assertNotIn("expunge", self.client.calls)

    def test_missing_uidplus_blocks_any_write(self):
        self.client.no_uidplus = True
        self.client.capabilities = (b"IMAP4REV1",)
        with self.assertRaisesRegex(RuntimeError, "UIDPLUS"):
            self.act()
        self.assertEqual(len(self.client.folders[HOLD_FOLDER]), 0)
        self.assertNotIn("copy", self.client.calls)

    def test_unexpected_extra_hold_message_blocks_inventory(self):
        self.client.add(HOLD_FOLDER, b"From: unknown@example.org\r\n\r\nx")
        with self.assertRaisesRegex(RuntimeError, "hold_folder_unrelated_content|imap_noncanonical_tagged_draft"):
            validate_hold_inventory(self.client, "Drafts", HOLD_FOLDER,
                                    inventory_existing, 1)

    def test_sender_mismatch_never_archived(self):
        self.assertFalse(move_to_hold(self.client, "Drafts", HOLD_FOLDER,
                                      self.lead, self.to, "other@example.org",
                                      self.message))
        self.assertEqual(len(self.client.folders["Drafts"]), 1)
        self.assertNotIn("copy", self.client.calls)

    def test_baseline_union_must_be_complete(self):
        with self.assertRaisesRegex(RuntimeError, "hold_union_baseline_changed"):
            validate_hold_inventory(self.client, "Drafts", HOLD_FOLDER,
                                    inventory_existing, 1173)

    def test_repeat_after_success_no_target_copy(self):
        self.assertTrue(self.act())
        self.assertFalse(self.act())
        self.assertEqual(len(self.client.folders[HOLD_FOLDER]), 1)


    def test_hold_only_recheck_is_guarded_by_live_inventory_and_disables_rewrite(self):
        from pathlib import Path
        workflow = (Path(__file__).resolve().parents[1] /
                    ".github/workflows/once-myhost-safe-hold-and-rewrite.yml").read_text()
        self.assertIn("[myhost-cleanup-656]", workflow)
        self.assertIn("[myhost-529-hold-only]", workflow)
        self.assertIn("len(active) != 529 or len(held) != 644", workflow)
        self.assertIn("validate_hold_inventory(", workflow)
        self.assertIn("require_uidplus(client, 'reversible recovery hold')", workflow)
        self.assertIn('if: "!contains(github.event.head_commit.message', workflow)
        self.assertIn("MYHOST_529_PREFLIGHT=red details_suppressed", workflow)

if __name__ == "__main__":
    unittest.main()
