"""Offline, fictional evidence of owner/auth/archive/scope safety. No IMAP/Google."""
import hashlib
import unittest
from unittest.mock import MagicMock, Mock, patch

import conversation_replacement as mod
import private_imap_archive as archive
from myhost_draft import build_message

DID = "draft-" + "a" * 32
OTHER = "draft-" + "b" * 32
ROW = {"draft_id": DID, "company": "Fictieve Bakker",
       "email": "info@voorbeeld.nl",
       "source_url": "https://voorbeeld.nl/",
       "subject": "Brood bij de bakker",
       "body": "Hoi,\n\nIk zag dat jullie broden bakken.\n\n"
               "Bakken jullie ook op zondag?\n\n"
               + mod.OPT + "\n\nGroet,\nAndrew"}
NEW = dict(ROW, subject="Zondag bij de bakker")
ALT = dict(ROW, draft_id=OTHER, subject="Andere zaak")


def event(mode="PILOT"):
    return {"action": "created",
            "repository": {"full_name": mod.REPO},
            "issue": {"number": mod.ISSUE},
            "comment": {"body": mod.PREFIX + mode,
                        "user": {"login": mod.OWNER},
                        "author_association": "OWNER"}}


def snapshot(uid, row, sha="sha"):
    return {"uid": uid, "draft_id": row["draft_id"], "message": build_message(row),
            "sha256": sha, "draft_flag": True, "flags": {b"\\DRAFT"}}


class FakeArchiveClient:
    def __init__(self, storage):
        self.storage = storage
        self.closed = False

    def list(self):
        return "OK", [
            b'(\\HasNoChildren \\Drafts) "/" "Drafts"',
            b'(\\HasNoChildren) "/" "Webactueel Original Drafts 20261017"',
        ]

    def create(self, folder):
        raise AssertionError("archive exists: CREATE must not be called")

    def append(self, folder, flags, date, raw):
        assert folder == '"' + archive.ARCHIVE + '"'
        assert flags == r"(\Seen)"
        self.storage["3"] = {
            "uid": "3", "draft_id": DID, "sha256": hashlib.sha256(raw).hexdigest(),
            "draft_flag": False, "flags": {b"\\SEEN"}, "raw": raw,
        }
        return "OK", []

    def logout(self):
        self.closed = True


class ConversationRegressionTests(unittest.TestCase):
    def test_owner_command_requires_exact_issue_actor_and_mode(self):
        mod.authorize(event("PRECHECK"), "PRECHECK")
        mod.authorize(event("PILOT"), "PILOT")
        for malformed in ("BATCH_0", "BATCH_6", "SEND", "DELETE_ALL"):
            with self.assertRaisesRegex(RuntimeError, "unauthorized"):
                mod.authorize(event(malformed), malformed)
        for top, child, value in [
            ("issue", "number", 1720), ("repository", "full_name", "untrusted"),
            ("comment", "body", "LEADS_CONVERSATIONS_V1:BATCH_5"),
            ("comment", "author_association", "CONTRIBUTOR"),
        ]:
            case = event()
            case[top][child] = value
            with self.assertRaisesRegex(RuntimeError, "authorization"):
                mod.authorize(case, "PILOT")
        case = event()
        case["comment"]["user"]["login"] = "outsider"
        with self.assertRaises(RuntimeError):
            mod.authorize(case, "PILOT")

    def test_body_has_one_company_question_and_exact_optout(self):
        mod.review_body(ROW["body"])
        for value in [
            ROW["body"].replace(mod.OPT, ""),
            ROW["body"].replace("Hoi,", "Goedendag,"),
            ROW["body"].replace("Bakken jullie ook op zondag?", "Er is geen vraag."),
            ROW["body"].replace("Bakken jullie ook op zondag?", "Twee vragen? Echt?"),
            ROW["body"].replace("Groet,\nAndrew", "Groet,\nOnbekend"),
            ROW["body"].replace("Bakken jullie ook op zondag?", "Bakken jullie ook op zondag?\n\nWas gewoon benieuwd."),
        ]:
            with self.assertRaisesRegex(RuntimeError, "body_invalid"):
                mod.review_body(value)

    def test_new_and_old_original_mailbox_are_typed_and_preserved(self):
        records = {
            DID: {"category": "target", "current": ROW, "new": NEW},
            OTHER: {"category": "held", "current": ALT, "new": ALT},
        }
        current = {"1": snapshot("1", ROW), "2": snapshot("2", ALT)}
        with patch.object(mod.imap, "USER", "info@andrewbaeten.nl"), \
             patch.object(mod, "EXPECTED_COUNTS", {"target": 1, "held": 1}):
            # Scope requires actual 411 independent draft count; don't weaken
            # it simply because this offline fake has two messages.
            with self.assertRaisesRegex(RuntimeError, "mailbox_count_changed"):
                mod._classify(records, current)
            current["3"] = snapshot("3", ROW)
            with self.assertRaisesRegex(RuntimeError, "duplicate_draft_id"):
                mod._classify(records, current)
            del current["3"]
            current["2"] = snapshot("2", NEW)
            with self.assertRaises(RuntimeError):
                mod._classify(records, current)
            current["2"] = snapshot("2", ALT)
            current["1"]["draft_flag"] = False
            with self.assertRaisesRegex(RuntimeError, "flags_changed"):
                mod._classify(records, current)

    def test_pilot_delegates_only_one_verified_exact_old_uid(self):
        mapped = {
            DID: {"category": "target", "number": 1, "current": ROW, "new": NEW},
            OTHER: {"category": "held", "number": 2, "current": ALT, "new": ALT},
        }
        states = [
            ("Drafts", "7", {DID: ("10", "old", "f" * 64),
                             OTHER: ("11", "old", "c" * 64)}),
            ("Drafts", "7", {DID: ("12", "new", "e" * 64),
                             OTHER: ("11", "old", "c" * 64)}),
        ]
        fakeconn = Mock()
        fakeconn.logout = Mock()
        archive_instance = MagicMock()
        outcome = {"status": "verified", "drafts": 411}
        with patch.object(mod, "authorized_writer", return_value=object()), \
             patch.object(mod, "_verified_scope", return_value=mapped), \
             patch.object(mod, "_check_mailbox", side_effect=states) as mail, \
             patch.object(mod.imap, "target_guard"), \
             patch.object(mod.imap, "uidplus", return_value=True), \
             patch.object(mod, "PrivateIMAPArchive", return_value=archive_instance), \
             patch.object(mod, "_verify_archived_originals", return_value=1), \
             patch.object(mod.drafts, "execute", return_value=outcome) as execute:
            result = mod.run("PILOT", event(), connector=lambda: fakeconn)
        self.assertEqual(result["installed"], 1)
        self.assertEqual(execute.call_count, 1)
        opts = execute.call_args
        self.assertEqual(opts.args[1:3], ("UPDATE_DRAFT", DID))
        self.assertEqual(opts.kwargs["expected"]["uid"], "10")
        self.assertEqual(opts.kwargs["expected"]["sha256"], "f" * 64)
        self.assertEqual(opts.kwargs["row"]["subject"], NEW["subject"])
        self.assertFalse(result["sent"])
        self.assertEqual(mail.call_count, 2)
        fakeconn.logout.assert_called_once()

    def test_remaining_batches_are_sequential_and_end_in_separate_audit(self):
        event = {"action": "created", "repository": {"full_name": mod.REPO},
                 "issue": {"number": mod.ISSUE},
                 "comment": {"body": mod.PREFIX + "BATCH_2_TO_5",
                             "user": {"login": mod.OWNER},
                             "author_association": "OWNER"}}
        pre = {"total": 411, "eligible": 391, "already_new": 87,
               "archived": 87, "sent": 0}
        mid = {"total": 411, "eligible": 391, "already_new": 188,
               "archived": 188, "sent": 0}
        final = {"total": 411, "eligible": 391, "already_new": 391,
                 "archived": 391, "blocked": 20, "sent": 0}
        with patch.object(mod, "run", side_effect=[pre, mid, mid, mid, mid, final]) as run:
            result = mod.run_remaining(event)
        self.assertEqual(result["archived"], 391)
        self.assertEqual(result["batches"], 4)
        self.assertEqual(result["sent"], 0)
        self.assertEqual([c.args[0] for c in run.call_args_list],
                         ["AUDIT", "BATCH_2", "BATCH_3", "BATCH_4", "BATCH_5", "AUDIT"])
        for call in run.call_args_list:
            self.assertEqual(call.args[1]["comment"]["body"], mod.PREFIX + call.args[0])

    def test_remaining_batches_refuse_incomplete_first_batch_and_stop_on_error(self):
        event = {"action": "created", "repository": {"full_name": mod.REPO},
                 "issue": {"number": mod.ISSUE},
                 "comment": {"body": mod.PREFIX + "BATCH_2_TO_5",
                             "user": {"login": mod.OWNER},
                             "author_association": "OWNER"}}
        incomplete = {"total": 411, "already_new": 86, "sent": 0}
        with patch.object(mod, "run", return_value=incomplete) as run:
            with self.assertRaisesRegex(RuntimeError, "first_batch_not_complete"):
                mod.run_remaining(event)
            self.assertEqual(run.call_count, 1)
        pre = {"total": 411, "already_new": 87, "sent": 0}
        with patch.object(mod, "run", side_effect=[pre, pre, RuntimeError("synthetic")]) as run:
            with self.assertRaisesRegex(RuntimeError, "synthetic"):
                mod.run_remaining(event)
            self.assertEqual([c.args[0] for c in run.call_args_list],
                             ["AUDIT", "BATCH_2", "BATCH_3"])

    def test_archive_exact_mime_preserved_and_separate_session(self):
        raw = build_message(ROW).as_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        store = {}
        clients = []
        def connect():
            client = FakeArchiveClient(store)
            clients.append(client)
            return client
        def scanned(client):
            return {k: {n: v for n, v in entry.items() if n != "raw"}
                    for k, entry in client.storage.items()}
        def raw_snapshot(client, uid, expected):
            assert client.storage[uid]["sha256"] == expected
            return client.storage[uid]["raw"]
        snapshots = archive.PrivateIMAPArchive(connector=connect)
        with patch.object(archive.transport, "select", return_value="5"), \
             patch.object(archive.transport, "scan", side_effect=scanned), \
             patch.object(archive.drafts, "_raw_snapshot", side_effect=raw_snapshot), \
             patch.object(archive, "find_drafts_folder", return_value="Drafts"):
            key = snapshots.save(DID, "7", "1", raw)
            self.assertEqual(key, (DID, sha))
            self.assertEqual(snapshots.read(key), raw)
            self.assertEqual(snapshots.save(DID, "7", "1", raw), key)
            with self.assertRaisesRegex(RuntimeError, "original_conflict"):
                snapshots.save(DID, "7", "1", raw + b"bad")
        self.assertGreaterEqual(len(clients), 3)
        self.assertTrue(all(client.closed for client in clients))


if __name__ == "__main__":
    unittest.main()
