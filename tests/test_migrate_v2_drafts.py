"""Offline, fictional tests of the guarded V2 draft-only migration."""
import copy
import unittest
from unittest.mock import patch

import migrate_v2_drafts as m
from myhost_draft import build_message
from test_draft_revision import Server, Client, entry, fixtures


def event(mode, *, owner="Yolol100"):
    return {"action": "created",
            "repository": {"full_name": "Yolol100/Leadscanner"},
            "issue": {"number": 1659},
            "comment": {"body": m.PREFIX + mode, "user": {"login": owner},
                        "author_association": "OWNER"}}


def data():
    base, first, _ = fixtures()
    result = {}
    for key, record in first.items():
        previous = dict(record["current"])
        if record["category"] == "target":
            subject = "Verbeterde mail " + str(record["number"])
            body = ("Goedendag,\n\n"
                    "Ik zag dat jullie een lokale dienst bieden. Een korte mobiele "
                    "pagina met een duidelijke ingang kan daar goed op aansluiten.\n\n"
                    "Zal ik één voorbeeld laten zien?\n\n"
                    + m.OPT + "\n\nGroet,\nAndrew")
            category = "target"
            active = True
            newer = dict(previous, subject=subject, body=body)
        else:
            category = "held"
            active = False
            newer = previous
        result[key] = dict(record, current=previous, new=newer,
                           category=category, active=active)
    return base, result


def server_with(records, base):
    server = Server(base, records)
    # No historic held/excluded record may enter live Drafts.
    for uid in list(server.boxes["Drafts"]):
        if server.boxes["Drafts"][uid]["draft_id"] not in {
                key for key, r in records.items() if r["category"] == "target"}:
            del server.boxes["Drafts"][uid]
    # Mimic five user-removed drafts; a migration must not delete unknown mail.
    for uid in ("406", "407", "408", "409", "410"):
        server.boxes["Drafts"].pop(uid, None)
    return server


class RecoveryClient(Client):
    """Synthetic IMAP: honor non-Draft flags in separate proof folder."""

    def append(self, folder, flags, date, raw):
        result = super().append(folder, flags, date, raw)
        if result[0] == "OK" and folder.strip('"') == m.archives.V2_CREATED:
            item = self.server.boxes[m.archives.V2_CREATED][
                str(self.server.next_id)]
            item["flags"], item["draft_flag"] = {b"\SEEN"}, False
        return result


class RecoveryServer(Server):
    def connect(self):
        return RecoveryClient(self)


def recovered_server(base, records):
    server = RecoveryServer(base, records)
    for uid in list(server.boxes["Drafts"]):
        if int(uid) > 405 or records[
                server.boxes["Drafts"][uid]["draft_id"]]["category"] != "target":
            del server.boxes["Drafts"][uid]
    server.boxes[m.archives.V2_ARCHIVE] = {}
    for uid, item in list(server.boxes["Drafts"].items()):
        record = records[item["draft_id"]]
        server.boxes["Drafts"][uid] = entry(
            int(uid), build_message(record["new"]).as_bytes(), {b"\DRAFT"})
        server.boxes[m.archives.V2_ARCHIVE][uid] = entry(
            int(uid), build_message(record["current"]).as_bytes(), {b"\SEEN"})
    return server


class MigrationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.base, self.records = data()

    def execute(self, server, mode, *, loader=None):
        loader = loader or (lambda _: self.records)
        with patch.object(m.legacy, "authorized_writer", return_value=object()), \
             patch.object(m.legacy.imap, "target_guard"), \
             patch.object(m.legacy.imap, "uidplus", return_value=True), \
             patch.object(m.legacy, "find_drafts_folder", return_value="Drafts"), \
             patch.object(m.archives, "find_drafts_folder", return_value="Drafts"), \
             patch.object(m.legacy.imap, "select", side_effect=server.select), \
             patch.object(m.legacy.transport, "scan", side_effect=server.scan):
            return m.run(mode, event(mode), connector=server.connect, loader=loader)

    def test_authorization_and_restricted_mode(self):
        for mode in m.MODES:
            m.authorize(event(mode), mode)
        with self.assertRaises(RuntimeError):
            m.authorize(event("PILOT", owner="other"), "PILOT")
        with self.assertRaises(RuntimeError):
            m.authorize(event("SEND"), "SEND")
        with self.assertRaises(RuntimeError):
            m.authorize({**event("PILOT"), "issue": {"number": 1}}, "PILOT")

    def test_copy_contract_rejects_generic_or_malformed_mail(self):
        example = next(r["new"]["body"] for r in self.records.values()
                       if r["category"] == "target")
        m.valid_body(example)
        for bad in (example.replace(m.OPT, ""),
                    example.replace("Zal ik", "Zal ik {{naam}}"),
                    example.replace("Andrew", "Sender"),
                    example.replace("dienst bieden.", "dienst bieden?"),
                    example.replace("pagina", "Was gewoon benieuwd. pagina")):
            with self.subTest(bad=bad[:20]), self.assertRaises(RuntimeError):
                m.valid_body(bad)

    def test_strict_classification_and_source_holds(self):
        server = server_with(self.records, self.base)
        box = copy.deepcopy(server.boxes["Drafts"])
        states = m.classify(self.records, box)
        self.assertEqual(len(states), 405)
        self.assertEqual(sum(v[1] == "old" for v in states.values()), 405)
        fake = next(key for key, r in self.records.items()
                    if r["category"] == "held")
        box["999"] = entry(999, build_message(self.records[fake]["current"]).as_bytes(),
                           {b"\\DRAFT"})
        with self.assertRaisesRegex(RuntimeError, "v2_mailbox_identity_changed"):
            m.classify(self.records, box)

    def test_inactive_source_hold_is_preserved(self):
        server = server_with(self.records, self.base)
        first = next(key for key, r in self.records.items()
                     if r["category"] == "target")
        self.records[first]["category"] = "source_hold"
        self.records[first]["active"] = False
        states = m.classify(self.records, server.boxes["Drafts"])
        self.assertEqual(states[first][1], "old")
        server.boxes["Drafts"]["1"] = entry(
            1, build_message(self.records[first]["new"]).as_bytes(), {b"\\DRAFT"})
        with self.assertRaisesRegex(RuntimeError, "v2_source_hold_modified"):
            m.classify(self.records, server.boxes["Drafts"])

    def test_read_only_precheck_does_not_create_archive(self):
        server = server_with(self.records, self.base)
        result = self.execute(server, "PRECHECK")
        self.assertEqual(result["old"], 405)
        self.assertEqual(result["missing"], 5)
        self.assertEqual(result["sent"], 0)
        self.assertNotIn(m.archives.V2_ARCHIVE, server.boxes)
        self.assertFalse(any(c[0] == "APPEND" for c in server.log))

    def test_pilot_archives_original_and_only_replaces_one_uid(self):
        server = server_with(self.records, self.base)
        original = server.boxes["Drafts"]["1"]["raw"]
        outcome = self.execute(server, "PILOT")
        self.assertEqual(outcome["installed"], 1)
        self.assertEqual(outcome["sent"], 0)
        self.assertEqual(len(server.boxes["Drafts"]), 405)
        self.assertNotIn("1", server.boxes["Drafts"])
        archive = list(server.boxes[m.archives.V2_ARCHIVE].values())
        self.assertEqual(len(archive), 1)
        self.assertEqual(archive[0]["raw"], original)
        self.assertFalse(archive[0]["draft_flag"])
        self.assertEqual(self.execute(server, "PILOT")["new"], 1)

    def test_changed_source_stops_before_deleting_original(self):
        server = server_with(self.records, self.base)
        changed = copy.deepcopy(self.records)
        changed[next(iter(changed))]["new"]["subject"] = "Changed"
        calls = iter([self.records, changed])
        with self.assertRaisesRegex(RuntimeError, "v2_source_changed"):
            self.execute(server, "PILOT", loader=lambda _: next(calls))
        self.assertIn("1", server.boxes["Drafts"])
        self.assertEqual(m.classify(self.records, server.boxes["Drafts"])[
            next(iter(self.records))][1], "old")

    def test_missing_draft_is_not_recreated_before_old_batch_updated(self):
        server = server_with(self.records, self.base)
        with self.assertRaisesRegex(RuntimeError, "v2_recreate_before_update"):
            self.execute(server, "RECREATE_BATCH_5")
        self.assertEqual(len(server.boxes["Drafts"]), 405)

    def execute_recovery(self, server, mode, *, loader=None):
        def uidset(client):
            return set(server.boxes[client.folder])

        def fetch(client, uid):
            return server.boxes[client.folder][uid]

        def raw_snapshot(client, uid, sha):
            from hashlib import sha256
            raw = server.boxes[client.folder][uid]["raw"]
            self.assertEqual(sha256(raw).hexdigest(), sha)
            return raw

        with patch.object(m.archives.transport, "uidset", side_effect=uidset), \
             patch.object(m.archives.transport, "scan", side_effect=server.scan), \
             patch.object(m.archives.transport, "fetch_message", side_effect=fetch), \
             patch.object(m.archives.drafts, "_raw_snapshot",
                          side_effect=raw_snapshot):
            return self.execute(server, mode, loader=loader)

    def test_recovery_creates_only_missing_with_private_mime_proofs(self):
        server = recovered_server(self.base, self.records)
        self.assertEqual(len(server.boxes["Drafts"]), 405)
        out = self.execute_recovery(server, "RECREATE_REMAINING")
        self.assertEqual((out["created"], out["total"], out["new"]),
                         (5, 410, 410))
        self.assertEqual(out["archived"], 405)
        self.assertEqual(out["recovery_proofs"], 5)
        self.assertEqual(out["sent"], 0)
        self.assertEqual(out["pending"], 0)
        self.assertEqual(len(server.boxes[m.archives.V2_CREATED]), 5)
        self.assertTrue(all(not v["draft_flag"] for v
                            in server.boxes[m.archives.V2_CREATED].values()))
        self.assertFalse(any(action[0] in {"STORE", "EXPUNGE"} for action
                             in server.log))
        repeat = self.execute_recovery(server, "RECREATE_REMAINING")
        self.assertEqual(repeat["new"], 410)
        self.assertEqual(self.execute_recovery(server, "AUDIT")["new"], 410)
        # Changing only a MIME header must fail the independent byte proof.
        recreated = next(
            item for item in server.boxes["Drafts"].values()
            if item["draft_id"] in
            {v["draft_id"] for v in server.boxes[m.archives.V2_CREATED].values()})
        record = self.records[recreated["draft_id"]]
        server.boxes["Drafts"][recreated["uid"]] = entry(
            int(recreated["uid"]),
            build_message(record["new"]).as_bytes(), {b"\\DRAFT"})
        with self.assertRaisesRegex(RuntimeError, "v2_recovery_proof_mismatch"):
            self.execute_recovery(server, "AUDIT")

    def test_recovery_reuses_proofs_after_interrupted_drafts_append(self):
        server = recovered_server(self.base, self.records)
        # First five IMAP appends build private MIME proofs; the next
        # append adds one draft. Simulate the second draft APPEND failing.
        server.fail_append_at = 7
        with self.assertRaisesRegex(RuntimeError, "v2_create_failed"):
            self.execute_recovery(server, "RECREATE_REMAINING")
        self.assertEqual(len(server.boxes[m.archives.V2_CREATED]), 5)
        self.assertEqual(len(server.boxes["Drafts"]), 406)
        resumed = self.execute_recovery(server, "RECREATE_REMAINING")
        self.assertEqual(resumed["created"], 4)
        self.assertEqual(resumed["new"], 410)
        self.assertEqual(resumed["recovery_proofs"], 5)
        self.assertEqual(self.execute_recovery(server, "AUDIT")["pending"], 0)

    def test_recovery_rechecks_source_after_private_proof(self):
        server = recovered_server(self.base, self.records)
        changed = copy.deepcopy(self.records)
        changed[next(iter(changed))]["new"]["body"] = "Modified"
        reads = iter((self.records, self.records, changed))
        with self.assertRaisesRegex(RuntimeError, "v2_source_changed"):
            self.execute_recovery(
                server, "RECREATE_REMAINING", loader=lambda _: next(reads))
        self.assertEqual(len(server.boxes["Drafts"]), 405)
        self.assertEqual(len(server.boxes[m.archives.V2_CREATED]), 5)
        self.assertEqual(
            self.execute_recovery(server, "RECREATE_REMAINING")["new"], 410)

    def test_real_source_shapes_keep_skips_and_low_scores_as_holds(self):
        from datetime import datetime, timezone
        rows = []
        prior = [m.rev.HEADERS]
        qa = [["Nr", "Draft-ID", "Bedrijf", "E-mailadres"] + [""] * 12]
        v2_batches = [[m.V2_HEADERS] for _ in range(5)]
        proof = [list(m.legacy.websites.COLUMNS)]
        reviewed = 0
        for key, item in self.records.items():
            n = item["number"]
            old = item["current"]
            newer = item["new"]
            is_target = item["category"] == "target"
            low_score = n <= 54
            group = (n - 1)//100
            q = [""] * 16
            q[0], q[1], q[2], q[3] = str(n), key, old["company"], old["email"]
            q[5], q[6], q[8] = newer["subject"], newer["body"], old["source_url"]
            q[10], q[13] = ("8.5" if low_score else "9.2"), "VOOR_MENSELIJKE_EINDCONTROLE"
            qa.append(q)
            copy = [""] * 13
            copy[0], copy[1], copy[2], copy[4] = str(n), key, old["company"], newer["subject"]
            copy[5] = ("HERZIEN VOOR MENSELIJKE CONTROLE" if is_target
                       else "OVERGESLAGEN")
            copy[7] = old["body"] if is_target else ""
            copy[11] = "NIET VERZENDGEREED - HANDMATIGE REVIEW"
            prior.append(copy)
            props = [""] * 15
            props[0], props[1], props[2], props[3], props[4] = (
                str(n), key, old["company"], old["email"], old["source_url"])
            props[11], props[12] = (
                "NIET VERZENDGEREED - menselijke controle nodig", "ONGEWIJZIGD")
            if is_target:
                reviewed += 1
                props[5], props[6] = newer["subject"], newer["body"]
                props[7] = "TEKSTCHECK_OK 60 woorden"
                props[13] = "REVIEW - individuele broncontrole open"
            else:
                props[13] = "HOLD - NIET VERVANGEN"
            v2_batches[group].append(props)
            row = [""] * 14
            row[0] = "Review450:" + key
            row[6] = old["email"]
            row[11] = datetime.now(timezone.utc).isoformat()
            row[12] = "verified_with_detail"
            proof.append(row)
        self.assertEqual(reviewed, 410)

        def source_read(_session, _sid, a1):
            if a1.startswith("QA450Actueel!"):
                return qa
            if a1.startswith("'Conceptkwaliteit 20261018'!"):
                return prior
            if a1.startswith("WebsiteEvidence!"):
                return proof
            for n in range(1, 6):
                if a1.startswith(f"'Korte mails V2 B{n} REVIEW 20261019'!"):
                    return v2_batches[n-1]
            raise AssertionError("Unexpected source")
        with patch.object(m.legacy, "_private_rows", return_value=self.records), \
             patch.object(m.legacy.history.source, "read", side_effect=source_read):
            result = m.source_scope(object())
        self.assertEqual(len(result), 450)
        self.assertEqual(sum(r["active"] for r in result.values()), 356)
        self.assertEqual(sum(r["category"] == "held" for r in result.values()), 40)
        self.assertEqual(sum(r.get("quality_ready") is False for r in result.values()), 54)

    def test_archive_restricts_scope_to_fixed_private_folder(self):
        server = server_with(self.records, self.base)
        client = server.connect()
        with self.assertRaisesRegex(RuntimeError, "archive_folder_name_invalid"):
            m.archives._archive(client, folder="INBOX", create=True)
        self.assertEqual(
            m.archives._archive(client, folder=m.archives.V2_ARCHIVE, create=True),
            m.archives.V2_ARCHIVE)


if __name__ == "__main__":
    unittest.main()
