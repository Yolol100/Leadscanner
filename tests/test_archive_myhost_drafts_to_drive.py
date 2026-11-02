"""Offline read-only IMAP to private Drive ZIP archive acceptance tests."""
import io
import json
import unittest
from unittest.mock import patch
import zipfile

from archive_myhost_drafts_to_drive import run, snapshot_current_drafts
from test_draft_management import MemoryStore, MemoryClient, ROW


def bootstrap():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps({
            "format": "webactueel-mijnhost-mime-archive-v1",
            "status": "empty-bootstrap", "messages": 0,
        }))
    return buffer.getvalue()


class FakeArchive:
    def __init__(self):
        self.payload = bootstrap()
        self.writes = 0

    def read_bytes(self):
        return self.payload

    def replace_empty_with(self, payload):
        self.payload = payload
        self.writes += 1
        return True


class ArchiveAcceptanceTests(unittest.TestCase):
    def test_archive_exact_original_messages_and_no_mailbox_writes(self):
        store = MemoryStore()
        original = {}
        for identity in ("a", "b"):
            row = dict(ROW, draft_id="draft-" + identity * 32)
            uid = store.add(row)
            original[uid] = store.messages[uid][0]
        destination = FakeArchive()
        with patch("archive_myhost_drafts_to_drive.draft.imap.target_guard"):
            result = run(connector=lambda: MemoryClient(store), archive=destination)
        self.assertEqual(result["state"], "archived_and_readback_verified")
        self.assertEqual(result["messages"], 2)
        with zipfile.ZipFile(io.BytesIO(destination.payload)) as z:
            m = json.loads(z.read("manifest.json"))
            self.assertEqual(m["messages"], 2)
            self.assertEqual(m["status"], "complete")
            for uid, raw in original.items():
                self.assertEqual(z.read("originals/uid-" + uid + ".eml"), raw)
        self.assertEqual(destination.writes, 1)
        self.assertEqual(store.append_count, 0)
        self.assertEqual(store.deleted, [])
        with patch("archive_myhost_drafts_to_drive.draft.imap.target_guard"):
            again = run(connector=lambda: MemoryClient(store), archive=destination)
        self.assertEqual(again["state"], "archive_already_populated")
        self.assertEqual(destination.writes, 1)

    def test_non_draft_flag_blocks_archive(self):
        store = MemoryStore()
        uid = store.add(ROW)
        raw, flags = store.messages[uid]
        store.messages[uid] = (raw, set())
        client = MemoryClient(store)
        with self.assertRaisesRegex(RuntimeError, "non_draft"):
            snapshot_current_drafts(client, "Drafts")
        self.assertEqual(store.deleted, [])
        self.assertEqual(store.append_count, 0)

    def test_empty_mailbox_blocks_without_upload(self):
        store = MemoryStore()
        destination = FakeArchive()
        with patch("archive_myhost_drafts_to_drive.draft.imap.target_guard"):
            with self.assertRaisesRegex(RuntimeError, "empty_inventory"):
                run(connector=lambda: MemoryClient(store), archive=destination)
        self.assertEqual(destination.writes, 0)


if __name__ == "__main__":
    unittest.main()
