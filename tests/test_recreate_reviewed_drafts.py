"""Offline guard tests: no SMTP, no delete, retryable create-only drafts."""
import copy
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import draft_revision as revision
import recreate_reviewed_drafts as recreate
from myhost_draft import build_message
from test_draft_revision import Server, event, entry, fixtures


class RecreateTests(unittest.TestCase):
    def setUp(self):
        self.base, self.records, self.rows = fixtures()
        self.eligible = {k: v for k, v in self.records.items()
                         if v["category"] == "target"}
        self.server = Server(self.base, self.records)
        self.server.boxes["Drafts"] = {}

    def context(self, *, source=None, save=None):
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(recreate, "load_reviewed",
                                        side_effect=source or (lambda *_: (self.eligible, set()))))
        stack.enter_context(patch.object(recreate.legacy, "authorized_writer",
                                        return_value=object()))
        stack.enter_context(patch.object(recreate.legacy.imap, "target_guard"))
        stack.enter_context(patch.object(recreate.legacy, "find_drafts_folder",
                                        return_value="Drafts"))
        stack.enter_context(patch.object(recreate.legacy.imap, "select",
                                        side_effect=self.server.select))
        stack.enter_context(patch.object(recreate.legacy.transport, "scan",
                                        side_effect=self.server.scan))

        def append(client, folder, row):
            status, _ = client.append('"' + folder + '"', r"(\\Draft)", None,
                                      build_message(row).as_bytes())
            if status != "OK":
                raise RuntimeError("imap_append_failed")
            return "created"

        stack.enter_context(patch.object(recreate, "save_draft",
                                        side_effect=save or append))
        return stack

    def test_private_source_identity_optout_and_manual_hold(self):
        now = datetime.now(timezone.utc).isoformat()
        proof = [list(recreate.legacy.websites.COLUMNS)]
        for number in range(1, 451):
            key = "draft-" + format(number, "032x")
            base = self.base[key]
            record = [""] * 14
            record[0] = "Review450:" + key
            record[6] = base["new"]["email"]
            record[11] = now
            record[12] = "needs_manual_check" if number == 4 else "verified_with_detail"
            proof.append(record)
        modified = copy.deepcopy(self.base)
        held_key = "draft-" + format(4, "032x")
        modified[held_key]["category"] = "source_hold"

        def reader(_, __, address):
            return self.rows if address.endswith("A1:M451") else proof

        with patch.object(recreate.legacy, "_private_rows", return_value=modified), \
             patch.object(recreate.legacy.history.source, "read", side_effect=reader):
            result, held = recreate.load_reviewed(object(), revision)
            self.assertEqual(len(result), 409)
            self.assertEqual(held, {held_key})
            self.assertNotIn(held_key, result)
            self.assertEqual(result[next(iter(result))]["new"]["body"],
                             self.records[next(iter(result))]["new"]["body"])

        broken = copy.deepcopy(self.rows)
        broken[1][1] = "draft-" + "f" * 32
        with patch.object(recreate.legacy, "_private_rows", return_value=modified), \
             patch.object(recreate.legacy.history.source, "read",
                               side_effect=lambda _, __, a: broken if a.endswith("A1:M451") else proof):
            with self.assertRaisesRegex(RuntimeError, "revision_source_identity"):
                recreate.load_reviewed(object(), revision)

    def test_precheck_is_read_only(self):
        with self.context():
            result = recreate.run("RECREATE_PRECHECK", revision=revision,
                                  connector=self.server.connect)
        self.assertEqual((result["eligible"], result["pending"], result["created"]),
                         (410, 410, 0))
        self.assertEqual(self.server.log, [])

    def test_pilot_and_rerun_keep_only_one_verified_draft(self):
        with self.context():
            first = recreate.run("RECREATE_PILOT", revision=revision,
                                 connector=self.server.connect)
            again = recreate.run("RECREATE_PILOT", revision=revision,
                                 connector=self.server.connect)
        self.assertEqual((first["created"], first["pending"]), (1, 409))
        self.assertEqual(again["created"], 0)
        self.assertEqual(len(self.server.boxes["Drafts"]), 1)
        item = next(iter(self.server.boxes["Drafts"].values()))
        self.assertTrue(item["draft_flag"])
        self.assertEqual(item["draft_id"], "draft-" + format(1, "032x"))

    def test_batch_failure_preserves_verified_prefix_and_safe_retry(self):
        calls = [0]

        def interrupted(client, folder, row):
            calls[0] += 1
            if calls[0] == 3:
                raise RuntimeError("imap_append_failed")
            status, _ = client.append('"' + folder + '"', r"(\\Draft)", None,
                                      build_message(row).as_bytes())
            self.assertEqual(status, "OK")
            return "created"

        with self.context(save=interrupted):
            with self.assertRaisesRegex(RuntimeError, "imap_append_failed"):
                recreate.run("RECREATE_BATCH_1", revision=revision,
                             connector=self.server.connect)
        self.assertEqual(len(self.server.boxes["Drafts"]), 2)
        with self.context():
            outcome = recreate.run("RECREATE_BATCH_1", revision=revision,
                                   connector=self.server.connect)
        self.assertEqual((outcome["created"], outcome["existing"]), (98, 100))
        self.assertEqual(len(self.server.boxes["Drafts"]), 100)
        self.assertEqual(len({item["draft_id"] for item in self.server.boxes["Drafts"].values()}), 100)
        self.assertNotIn("STORE", [event[0] for event in self.server.log])
        self.assertNotIn("EXPUNGE", [event[0] for event in self.server.log])

    def test_wrong_recipient_duplicate_or_unknown_draft_blocks(self):
        key = next(iter(self.eligible))
        row = self.eligible[key]["new"]
        raw = build_message(dict(row, email="different@example.com")).as_bytes()
        for uid in ("1", "2"):
            with self.subTest(uid=uid):
                self.server.boxes["Drafts"] = {uid: entry(uid, raw, {b"\\DRAFT"})}
                with self.context():
                    with self.assertRaisesRegex(RuntimeError, "revision_mailbox_changed"):
                        recreate.run("RECREATE_PRECHECK", revision=revision,
                                     connector=self.server.connect)
                self.assertEqual(len(self.server.boxes["Drafts"]), 1)

    def test_source_change_fails_before_append(self):
        second = copy.deepcopy(self.eligible)
        key = next(iter(second))
        second[key]["new"]["body"] += " gewijzigd"
        calls = [0]

        def source(*_):
            calls[0] += 1
            return (self.eligible if calls[0] == 1 else second), set()

        with self.context(source=source):
            with self.assertRaisesRegex(RuntimeError, "revision_source_changed"):
                recreate.run("RECREATE_BATCH_1", revision=revision,
                             connector=self.server.connect)
        self.assertEqual(len(self.server.boxes["Drafts"]), 0)


if __name__ == "__main__":
    unittest.main()
