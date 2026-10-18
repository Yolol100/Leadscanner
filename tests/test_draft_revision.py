"""Fictional offline tests of second-pass MIME replacement and recovery."""
import copy
import hashlib
import unittest
from email import policy
from email.parser import BytesParser
from unittest.mock import patch

import draft_revision as mod
from myhost_draft import build_message


def event(mode="REVISION_ALL"):
    return {"action": "created", "repository": {"full_name": mod.legacy.REPO},
            "issue": {"number": mod.legacy.ISSUE},
            "comment": {"body": mod.legacy.PREFIX + mode,
                        "user": {"login": mod.legacy.OWNER}, "author_association": "OWNER"}}


def entry(uid, raw, flags):
    message = BytesParser(policy=policy.default).parsebytes(raw)
    return {"uid": str(uid), "draft_id": str(message["X-Webactueel-Draft-ID"]),
            "message": message, "sha256": hashlib.sha256(raw).hexdigest(),
            "draft_flag": b"\\DRAFT" in flags, "flags": set(flags), "size": len(raw), "raw": raw}


def fixtures():
    base, revised, rows = {}, {}, [mod.HEADERS]
    for number in range(1, 451):
        key = "draft-" + format(number, "032x")
        company = "Fictief bedrijf " + str(number)
        old_body = "Hoi,\n\nJullie bieden een dienst aan.\n\nZijn er vragen?\n\n" + mod.legacy.OPT + "\n\nGroet,\nAndrew"
        previous = {"draft_id": key, "company": company, "email": "info@voorbeeld.nl",
                    "source_url": "https://voorbeeld.nl/", "subject": "Vraag " + str(number), "body": old_body}
        original = dict(previous, subject="Oorspronkelijk " + str(number))
        category = "target" if number <= 410 else "held" if number == 411 else "excluded"
        base[key] = {"number": number, "category": category, "current": original, "new": previous}
        body = ("Goedendag,\n\nJullie geven duidelijke informatie over jullie diensten. Ik kan die informatie ook op mobiel overzichtelijk tonen.\n\n"
                "Zal ik een voorbeeld sturen voor " + company + "?\n\n" + mod.legacy.OPT + "\n\nGroet,\nAndrew")
        revised[key] = (dict(base[key], current=previous, new=dict(previous, body=body))
                        if category == "target" else dict(base[key]))
        rows.append([str(number), key, company, "vakbedrijven", previous["subject"],
                     "HERZIEN VOOR MENSELIJKE CONTROLE" if category == "target" else "OVERGESLAGEN",
                     "Review", body if category == "target" else "", "Controle", "https://voorbeeld.nl/",
                     "BESTAAND CONCEPT ONGEWIJZIGD", "NIET VERZENDGEREED - HANDMATIGE REVIEW", "Review"])
    return base, revised, rows


class Server:
    def __init__(self, base, records):
        self.boxes = {"Drafts": {}, mod.archives.ARCHIVE: {}}
        self.next_id = 1000
        self.log = []
        self.fail_append_at = None
        self.appends = 0
        self.fail_expunge_once = False
        self.mutate_on_append = None
        self.corrupt_copy = False
        for key, row in records.items():
            n = row["number"]
            if row["category"] in {"target", "held"}:
                self.boxes["Drafts"][str(n)] = entry(n, build_message(row["current"]).as_bytes(), {b"\\DRAFT"})
            if row["category"] == "target":
                self.boxes[mod.archives.ARCHIVE][str(n)] = entry(n, build_message(base[key]["current"]).as_bytes(), {b"\\SEEN"})

    def connect(self):
        return Client(self)

    def scan(self, client):
        return copy.deepcopy(self.boxes[client.folder])

    def select(self, client, folder, readonly=True):
        client.folder = folder
        return "7"


class Client:
    def __init__(self, server):
        self.server = server
        self.folder = "Drafts"

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "' + name.encode() + b'"' for name in self.server.boxes]

    def create(self, folder):
        name = folder.strip('"')
        self.server.boxes[name] = {}
        return "OK", []

    def logout(self):
        return None

    def append(self, folder, flags, date, raw):
        self.server.appends += 1
        if self.server.fail_append_at == self.server.appends:
            return "NO", []
        self.server.next_id += 1
        uid = str(self.server.next_id)
        name = folder.strip('"')
        self.server.boxes[name][uid] = entry(uid, raw, {b"\\DRAFT"})
        self.server.log.append(("APPEND", name, uid))
        if self.server.mutate_on_append:
            action, self.server.mutate_on_append = self.server.mutate_on_append, None
            action(self.server)
        return "OK", []

    def uid(self, command, ids, *args):
        wanted = set(ids.split(","))
        assert wanted and "*" not in ids
        self.server.log.append((command, self.folder, ids))
        box = self.server.boxes[self.folder]
        if command == "COPY":
            target = args[0].strip('"')
            for old_uid in sorted(wanted, key=int):
                item = box[old_uid]
                self.server.next_id += 1
                uid = str(self.server.next_id)
                raw = item["raw"] + (b"broken" if self.server.corrupt_copy else b"")
                self.server.boxes[target][uid] = entry(uid, raw, item["flags"])
        elif command == "STORE":
            verb, flag = args
            flag = flag.strip("()").upper().encode()
            for uid in wanted & set(box):
                if verb.startswith("+"):
                    box[uid]["flags"].add(flag)
                else:
                    box[uid]["flags"].discard(flag)
                box[uid]["draft_flag"] = b"\\DRAFT" in box[uid]["flags"]
        elif command == "EXPUNGE":
            if self.server.fail_expunge_once:
                self.server.fail_expunge_once = False
                return "NO", []
            for uid in wanted & set(box):
                if b"\\DELETED" in box[uid]["flags"]:
                    del box[uid]
        else:
            raise AssertionError(command)
        return "OK", []


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.base, self.records, self.rows = fixtures()

    def test_explicit_owner_authorization_and_no_other_modes(self):
        for mode in mod.MODES | {"AUDIT"}:
            mod.authorize(mode, event(mode))
        for changed in (dict(event(), action="edited"), dict(event(), issue={"number": 1}),
                        dict(event(), repository={"full_name": "other/repo"}),
                        dict(event(), comment={"body": mod.legacy.PREFIX + "REVISION_ALL", "user": {"login": "other"}})):
            with self.assertRaises(RuntimeError):
                mod.authorize("REVISION_ALL", changed)
        with self.assertRaises(RuntimeError):
            mod.authorize("SEND", event("SEND"))

    def test_copy_only_source_reads_keep_recipient_and_suppression_gate(self):
        with patch.object(mod.legacy, "_private_rows", return_value=self.base) as source, \
             patch.object(mod.legacy.history.source, "read", return_value=self.rows):
            _, revised = mod.load_scope(object())
            self.assertEqual(sum(x["category"] == "target" for x in revised.values()), 410)
            self.assertFalse(source.call_args.kwargs["require_fresh"])
            for key, value in revised.items():
                self.assertEqual(value["new"]["email"], self.base[key]["new"]["email"])
                self.assertEqual(value["new"]["source_url"], self.base[key]["new"]["source_url"])
        with patch.object(mod.legacy, "_private_rows", side_effect=RuntimeError("historical_suppression_changed")):
            with self.assertRaisesRegex(RuntimeError, "historical_suppression_changed"):
                mod.load_scope(object())

    def test_proposals_cannot_change_identity_subject_or_release_a_hold(self):
        for column, value in ((0, "999"), (1, "draft-" + "f" * 32), (2, "Other"), (4, "Changed subject"), (11, "SEND")):
            rows = copy.deepcopy(self.rows)
            rows[1][column] = value
            with self.subTest(column=column), patch.object(mod.legacy, "_private_rows", return_value=self.base), \
                 patch.object(mod.legacy.history.source, "read", return_value=rows):
                with self.assertRaises(RuntimeError):
                    mod.load_scope(object())
        rows = copy.deepcopy(self.rows)
        rows[411][7] = rows[1][7]
        with patch.object(mod.legacy, "_private_rows", return_value=self.base), \
             patch.object(mod.legacy.history.source, "read", return_value=rows):
            with self.assertRaisesRegex(RuntimeError, "source_scope"):
                mod.load_scope(object())

    def test_both_greetings_but_not_missing_optout_or_placeholders(self):
        body = self.rows[1][7]
        mod.validate_body(body)
        mod.validate_body(body.replace("Goedendag,", "Hoi,"))
        for wrong in (body.replace(mod.legacy.OPT, ""), body.replace("diensten.", "[company]."),
                      body.replace("Andrew", "Other"), body.replace("sturen voor", "sturen? Voor")):
            with self.assertRaises(RuntimeError):
                mod.validate_body(wrong)

    def execute(self, server, mode="REVISION_ALL", second_scope=None):
        scopes = [(self.base, self.records), second_scope or (self.base, self.records)]
        with patch.object(mod, "load_scope", side_effect=scopes), \
             patch.object(mod.legacy, "authorized_writer", return_value=object()), \
             patch.object(mod.legacy.imap, "target_guard"), \
             patch.object(mod.legacy.imap, "uidplus", return_value=True), \
             patch.object(mod.legacy, "find_drafts_folder", return_value="Drafts"), \
             patch.object(mod.archives, "find_drafts_folder", return_value="Drafts"), \
             patch.object(mod.legacy.imap, "select", side_effect=server.select), \
             patch.object(mod.legacy.transport, "scan", side_effect=server.scan):
            return mod.run(mode, event(mode), connector=server.connect)

    def test_full_batch_exact_backup_readback_and_idempotent_second_run(self):
        server = Server(self.base, self.records)
        initial = copy.deepcopy(server.boxes["Drafts"])
        original_archive = copy.deepcopy(server.boxes[mod.archives.ARCHIVE])
        outcome = self.execute(server)
        self.assertEqual(outcome["revised"], 410)
        self.assertEqual(outcome["revision_archived"], 410)
        self.assertEqual(outcome["sent"], 0)
        self.assertEqual(len(server.boxes["Drafts"]), 411)
        self.assertEqual(server.boxes["Drafts"]["411"]["sha256"], initial["411"]["sha256"])
        self.assertEqual({u: i["sha256"] for u, i in server.boxes[mod.archives.ARCHIVE].items()},
                         {u: i["sha256"] for u, i in original_archive.items()})
        previous_by_key = {i["draft_id"]: i for i in server.boxes[mod.archives.REVISION_ARCHIVE].values()}
        for uid, item in initial.items():
            if uid != "411":
                self.assertEqual(item["raw"], previous_by_key[item["draft_id"]]["raw"])
                self.assertFalse(previous_by_key[item["draft_id"]]["draft_flag"])
        writes = len(server.log)
        again = self.execute(server)
        self.assertEqual(again["pending"], 0)
        self.assertEqual(len(server.log), writes)
        audit = self.execute(server, "AUDIT")
        self.assertEqual((audit["already_new"], audit["archived"], audit["revised"]), (410, 410, 410))

    def test_pilot_changes_only_one_existing_draft(self):
        server = Server(self.base, self.records)
        outcome = self.execute(server, "REVISION_PILOT")
        self.assertEqual((outcome["revised"], outcome["pending"]), (1, 409))
        self.assertEqual(len(server.boxes["Drafts"]), 411)
        self.assertIn("2", server.boxes["Drafts"])

    def test_read_only_modes_never_create_archive_or_write_mail(self):
        for mode in ("AUDIT", "REVISION_PRECHECK", "REVISION_AUDIT"):
            server = Server(self.base, self.records)
            result = self.execute(server, mode)
            self.assertEqual(result["sent"], 0)
            self.assertEqual(server.log, [])
            self.assertNotIn(mod.archives.REVISION_ARCHIVE, server.boxes)

    def test_append_failure_preserves_originals_and_removes_only_staged_copies(self):
        server = Server(self.base, self.records)
        server.fail_append_at = 3
        before = {u: i["sha256"] for u, i in server.boxes["Drafts"].items()}
        with self.assertRaisesRegex(RuntimeError, "stage_failed"):
            self.execute(server)
        self.assertEqual(before, {u: i["sha256"] for u, i in server.boxes["Drafts"].items()})
        self.assertTrue(all(b"\\DELETED" not in i["flags"] for i in server.boxes["Drafts"].values()))

    def test_changed_source_or_archive_bytes_prevents_original_deletion(self):
        server = Server(self.base, self.records)
        changed = copy.deepcopy(self.records)
        changed[next(iter(changed))]["new"]["body"] += "changed"
        with self.assertRaisesRegex(RuntimeError, "source_changed"):
            self.execute(server, second_scope=(self.base, changed))
        self.assertEqual(set(server.boxes["Drafts"]), {str(i) for i in range(1, 412)})
        server = Server(self.base, self.records)
        server.corrupt_copy = True
        with self.assertRaises(RuntimeError):
            self.execute(server)
        self.assertEqual(server.appends, 0)
        self.assertEqual(len(server.boxes["Drafts"]), 411)

    def test_failed_targeted_expunge_restores_original_flags(self):
        server = Server(self.base, self.records)
        server.fail_expunge_once = True
        with self.assertRaisesRegex(RuntimeError, "delete_failed"):
            self.execute(server)
        self.assertEqual(set(server.boxes["Drafts"]), {str(i) for i in range(1, 412)})
        self.assertTrue(all(b"\\DELETED" not in i["flags"] for i in server.boxes["Drafts"].values()))


if __name__ == "__main__":
    unittest.main()
