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



class SheetsBatchSnapshotTests(unittest.TestCase):
    """Four fresh live Sheets reads per gate; no persistent source cache."""

    @staticmethod
    def backend(*, truncate=False, wrong_range=False, status=200):
        from urllib.parse import parse_qs, urlsplit

        def get(url, **kwargs):
            parsed = urlsplit(url)
            assert parsed.scheme == "https"
            assert parsed.netloc == "sheets.googleapis.com"
            assert parsed.path.endswith("/values:batchGet")
            assert kwargs.get("timeout") == 30
            spreadsheet_id = parsed.path.split("/")[3]
            ranges = parse_qs(parsed.query)["ranges"]
            reply = []
            for index, requested in enumerate(ranges):
                tab, a1 = requested.split("!", 1)
                if a1 == "A:J":
                    a1 = "A1:J10000"
                if wrong_range and index == 0:
                    a1 = "B1:J10000"
                reply.append({
                    "range": tab + "!" + a1,
                    "values": [[requested]],
                })
            if truncate:
                reply.pop()
            return Mock(status_code=status, json=lambda: {
                "spreadsheetId": spreadsheet_id, "valueRanges": reply,
            })
        result = Mock()
        result.get.side_effect = get
        return result

    def test_all_sources_still_read_fresh_in_four_batches(self):
        from urllib.parse import quote
        import registry_readonly as registry
        backend = self.backend()
        first = mod.ScopedSheetsSnapshot(backend)
        self.assertEqual(backend.get.call_count, 4)
        def check(reader, sid, a1):
            url = ("https://sheets.googleapis.com/v4/spreadsheets/"
                   + sid + "/values/" + quote(a1, safe=""))
            assert reader.get(url, timeout=20).status_code == 200
            self.assertEqual(reader.get(url).json()["values"], [[a1]])
        for sid, a1 in [
            (mod.history.source.SID, "QA450Actueel!A2:P451"),
            (mod.history.source.SID, "'Gespreksstijl Fase5 20261016'!A1:M51"),
            (mod.history.source.SID, "WebsiteEvidence!A1:N1000"),
            (mod.history.source.SID, "LeadHistory!A:J"),
            (registry.REGISTRY_ID, "DedupeRegistry!A:J"),
            (registry.REGISTRY_ID, "HistoricalHmacV2!A:J"),
            (registry.DRAFT_QUEUE_ID, "DraftQueue!A:J"),
        ]:
            check(first, sid, a1)
        key = ("https://sheets.googleapis.com/v4/spreadsheets/"
               + registry.REGISTRY_ID + "/values/"
               + quote("HistoricalHmacV2!A:J", safe=""))
        first.get(key).json()["values"][0][0] = "accidental local mutation"
        self.assertEqual(first.get(key).json()["values"],
                         [["HistoricalHmacV2!A:J"]])
        second = mod.ScopedSheetsSnapshot(backend)
        self.assertEqual(backend.get.call_count, 8)
        self.assertEqual(second.get(key).json()["values"],
                         [["HistoricalHmacV2!A:J"]])

    def test_real_sheets_grid_clamps_whole_column_ranges(self):
        """Accept A:J -> A:H when the sheet physically has eight columns."""
        backend = self.backend()
        original = backend.get.side_effect
        clamped_columns = {
            "LeadHistory": "H",
            "DedupeRegistry": "H",
            "HistoricalHmacV2": "F",
            "Keys": "C",
            "DraftQueue": "G",
        }

        def clipped(url, **kwargs):
            response = original(url, **kwargs)
            payload = response.json()
            for item in payload["valueRanges"]:
                tab, bounds = item["range"].split("!", 1)
                if tab in clamped_columns and bounds == "A1:J10000":
                    item["range"] = tab + "!A1:" + clamped_columns[tab] + "10000"
            return Mock(status_code=200, json=lambda: payload)

        backend.get.side_effect = clipped
        reader = mod.ScopedSheetsSnapshot(backend)
        self.assertEqual(backend.get.call_count, 4)
        from urllib.parse import quote
        source = "LeadHistory!A:J"
        url = ("https://sheets.googleapis.com/v4/spreadsheets/"
               + mod.history.source.SID + "/values/" + quote(source, safe=""))
        self.assertEqual(reader.get(url).json()["values"], [[source]])

    def test_clamp_must_not_expand_or_shift_grid_columns(self):
        backend = self.backend()
        original = backend.get.side_effect

        def out_of_scope(url, **kwargs):
            response = original(url, **kwargs)
            payload = response.json()
            for item in payload["valueRanges"]:
                if item["range"].startswith("LeadHistory!"):
                    item["range"] = "LeadHistory!B1:K10000"
            return Mock(status_code=200, json=lambda: payload)

        backend.get.side_effect = out_of_scope
        with self.assertRaisesRegex(RuntimeError, "conversation_batch_source_invalid"):
            mod.ScopedSheetsSnapshot(backend)

    def test_batch_missing_ranges_or_wrong_a1_fails_closed(self):
        for options in ({"truncate": True}, {"wrong_range": True}):
            with self.assertRaisesRegex(RuntimeError, "conversation_batch_source_invalid"):
                mod.ScopedSheetsSnapshot(self.backend(**options))

    def test_batch_http_failure_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "conversation_batch_source_read_failed"):
            mod.ScopedSheetsSnapshot(self.backend(status=403))

    def test_unknown_or_cross_origin_single_get_is_not_delegated(self):
        from urllib.parse import quote
        backend = self.backend()
        session = mod.ScopedSheetsSnapshot(backend)
        for url in [
            "https://example.com/v4/spreadsheets/abc/values/LeadHistory%21A%3AJ",
            "http://sheets.googleapis.com/v4/spreadsheets/abc/values/LeadHistory%21A%3AJ",
            "https://sheets.googleapis.com/v4/spreadsheets/abc/values/LeadHistory%21A%3AJ",
            "https://sheets.googleapis.com/v4/spreadsheets/"
                + mod.history.source.SID + "/values/"
                + quote("UnknownTab!A1:Z999", safe=""),
        ]:
            with self.assertRaisesRegex(RuntimeError, "conversation_unbatched_source_request"):
                session.get(url)
        self.assertEqual(backend.get.call_count, 4)

    def test_private_source_gate_still_calls_full_original_validators(self):
        source = object()
        wrapped = object()
        with patch.object(mod, "ScopedSheetsSnapshot", return_value=wrapped) as b, \
             patch.object(mod.history, "load_scope", side_effect=RuntimeError("sentinel")) as load:
            with self.assertRaisesRegex(RuntimeError, "sentinel"):
                mod._private_rows(source)
            b.assert_called_once_with(source)
            load.assert_called_once_with(wrapped)


class ConversationRegressionTests(unittest.TestCase):
    def test_read_throttle_and_429_retry_preserve_full_sheet_access(self):
        clock = [0.0]
        delays = []
        def now():
            return clock[0]
        def sleep(seconds):
            self.assertGreaterEqual(seconds, 0)
            delays.append(seconds)
            clock[0] += seconds
        backend = Mock()
        backend.get.side_effect = [
            Mock(status_code=429), Mock(status_code=200, json=lambda: {"values": [["a"]]}),
            Mock(status_code=200),
        ]
        session = mod.RateLimitedSourceReads(backend, clock=now, sleeper=sleep)
        response = session.get("https://sheets.googleapis.com/test")
        self.assertEqual(response.status_code, 200)
        response = session.get("https://sheets.googleapis.com/test")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(backend.get.call_count, 3)
        self.assertTrue(any(x >= 5 for x in delays))
        self.assertTrue(any(x >= 1.5 for x in delays))

    def test_non_transient_sheet_errors_are_not_retried(self):
        clock = Mock(return_value=3)
        backend = Mock()
        backend.get.return_value = Mock(status_code=403)
        session = mod.RateLimitedSourceReads(backend, clock=clock,
                                             sleeper=Mock())
        self.assertEqual(session.get("https://sheets.googleapis.com/test").status_code, 403)
        backend.get.assert_called_once()

    def test_429_exhaustion_fails_closed_without_extra_reads(self):
        backend = Mock()
        backend.get.return_value = Mock(status_code=429)
        session = mod.RateLimitedSourceReads(
            backend, clock=Mock(return_value=10),
            sleeper=Mock())
        with self.assertRaisesRegex(RuntimeError, "sheet_transient_exhausted"):
            session.get("https://sheets.googleapis.com/test")
        self.assertEqual(backend.get.call_count, session.RETRIES)

    def test_public_failure_reason_is_static_allowlist_only(self):
        self.assertEqual(mod._safe_reason(RuntimeError("archive_append_failed")),
                         "archive_append_failed")
        self.assertEqual(mod._safe_reason(RuntimeError("conversation_uidplus_required")),
                         "conversation_uidplus_required")
        self.assertEqual(mod._safe_reason(RuntimeError("private_sheet_read_failed")),
                         "private_sheet_read_failed")
        for error in (RuntimeError("archive_append_failed token=secret"),
                      RuntimeError("account@example.nl"),
                      KeyError(DID), ValueError("tokens")):
            self.assertEqual(mod._safe_reason(error), "private_or_unclassified_error")

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

    def test_source_holds_and_historical_holds_need_separate_review(self):
        baseline = dict(mod.EXPECTED_COUNTS)
        mod.validate_source_population(baseline, 450)
        for promotions in (1, 8, 15, 16):
            updated = dict(baseline,
                           target=391 + promotions,
                           source_hold=16 - promotions)
            mod.validate_source_population(updated, 450)
        for approved in (1, 2, 3, 4):
            reviewed = dict(baseline,
                            target=407 + approved, source_hold=0,
                            held=4 - approved)
            mod.validate_source_population(reviewed, 450)
        forbidden = [
            dict(baseline, target=390, source_hold=17),
            dict(baseline, target=392, source_hold=16),
            dict(baseline, target=408, source_hold=-1),
            dict(baseline, held=3, target=391),
            dict(baseline, held=5, target=390),
            dict(baseline, closed=0, target=392),
            dict(baseline, excluded=37, target=392),
        ]
        for counts in forbidden:
            with self.subTest(changed=counts):
                with self.assertRaisesRegex(RuntimeError, "population_changed"):
                    mod.validate_source_population(counts, 450)
        with self.assertRaisesRegex(RuntimeError, "population_changed"):
            mod.validate_source_population(baseline, 449)

    def test_historical_release_requires_private_review_and_verified_email(self):
        proposal = [""] * 13
        evidence = [""] * 14
        proposal[9] = "VOORLOPIG REDACTIONEEL VOORSTEL"
        proposal[10] = mod.HOLD_RELEASE_SOURCE
        proposal[11] = mod.HOLD_RELEASE_LEGAL
        evidence[12] = "verified_activity_only"
        self.assertTrue(mod._historical_hold_approved(
            "held", proposal, evidence))
        evidence[12] = "verified_with_detail"
        self.assertTrue(mod._historical_hold_approved(
            "held", proposal, evidence))
        for change in (
            lambda p, e: p.__setitem__(9, "OVERGESLAGEN - BRONBLOKKADE"),
            lambda p, e: p.__setitem__(10, "HOLD_BRONCHECK"),
            lambda p, e: p.__setitem__(11, "VERZENDGEREED"),
            lambda p, e: e.__setitem__(12, "needs_manual_check"),
        ):
            p, e = list(proposal), list(evidence)
            change(p, e)
            self.assertFalse(mod._historical_hold_approved(
                "held", p, e))
        self.assertFalse(mod._historical_hold_approved(
            "closed", proposal, evidence))
        self.assertFalse(mod._historical_hold_approved(
            "excluded", proposal, evidence))

    def test_final_chain_uses_proven_eligible_count_not_frozen_391(self):
        pre = {"total": 411, "eligible": 400, "already_new": 87,
               "archived": 87, "blocked": 11, "sent": 0}
        middle = {"total": 411, "eligible": 400, "already_new": 200,
                  "archived": 200, "blocked": 11, "sent": 0}
        done = {"total": 411, "eligible": 400, "already_new": 400,
                "archived": 400, "blocked": 11, "sent": 0}
        with patch.object(mod, "run",
                          side_effect=[pre, middle, middle, middle, middle, middle, done]):
            outcome = mod.run_remaining(event("BATCH_2_TO_5"))
        self.assertEqual(outcome["already_new"], 400)
        self.assertEqual(outcome["archived"], 400)
        self.assertEqual(outcome["blocked"], 11)
        mismatched = dict(done, archived=399)
        with patch.object(mod, "run",
                          side_effect=[pre, middle, middle, middle, middle, middle, mismatched]):
            with self.assertRaisesRegex(RuntimeError, "full_scope_not_verified"):
                mod.run_remaining(event("BATCH_2_TO_5"))

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

    def test_verified_batch_milestones_do_not_require_public_recipient_data(self):
        # Only anonymized counts may escape the otherwise redirected provider IO.
        initial = {"total": 411, "eligible": 391, "already_new": 92,
                   "archived": 92, "sent": 0}
        batch = {"total": 411, "eligible": 391, "installed": 90,
                 "already_new": 10, "archived": 391, "sent": 0}
        final = {"total": 411, "eligible": 391, "already_new": 391,
                 "archived": 391, "blocked": 20, "sent": 0}
        milestones = []
        with patch.object(mod, "run", side_effect=[
                initial, batch, batch, batch, batch, final]):
            completed = mod.run_remaining(
                event("BATCH_2_TO_5"),
                on_batch=lambda number, state: milestones.append(
                    (number, state["installed"], state["archived"])))
        self.assertEqual([number for number, _, _ in milestones],
                         [2, 3, 4, 5])
        self.assertEqual(completed["batches"], 4)
        self.assertEqual(completed["sent"], 0)

    def test_released_source_holds_in_first_hundred_are_idempotent(self):
        pre = {"total": 411, "eligible": 392, "already_new": 87,
               "archived": 87, "blocked": 19, "sent": 0}
        mid = {"total": 411, "eligible": 392, "already_new": 89,
               "archived": 89, "blocked": 19, "sent": 0}
        final = {"total": 411, "eligible": 392, "already_new": 392,
                 "archived": 392, "blocked": 19, "sent": 0}
        with patch.object(mod, "run",
                          side_effect=[pre, mid, mid, mid, mid, mid, final]) as execute:
            outcome = mod.run_remaining(event("BATCH_2_TO_5"))
        self.assertEqual(outcome["batches"], 5)
        self.assertEqual(outcome["already_new"], 392)
        self.assertEqual([call.args[0] for call in execute.call_args_list],
                         ["AUDIT", "BATCH_1", "BATCH_2", "BATCH_3",
                          "BATCH_4", "BATCH_5", "AUDIT"])

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
        pre = {"total": 411, "eligible": 391, "already_new": 87, "sent": 0}
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

        def fetched(client, uid):
            return {k: value for k, value in client.storage[uid].items()
                    if k != "raw"}

        with patch.object(archive.transport, "select", return_value="5"), \
             patch.object(archive.transport, "scan", side_effect=scanned) as bulk_scan, \
             patch.object(archive.transport, "uidset",
                          side_effect=lambda client: set(client.storage)), \
             patch.object(archive.transport, "fetch_message", side_effect=fetched), \
             patch.object(archive.drafts, "_raw_snapshot", side_effect=raw_snapshot), \
             patch.object(archive, "find_drafts_folder", return_value="Drafts"):
            key = snapshots.save(DID, "7", "1", raw)
            self.assertEqual(key, (DID, sha))
            self.assertEqual(snapshots.read(key), raw)
            self.assertEqual(snapshots.save(DID, "7", "1", raw), key)
            with self.assertRaisesRegex(RuntimeError, "original_conflict"):
                snapshots.save(DID, "7", "1", raw + b"bad")
            # All per-UID saves and independent reads share one validated
            # immutable archive INDEX; no repeated whole-folder MIME scan.
            self.assertEqual(bulk_scan.call_count, 1)
            store["3"]["flags"] = {b"\\DELETED"}
            with self.assertRaisesRegex(RuntimeError, "archive_flags_invalid"):
                snapshots.read(key)
            store["3"]["flags"] = {b"\\SEEN"}
            # An external archive append changes the UID set and blocks
            # stale cached state before another deletion could be approved.
            store["4"] = dict(store["3"], uid="4")
            with self.assertRaisesRegex(RuntimeError, "archive_scope_changed"):
                snapshots.read(key)
            self.assertEqual(bulk_scan.call_count, 1)
        self.assertGreaterEqual(len(clients), 3)
        self.assertTrue(all(client.closed for client in clients))

    def test_mailbox_check_trusts_bulk_scan_uid_consistency_gate(self):
        client = Mock()
        inventory = {"10": object()}
        with patch.object(mod, "find_drafts_folder", return_value="Drafts"), \
             patch.object(mod.imap, "select", return_value="7"), \
             patch.object(mod.transport, "scan", return_value=inventory) as scan, \
             patch.object(mod.imap, "uidset") as redundant, \
             patch.object(mod, "_classify", return_value={"sentinel": 1}) as classify:
            folder, validity, result = mod._check_mailbox(
                connector=lambda: client, records={})
        self.assertEqual((folder, validity), ("Drafts", "7"))
        self.assertEqual(result, {"sentinel": 1})
        scan.assert_called_once_with(client)
        classify.assert_called_once_with({}, inventory)
        redundant.assert_not_called()
        client.logout.assert_called_once()

    def test_private_source_fingerprint_detects_recipient_change(self):
        from copy import deepcopy
        records = {DID: {"category": "target", "number": 1,
                         "current": ROW, "new": NEW}}
        original = mod._digest(records)
        changed = deepcopy(records)
        changed[DID]["new"]["email"] = "info@nieuwe-zaak.example"
        self.assertNotEqual(mod._digest(changed), original)
        changed = deepcopy(records)
        changed[DID]["new"]["source_url"] = "https://nieuwe-zaak.example/"
        self.assertNotEqual(mod._digest(changed), original)



if __name__ == "__main__":
    unittest.main()
