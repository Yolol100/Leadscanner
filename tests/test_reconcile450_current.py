"""Synthetic tests: no IMAP or private Google access."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import reconcile450_current as target
from myhost_draft import build_message


class ReconcileCurrentTests(unittest.TestCase):
    def setUp(self):
        self.key = "draft-" + "0" * 31 + "1"
        self.old = {"draft_id": self.key, "company": "Example",
                    "email": "info@example.invalid",
                    "source_url": "https://example.invalid",
                    "subject": "Old subject", "body": "Old content"}
        self.new = {**self.old, "subject": "Better subject",
                    "body": "Better content"}
        self.expected = {self.key: {"old": self.old, "new": self.new,
                                    "eligible": True}}

    def record(self, row, uid):
        return {
            "draft_id": self.key,
            "draft_flag": True,
            "flags": {b"\\DRAFT"},
            "message": build_message(row),
            "uid": str(uid),
            "sha256": str(uid),
        }

    def test_old_and_new_classified_separately(self):
        items = {"1": self.record(self.old, 1), "2": self.record(self.new, 2)}
        result = target.classify(items, self.expected)
        self.assertEqual(result[self.key]["old"], ["1"])
        self.assertEqual(result[self.key]["new"], ["2"])
        target.verify_new_complete(result, self.expected)

    def test_changed_mail_is_not_deleted(self):
        edited = {**self.old, "subject": "Manual edit"}
        with self.assertRaisesRegex(RuntimeError, "unrecognized"):
            target.classify({"1": self.record(edited, 1)}, self.expected)

    def test_unrelated_draft_is_protected(self):
        record = self.record(self.old, 1)
        record["draft_id"] = "draft-" + "f"*32
        with self.assertRaisesRegex(RuntimeError, "unrelated_drafts_present"):
            target.classify({"1": record}, self.expected)

    def test_missing_new_version_fails(self):
        result = target.classify({"1": self.record(self.old, 1)},
                                 self.expected)
        with self.assertRaisesRegex(RuntimeError, "new_draft_not_verified"):
            target.verify_new_complete(result, self.expected)

    def test_blocked_entry_is_never_accepted_as_new(self):
        self.expected[self.key]["eligible"] = False
        with self.assertRaisesRegex(RuntimeError, "excluded_draft_not_rejected"):
            target.verify_new_complete(
                {self.key: {"new": ["2"], "old": ["1"]}}, self.expected)

    def test_scope_count_is_fail_closed(self):
        with patch.object(target.historical, "load_rows", return_value=[]):
            with patch.object(target.historical, "read", return_value=[]):
                with self.assertRaisesRegex(RuntimeError, "private_450_scope_invalid"):
                    target.load_private_scope(object())


if __name__ == "__main__":
    unittest.main()
