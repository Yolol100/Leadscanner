"""RFC 3501 Recent is session-local; every persistent attribute still matters."""
import unittest

import draft_revision as mod
import test_draft_revision as fixtures


class RecentClient(fixtures.Client):
    def append(self, folder, flags, date, raw):
        before = set(self.server.boxes[folder.strip('"')])
        result = super().append(folder, flags, date, raw)
        for uid in set(self.server.boxes[folder.strip('"')]) - before:
            self.server.boxes[folder.strip('"')][uid]["flags"].add(b"\\RECENT")
        return result


class RecentServer(fixtures.Server):
    def connect(self):
        return RecentClient(self)

    def select(self, client, folder, readonly=True):
        for row in self.boxes[folder].values():
            row["flags"].discard(b"\\RECENT")
        return super().select(client, folder, readonly)


class RecentFlagTests(unittest.TestCase):
    def test_ignore_only_recent_not_uid_hash_or_persistent_flags(self):
        before = {"9": {"sha256": "a" * 64, "flags": {b"\\DRAFT", b"\\RECENT"}}}
        after = {"9": {"sha256": "a" * 64, "flags": {b"\\DRAFT"}}}
        mod.unchanged(before, after)
        mod.unchanged(after, before)
        for changed in ({b"\\DRAFT", b"\\SEEN"}, {b"\\DRAFT", b"\\FLAGGED"},
                        {b"\\DRAFT", b"\\ANSWERED"}, {b"\\DRAFT", b"\\DELETED"},
                        {b"\\DRAFT", b"custom-keyword"}, set()):
            with self.subTest(flags=changed):
                with self.assertRaisesRegex(RuntimeError, "revision_mailbox_changed"):
                    mod.unchanged(after, {"9": {"sha256": "a" * 64, "flags": changed}})
        with self.assertRaisesRegex(RuntimeError, "revision_mailbox_changed"):
            mod.unchanged(after, {"9": {"sha256": "b" * 64, "flags": {b"\\DRAFT"}}})
        with self.assertRaisesRegex(RuntimeError, "revision_mailbox_changed"):
            mod.unchanged(after, {"10": after["9"]})

    def test_reselection_can_drop_recent_during_verified_revision(self):
        harness = fixtures.RevisionTests()
        harness.setUp()
        server = RecentServer(harness.base, harness.records)
        result = harness.execute(server, "REVISION_PILOT")
        self.assertEqual((result["revised"], result["pending"]), (1, 409))
        self.assertEqual(len(server.boxes["Drafts"]), 411)
        self.assertEqual(result["sent"], 0)


if __name__ == "__main__":
    unittest.main()
