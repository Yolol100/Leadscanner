"""Synthetic, offline safety tests: no live Google/IMAP access."""
import unittest
from unittest.mock import patch

import sync450_openings as s
from myhost_draft import build_message


class OpeningSyncSafety(unittest.TestCase):
    def setUp(self):
        self.keys = ["draft-" + x * 32 for x in "abcd"]
        self.old = {k: {"draft_id": k, "company": "Test Business",
                        "email": "info@example.nl", "source_url": "https://example.nl/",
                        "subject": "Existing draft", "body": "Existing copy"}
                    for k in self.keys}
        self.new = {k: {**v, "subject": "Better draft", "body": "New copy"}
                    for k, v in self.old.items()}
        self.expected = {
            k: {"category": category, "old": self.old[k], "new": self.new[k]}
            for k, category in zip(self.keys, ("ready", "held", "closed", "excluded"))
        }

    def record(self, key, version, uid):
        message = build_message(version)
        return {"uid": str(uid), "draft_id": key, "message": message,
                "draft_flag": True, "flags": {b"\\DRAFT"},
                "sha256": str(uid)}

    def complete_inventory(self):
        a, b, c, d = self.keys
        return {"1": self.record(a, self.old[a], 1),
                "2": self.record(a, self.new[a], 2),
                "3": self.record(b, self.old[b], 3),
                "4": self.record(c, self.old[c], 4)}

    def test_exact_old_and_new_are_separate(self):
        with patch.object(s.legacy, "USER", "info@andrewbaeten.nl"):
            result = s.classify(self.complete_inventory(), self.expected)
        a, b, c, d = self.keys
        self.assertEqual(result[a]["new"], ["2"])
        self.assertEqual(result[a]["old"], ["1"])
        s.verify_ready(result, self.expected)

    def test_edited_mail_refused(self):
        a, b, c, d = self.keys
        rows = {"1": self.record(a, {**self.old[a], "body": "Human edited"}, 1)}
        with self.assertRaisesRegex(RuntimeError, "unrecognized"):
            s.classify(rows, self.expected)

    def test_unrelated_message_never_deleted(self):
        a, b, c, d = self.keys
        record = self.record(a, self.old[a], 1)
        record["draft_id"] = "draft-" + "f" * 32
        with self.assertRaisesRegex(RuntimeError, "unrelated"):
            s.classify({"1": record}, self.expected)

    def test_held_must_remain_original(self):
        a, b, c, d = self.keys
        with self.assertRaisesRegex(RuntimeError, "held"):
            s.classify({"2": self.record(b, self.new[b], 2)}, self.expected)

    def test_excluded_cannot_appear(self):
        d = self.keys[3]
        with self.assertRaisesRegex(RuntimeError, "excluded"):
            s.classify({"4": self.record(d, self.old[d], 4)}, self.expected)

    def test_closed_draft_absent_after_sync(self):
        a, b, c, d = self.keys
        groups = {a: {"new": ["2"], "old": []},
                  b: {"new": [], "old": ["3"]},
                  c: {"new": [], "old": ["4"]},
                  d: {"new": [], "old": []}}
        with self.assertRaisesRegex(RuntimeError, "old_or_closed"):
            s.verify_complete(groups, self.expected, 3)
        groups[c]["old"] = []
        s.verify_complete(groups, self.expected, 2)

    def test_draft_flag_and_sender_guard(self):
        items = self.complete_inventory()
        items["3"]["draft_flag"] = False
        with self.assertRaisesRegex(RuntimeError, "draft_flag"):
            s.classify(items, self.expected)

    def test_body_structure_and_one_question(self):
        good = ("Goedendag,\n\nEen mobiele uitleg helpt gasten kiezen."
                "\n\nZal ik een voorbeeld sturen?\n\n" +
                s.OPT + "\n\nGroet,\nAndrew")
        old = ("Goedendag,\n\nRestaurant biedt diner.\n\n"
               "Een mobiele uitleg helpt gasten kiezen."
               "\n\nZal ik een voorbeeld sturen?\n\n" +
               s.OPT + "\n\nGroet,\nAndrew")
        s.check_body(good)
        s.check_body(old, old=True)
        for bad in (good.replace(s.OPT, ""), good.replace("Zal ik", "Ik kan"),
                    good.replace("Groet,\nAndrew", "Groet,\nNaam")):
            with self.assertRaisesRegex(RuntimeError, "review_body_invalid"):
                s.check_body(bad)
        with self.assertRaisesRegex(RuntimeError, "review_body_invalid"):
            s.check_body(old)

    def test_no_automatic_dispatch(self):
        with patch.dict("os.environ", {"OPENING450_TASK": s.TASK,
                                       "OPENING450_MODE": "unknown"}):
            self.assertEqual(s.main(), 1)
        with patch.dict("os.environ", {"OPENING450_TASK": "incorrect",
                                       "OPENING450_MODE": "install"}):
            self.assertEqual(s.main(), 1)

    def test_fixed_scope_count(self):
        self.assertEqual((s.READY_COUNT, s.HOLD_COUNT, s.CLOSED_COUNT,
                          s.EXCLUDED_COUNT), (407, 4, 1, 38))
        self.assertEqual(s.READY_COUNT + s.HOLD_COUNT + s.CLOSED_COUNT, 412)
        self.assertEqual(s.PHASE_SIZE, 100)


if __name__ == "__main__":
    unittest.main()
