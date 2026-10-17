"""No-network tests for owner-scoped Mijn.Host draft create/update/delete.

All identities and message contents are fictional. No provider credentials.
"""
import hashlib
import unittest
from unittest.mock import patch

import draft_management as mgr
from myhost_draft import build_message

DID = "draft-" + "a" * 32
OTHER = "draft-" + "b" * 32
ROW = {
    "draft_id": DID,
    "company": "Fictieve Groentewinkel",
    "email": "info@fictieve-groentewinkel.nl",
    "source_url": "https://fictieve-groentewinkel.nl/contact/",
    "subject": "Groente van de dag",
    "body": "Hoi,\n\nJullie verkopen groenten van de dag.\n\n"
            "Wisselt het assortiment elke week?\n\n"
            "Was gewoon benieuwd.\n\n"
            "Liever geen e-mails meer? Antwoord met 'nee', dan laat ik het hierbij.\n\n"
            "Groet,\nAndrew",
}


def permission(op, draft_id=DID):
    return {
        "action": "created",
        "repository": {"full_name": "Yolol100/Leadscanner"},
        "issue": {"number": 1659},
        "comment": {
            "user": {"login": "Yolol100"},
            "author_association": "OWNER",
            "body": "LEADS_MANAGE_V1:" + op + ":" + draft_id,
        },
    }


class MemoryStore:
    def __init__(self):
        self.messages = {}
        self.next_uid = 0
        self.uidvalidity = "7"
        self.uidplus = True
        self.append_count = 0
        self.deleted = []
        self.connections = 0
        self.fail_append = False

    def add(self, row):
        self.next_uid += 1
        uid = str(self.next_uid)
        raw = build_message(row).as_bytes()
        self.messages[uid] = (raw, {b"\\DRAFT"})
        return uid

    def expected(self, uid):
        raw, _ = self.messages[uid]
        return {
            "folder": "Drafts",
            "uidvalidity": self.uidvalidity,
            "uid": uid,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }


class MemoryClient:
    def __init__(self, store):
        self.store = store
        store.connections += 1

    def list(self):
        return "OK", [b'(\\HasNoChildren \\Drafts) "/" "Drafts"']

    def select(self, folder, readonly=True):
        if folder != '"Drafts"':
            raise AssertionError("Unexpected folder")
        return "OK", [str(len(self.store.messages)).encode("ascii")]

    def response(self, key):
        return key, [self.store.uidvalidity.encode("ascii")]

    def capability(self):
        value = b"IMAP4rev1 UIDPLUS" if self.store.uidplus else b"IMAP4rev1"
        return "OK", [value]

    def uid(self, command, *args):
        command = command.upper()
        if command == "SEARCH":
            keys = sorted(self.store.messages, key=int)
            return "OK", [" ".join(keys).encode("ascii")]
        if command == "FETCH":
            uids = str(args[0]).split(",")
            records = []
            for uid in uids:
                if uid not in self.store.messages:
                    return "NO", []
                raw, flags = self.store.messages[uid]
                meta = (b"1 (UID " + uid.encode("ascii") + b" FLAGS ("
                        + b" ".join(sorted(flags)) + b") RFC822.SIZE "
                        + str(len(raw)).encode("ascii") + b")")
                if "BODY.PEEK" in str(args[1]):
                    records.extend([(meta, raw), b")"])
                else:
                    records.append(meta)
            return "OK", records
        if command == "STORE":
            for uid in str(args[0]).split(","):
                raw, flags = self.store.messages[uid]
                self.store.messages[uid] = (raw, flags | {b"\\DELETED"})
            return "OK", []
        if command == "EXPUNGE":
            for uid in str(args[0]).split(","):
                raw, flags = self.store.messages[uid]
                if b"\\DELETED" in flags:
                    del self.store.messages[uid]
                    self.store.deleted.append(uid)
            return "OK", []
        raise AssertionError("Unknown IMAP command: " + command)

    def append(self, folder, flags, date_time, raw):
        if self.store.fail_append:
            return "NO", []
        self.store.next_uid += 1
        uid = str(self.store.next_uid)
        self.store.messages[uid] = (raw, {b"\\DRAFT"})
        self.store.append_count += 1
        return "OK", [b"APPENDUID 7 " + uid.encode("ascii")]

    def logout(self):
        return "BYE", []


class PrivateSnapshots:
    def __init__(self):
        self.saved = {}
        self.reads = 0

    def save(self, draft_id, validity, uid, raw):
        key = (draft_id, validity, uid)
        self.saved[key] = raw
        return key

    def read(self, key):
        self.reads += 1
        return self.saved[key]


class DraftManagementTests(unittest.TestCase):
    def setUp(self):
        self.storage = MemoryStore()
        self.snapshots = PrivateSnapshots()
        self.connector = lambda: MemoryClient(self.storage)

    def perform(self, operation, *, draft_id=DID, row=None, expected=None,
                source=lambda: True, snapshots=None):
        # Synthetic .nl domains need no DNS: URL resolver is separately tested.
        with patch("draft_queue_readonly.is_public_http_url", return_value=True):
            return mgr.execute(
                permission(operation, draft_id), operation, draft_id,
                row=row, expected=expected, check_source=source,
                snapshots=snapshots if snapshots is not None else self.snapshots,
                connector=self.connector)

    def test_create_requires_exact_owner_permission(self):
        event = permission("CREATE_DRAFT")
        event["comment"]["user"]["login"] = "someone-else"
        with self.assertRaisesRegex(RuntimeError, "authorization"):
            mgr.execute(event, "CREATE_DRAFT", DID, row=ROW,
                        check_source=lambda: True, connector=self.connector)
        self.assertEqual(self.storage.connections, 0)

    def test_create_with_independent_readback_and_idempotent_retry(self):
        result = self.perform("CREATE_DRAFT", row=ROW)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["drafts"], 1)
        self.assertEqual(self.storage.connections, 2)
        result = self.perform("CREATE_DRAFT", row=ROW)
        self.assertEqual(result["drafts"], 1)
        self.assertEqual(self.storage.append_count, 1)
        self.assertEqual(len(self.storage.messages), 1)
        self.assertEqual(self.storage.deleted, [])

    def test_update_stages_exact_new_copy_and_preserves_other_draft(self):
        uid = self.storage.add(ROW)
        other = dict(ROW, draft_id=OTHER, subject="Andere zaak")
        other_uid = self.storage.add(other)
        untouched = self.storage.messages[other_uid]
        expected = self.storage.expected(uid)
        improved = dict(ROW, subject="Versgroente bij fictieve winkel")
        output = self.perform("UPDATE_DRAFT", row=improved, expected=expected)
        self.assertEqual(output["status"], "verified")
        self.assertEqual(output["drafts"], 2)
        self.assertEqual(self.storage.deleted, [uid])
        self.assertEqual(self.storage.messages[other_uid], untouched)
        self.assertEqual(self.storage.append_count, 1)
        self.assertEqual(self.snapshots.saved[(DID, "7", uid)][0:5],
                         build_message(ROW).as_bytes()[0:5])

        # A retry of a successful update must not append a second copy.
        again = self.perform("UPDATE_DRAFT", row=improved, expected=expected)
        self.assertEqual(again["drafts"], 2)
        self.assertEqual(self.storage.append_count, 1)

    def test_delete_exact_uid_and_leave_everything_else_untouched(self):
        uid = self.storage.add(ROW)
        other = dict(ROW, draft_id=OTHER, subject="Fictief ander onderwerp")
        other_uid = self.storage.add(other)
        unrelated = self.storage.messages[other_uid]
        target = self.storage.expected(uid)
        result = self.perform("DELETE_DRAFT", expected=target)
        self.assertEqual(result["drafts"], 1)
        self.assertEqual(self.storage.deleted, [uid])
        self.assertEqual(self.storage.messages[other_uid], unrelated)
        self.assertGreater(self.snapshots.reads, 0)

        repeat = self.perform("DELETE_DRAFT", expected=target)
        self.assertEqual(repeat["status"], "already_absent_unverified")
        self.assertEqual(self.storage.deleted, [uid])

    def test_reject_duplicate_draft_id_and_changed_original(self):
        self.storage.add(ROW)
        self.storage.add(ROW)
        with self.assertRaisesRegex(RuntimeError, "duplicate_draft_id"):
            self.perform("CREATE_DRAFT", row=ROW)
        self.assertEqual(self.storage.append_count, 0)

        self.storage = MemoryStore()
        uid = self.storage.add(ROW)
        target = self.storage.expected(uid)
        raw, flags = self.storage.messages[uid]
        self.storage.messages[uid] = (raw + b"\nchanged", flags)
        with self.assertRaisesRegex(RuntimeError, "original_draft_changed"):
            self.perform("DELETE_DRAFT", expected=target)
        self.assertEqual(self.storage.deleted, [])

    def test_reject_missing_snapshot_before_destructive_action(self):
        uid = self.storage.add(ROW)
        original = self.storage.messages[uid]
        with self.assertRaisesRegex(RuntimeError, "snapshot_storage_required"):
            self.perform("DELETE_DRAFT", expected=self.storage.expected(uid),
                         snapshots=object())
        self.assertEqual(self.storage.messages[uid], original)
        self.assertEqual(self.storage.deleted, [])

    def test_reject_incomplete_source_and_uidvalidity_change(self):
        with self.assertRaisesRegex(RuntimeError, "source_or_exclusion_unverified"):
            self.perform("CREATE_DRAFT", row=ROW, source=lambda: False)
        self.assertEqual(self.storage.connections, 0)
        uid = self.storage.add(ROW)
        target = self.storage.expected(uid)
        self.storage.uidvalidity = "8"
        with self.assertRaisesRegex(RuntimeError, "uidvalidity_changed"):
            self.perform("DELETE_DRAFT", expected=target)
        self.assertEqual(self.storage.deleted, [])

    def test_without_uidplus_never_remove_original(self):
        uid = self.storage.add(ROW)
        self.storage.uidplus = False
        with self.assertRaisesRegex(RuntimeError, "uid_expunge"):
            self.perform("DELETE_DRAFT", expected=self.storage.expected(uid))
        self.assertEqual(len(self.storage.messages), 1)

    def test_append_failure_does_not_delete_original(self):
        uid = self.storage.add(ROW)
        target = self.storage.expected(uid)
        self.storage.fail_append = True
        changed = dict(ROW, subject="Nieuw onderwerp")
        with self.assertRaisesRegex(RuntimeError, "draft_append_failed"):
            self.perform("UPDATE_DRAFT", row=changed, expected=target)
        self.assertIn(uid, self.storage.messages)
        self.assertEqual(self.storage.deleted, [])
        self.assertEqual(self.storage.append_count, 0)

    def test_destination_email_change_forbidden(self):
        uid = self.storage.add(ROW)
        changed = dict(ROW, email="info@andere-fictieve-winkel.nl")
        with self.assertRaisesRegex(RuntimeError, "recipient_identity_changed"):
            self.perform("UPDATE_DRAFT", row=changed, expected=self.storage.expected(uid))
        self.assertEqual(self.storage.append_count, 0)
        self.assertIn(uid, self.storage.messages)

    def test_update_uses_targeted_staging_read_and_full_predelete_scan(self):
        uid = self.storage.add(ROW)
        updated = dict(ROW, subject="Fictieve verse voorraad")
        original_scan = mgr.transport.scan
        with patch.object(mgr.transport, "scan", wraps=original_scan) as scan:
            result = self.perform(
                "UPDATE_DRAFT", row=updated, expected=self.storage.expected(uid))
        self.assertEqual(result["status"], "verified")
        # Initial full scan, pre-deletion full scan, independent final scan.
        # APPEND-stage validity/UID delta and exact MIME use targeted reads.
        self.assertEqual(scan.call_count, 3)
        self.assertEqual(self.storage.deleted, [uid])
        self.assertEqual(self.storage.append_count, 1)

    def test_unrelated_message_tamper_is_still_blocked_before_old_delete(self):
        uid = self.storage.add(ROW)
        other = dict(ROW, draft_id=OTHER, subject="Onverwante zaak")
        other_uid = self.storage.add(other)
        expected = self.storage.expected(uid)
        changed = dict(ROW, subject="Ander onderwerp")
        original_scan = mgr.transport.scan
        count = [0]

        def scan_with_external_change(client):
            count[0] += 1
            if count[0] == 2:
                raw, flags = self.storage.messages[other_uid]
                self.storage.messages[other_uid] = (raw + b"\nexternal edit", flags)
            return original_scan(client)

        with patch.object(mgr.transport, "scan", side_effect=scan_with_external_change):
            with self.assertRaisesRegex(RuntimeError, "unrelated_draft_changed"):
                self.perform("UPDATE_DRAFT", row=changed, expected=expected)
        self.assertIn(uid, self.storage.messages)
        self.assertNotIn(uid, self.storage.deleted)
        self.assertEqual(self.storage.deleted.__len__(), 1)
        self.assertEqual(self.storage.append_count, 1)

    def test_scoped_inventory_does_not_repeat_bulk_scan_uid_search(self):
        # The bulk scanner itself checks UID membership twice.
        fake_inventory = {"17": object()}
        with patch.object(mgr.imap, "select", return_value="7"), \
             patch.object(mgr.transport, "scan", return_value=fake_inventory) as scanner, \
             patch.object(mgr.imap, "uidset") as redundant:
            validity, inventory = mgr._scope(object(), "Drafts")
        self.assertEqual(validity, "7")
        self.assertIs(inventory, fake_inventory)
        scanner.assert_called_once()
        redundant.assert_not_called()



if __name__ == "__main__":
    unittest.main()
