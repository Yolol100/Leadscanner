"""Synthetic, no-API/no-mailbox safety tests for scheduled first drafts."""
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import auto_draft_new as a
import fast_website_evidence as e


def approved():
    return {"run_id": "777", "company": "Hovenier Amstel",
            "website": "https://voorbeeld.nl/",
            "email": "info@voorbeeld.nl",
            "source_url": "https://voorbeeld.nl/contact",
            "cluster": "1", "branche_meervoud": "hoveniers",
            "greeting": "Goedendag,",
            "status": "verified_website_and_email"}


def fact():
    row = approved()
    return {"record_key": "Approved:" + e._digest([
            row["company"], row["website"], row["email"]])[:24],
            "source_tab": "Approved", "source_row": "2",
            "source_sha256": e._digest([
                row["company"], row["website"], row["email"],
                row["branche_meervoud"]]),
            "company": row["company"], "website": row["website"],
            "email": row["email"], "branch": row["branche_meervoud"],
            "email_source_url": row["source_url"],
            "facts_json": json.dumps([{
                "term": "tuinontwerp",
                "excerpt": "Wij bieden tuinontwerp aan voor particulieren",
                "source_url": row["website"]}]),
            "feature_mentions_json": "[]",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "status": "verified_with_detail",
            "reason": "official_email_and_local_activity_confirmed"}


def evidence():
    f = fact()
    return {f["record_key"]: f}


def queue_row():
    return {"draft_id": "draft-" + "1" * 32,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "company": "Hovenier Amstel",
            "email": "info@voorbeeld.nl",
            "source_url": "https://voorbeeld.nl/contact",
            "subject": "Over een tuinontwerp",
            "body": "Een voorbeeld"}


class AutomaticDraftSafetyTests(unittest.TestCase):
    def test_specific_verified_service_creates_review_only_copy(self):
        result = a._eligible(approved(), evidence())
        self.assertIsNotNone(result)
        subject, body = result
        self.assertIn("tuinontwerp", subject)
        self.assertIn("tuinplan", body)
        self.assertIn("bestaande werkwijze", body)
        self.assertTrue(body.split("\n\n")[1].startswith("Een korte uitleg over "))
        self.assertNotIn("Ik zag", body)
        self.assertNotIn("Ik kwam jullie website tegen", body)
        self.assertNotIn("Ik ben Andrew van Webactueel", body)
        self.assertEqual(body.count(a.OPT_OUT), 1)
        self.assertEqual(body.split(a.OPT_OUT, 1)[0].count("?"), 1)
        self.assertLessEqual(len(body.split()), 110)
        self.assertTrue(body.endswith("Groet,\nAndrew"))

    def test_all_six_review_clusters_open_with_a_useful_idea(self):
        for cluster in ("1", "2", "3", "4", "5", "6"):
            with self.subTest(cluster=cluster):
                case = {**approved(), "cluster": cluster}
                item = a._compose(case, {"term": "tuinontwerp"})
                self.assertIsNotNone(item)
                _, body = item
                self.assertTrue(body.split("\n\n")[1].startswith("Een korte uitleg"))
                self.assertNotIn("Ik zag ", body)
                self.assertEqual(body.count(a.OPT_OUT), 1)
                self.assertEqual(body.split(a.OPT_OUT, 1)[0].count("?"), 1)
                self.assertLessEqual(len(body.split()), 110)
                self.assertTrue(body.endswith("Groet,\nAndrew"))

    def test_unverified_or_generic_sources_never_make_drafts(self):
        for status in ("verified_activity_only", "needs_manual_check"):
            with self.subTest(status=status):
                f = fact(); f["status"] = status
                self.assertIsNone(a._eligible(approved(), {f["record_key"]: f}))

    def test_wrong_cluster_for_verified_branch_is_blocked(self):
        r = approved()
        r["cluster"] = "3"  # Hoveniers are cluster 1, not restaurant sales.
        self.assertIsNone(a._eligible(r, evidence()))

    def test_cross_domain_email_is_excluded(self):
        r = approved(); r["email"] = "info@ander.nl"
        self.assertIsNone(a._eligible(r, evidence()))

    def test_source_mutation_rejected(self):
        f = fact(); f["source_sha256"] = "tampered"
        self.assertIsNone(a._eligible(approved(), {f["record_key"]: f}))

    def test_stale_source_rejected(self):
        f = fact(); f["checked_at"] = "2025-01-01T00:00:00+00:00"
        self.assertIsNone(a._eligible(approved(), {f["record_key"]: f}))

    def test_unsupported_detail_cannot_make_offer(self):
        f = fact()
        f["facts_json"] = json.dumps([{"term": "algemene diensten",
                   "excerpt": "Wij bieden algemene diensten",
                   "source_url": "https://voorbeeld.nl/"}])
        self.assertIsNone(a._eligible(approved(), {f["record_key"]: f}))

    def test_negated_excerpt_is_rejected(self):
        f = fact()
        f["facts_json"] = json.dumps([{"term": "tuinontwerp",
                   "excerpt": "Geen tuinontwerp beschikbaar",
                   "source_url": "https://voorbeeld.nl/"}])
        self.assertIsNone(a._eligible(approved(), {f["record_key"]: f}))

    def test_private_state_replay_calls_existing_imap_readback_no_append(self):
        existing = queue_row()
        state = {"auto_run_id": "777", "draft_id": "draft-" + "1"*32,
                 "identity_sha256": a._identity(approved()),
                 "source_sha256": e._digest([
                    approved()["company"], approved()["website"],
                    approved()["email"], approved()["branche_meervoud"]]),
                 "quality_status": a.DRAFT_STATUS_PREFIX + a._copy_digest(existing)}
        state_raw = [a.STATE_HEADERS, [state[h] for h in a.STATE_HEADERS]]
        q_raw = [a.DRAFT_HEADERS, [existing[h] for h in a.DRAFT_HEADERS]]
        mail = Mock(return_value={"created": 0, "existing": 1})
        with patch.object(a, "_load_latest", return_value=(
                    [approved()], evidence(), [["snapshot"]])), \
             patch.object(a, "_state_id", return_value=(1,2)), \
             patch.object(a, "_read", side_effect=[q_raw,state_raw]), \
             patch.object(a, "_write_atomic") as new_write:
            result = a.scheduled_draft_run("777", conn=Mock(), mailbox=mail)
        self.assertEqual(result["status"], "resumed")
        self.assertEqual(result["stored"], 1)
        mail.assert_called_once_with([state["draft_id"]])
        new_write.assert_not_called()

    def test_http_official_business_is_not_automatically_excluded(self):
        row = approved()
        row["website"] = "http://voorbeeld.nl/"
        row["source_url"] = "http://voorbeeld.nl/contact"
        source = fact()
        source.update(website=row["website"], email_source_url=row["source_url"],
                      source_sha256=e._digest([
                          row["company"], row["website"], row["email"],
                          row["branche_meervoud"]]))
        source["record_key"] = "Approved:" + e._digest([
            row["company"], row["website"], row["email"]])[:24]
        source["facts_json"] = json.dumps([{
            "term": "tuinontwerp", "excerpt": "Wij bieden tuinontwerp",
            "source_url": "http://voorbeeld.nl/"}])
        self.assertIsNotNone(a._eligible(row, {source["record_key"]: source}))
        self.assertEqual(a._host("https://user:secret@voorbeeld.nl/"), "")
        self.assertEqual(a._host("file:///etc/passwd"), "")
        self.assertEqual(a._host("http://voorbeeld.nl:8080/"), "")

    def test_new_eligible_offers_are_branch_specific_not_generic(self):
        cases = [
            ("logiesbedrijven", "3", "familiekamer"),
            ("horecazaken", "3", "brunch"),
            ("sportscholen", "2", "proefles"),
            ("fietsenwinkels", "3", "elektrische fiets"),
        ]
        for branch, cluster, term in cases:
            with self.subTest(branch=branch):
                row = approved()
                row["branche_meervoud"], row["cluster"] = branch, cluster
                row["company"] = "Amstel Voorbeeld"
                record = fact()
                record.update(company=row["company"], branch=branch,
                              source_sha256=e._digest([
                                row["company"], row["website"],
                                row["email"], branch]),
                              facts_json=json.dumps([{
                                "term": term, "excerpt": "Wij bieden " + term,
                                "source_url": row["website"]}]))
                record["record_key"] = "Approved:" + e._digest([
                    row["company"], row["website"], row["email"]])[:24]
                generated = a._eligible(row, {record["record_key"]: record})
                self.assertIsNotNone(generated)
                self.assertIn(term, generated[0])
                self.assertLessEqual(len(generated[1].split()), 110)

    def test_wrong_industry_fact_cannot_be_reused_even_with_valid_source_hash(self):
        row = approved()
        item = fact()
        item["facts_json"] = json.dumps([{
            "term": "familiekamer", "excerpt": "Wij hebben een familiekamer",
            "source_url": row["website"]}])
        self.assertIsNone(a._eligible(row, {item["record_key"]: item}))

    def test_tampered_existing_draft_copy_blocks_resume_before_imap(self):
        original = queue_row()
        state = {
            "auto_run_id": "777", "draft_id": original["draft_id"],
            "identity_sha256": a._identity(approved()),
            "source_sha256": e._digest([
                approved()["company"], approved()["website"],
                approved()["email"], approved()["branche_meervoud"]]),
            "quality_status": a.DRAFT_STATUS_PREFIX + a._copy_digest(original),
        }
        tampered = dict(original, body=original["body"] + " Ongecontroleerde claim.")
        state_raw = [a.STATE_HEADERS, [state[h] for h in a.STATE_HEADERS]]
        q_raw = [a.DRAFT_HEADERS, [tampered[h] for h in a.DRAFT_HEADERS]]
        mailbox = Mock()
        with patch.object(a, "_load_latest", return_value=(
                     [approved()], evidence(), [["snapshot"]])), \
             patch.object(a, "_state_id", return_value=(1, 2)), \
             patch.object(a, "_read", side_effect=[q_raw, state_raw]):
            with self.assertRaisesRegex(RuntimeError, "resume_provenance_mismatch"):
                a.scheduled_draft_run("777", conn=Mock(), mailbox=mailbox)
        mailbox.assert_not_called()

    def test_tampered_resume_cannot_open_wrong_mailbox_draft(self):
        state = {"auto_run_id": "777", "draft_id": "draft-" + "1"*32,
                 "identity_sha256": "unrelated-identity",
                 "source_sha256": "tampered",
                 "quality_status": "source_verified_human_review_required"}
        data = [a.STATE_HEADERS, [state[h] for h in a.STATE_HEADERS]]
        q = queue_row()
        queue = [a.DRAFT_HEADERS, [q[h] for h in a.DRAFT_HEADERS]]
        mailbox = Mock()
        with patch.object(a, "_load_latest", return_value=(
                    [approved()], evidence(), [["snapshot"]])), \
             patch.object(a, "_state_id", return_value=(1,2)), \
             patch.object(a, "_read", side_effect=[queue,data]):
            with self.assertRaisesRegex(RuntimeError, "resume_provenance_mismatch"):
                a.scheduled_draft_run("777", conn=Mock(), mailbox=mailbox)
        mailbox.assert_not_called()

    def test_missing_queue_id_blocks_resume(self):
        state = {"auto_run_id": "777", "draft_id": "draft-" + "1"*32,
                 "identity_sha256": a._identity(approved()),
                 "source_sha256": e._digest([
                    approved()["company"], approved()["website"],
                    approved()["email"], approved()["branche_meervoud"]]),
                 "quality_status": "source_verified_human_review_required"}
        state_raw = [a.STATE_HEADERS, [state[h] for h in a.STATE_HEADERS]]
        with patch.object(a, "_load_latest", return_value=(
                    [approved()], evidence(), [["snapshot"]])), \
             patch.object(a, "_state_id", return_value=(1,2)), \
             patch.object(a, "_read", side_effect=[[a.DRAFT_HEADERS],state_raw]):
            with self.assertRaisesRegex(RuntimeError, "queued_ids_missing"):
                a.scheduled_draft_run("777", conn=Mock(), mailbox=Mock())

    def test_no_new_run_never_touches_mailbox(self):
        mail = Mock()
        with patch.object(a, "_load_latest", return_value=([], {}, [])), \
             patch.object(a, "_state_id") as state:
            result = a.scheduled_draft_run("777", conn=Mock(), mailbox=mail)
        self.assertEqual(result["status"], "no_new_current_run")
        mail.assert_not_called()
        state.assert_not_called()

    def test_duplicate_existing_queue_is_skipped(self):
        q = queue_row()
        q_raw = [a.DRAFT_HEADERS, [q[h] for h in a.DRAFT_HEADERS]]
        with patch.object(a, "_load_latest", return_value=(
                    [approved()], evidence(), [["snapshot"]])), \
             patch.object(a, "_state_id", return_value=(1,2)), \
             patch.object(a, "_read", side_effect=[q_raw,[]]), \
             patch.object(a, "_write_atomic") as saved:
            r = a.scheduled_draft_run("777", conn=Mock(),
                   mailbox=Mock(), suppressions=lambda **kw:[])
        self.assertEqual(r["prepared"], 0)
        saved.assert_not_called()

    def test_one_new_draft_commits_atomically_then_imap(self):
        q_raw = [a.DRAFT_HEADERS]
        mock_post = Mock(status_code=200)
        mock_session = Mock()
        mock_session.post.return_value = mock_post
        created = []
        def write(*args):
            created.extend(args[-2])
        mail = Mock(return_value={"created": 1, "existing": 0})
        with patch.object(a, "_load_latest", return_value=(
                    [approved()], evidence(), [["snapshot"]])), \
             patch.object(a, "_state_id", return_value=(1,2)), \
             patch.object(a, "_read", side_effect=[q_raw, [], [["snapshot"]]]), \
             patch.object(a, "_write_atomic", side_effect=write) as saved, \
             patch.object(a, "validate_draft", side_effect=lambda d:d):
            r = a.scheduled_draft_run("777", conn=mock_session,
                        mailbox=mail, suppressions=lambda **kw:[])
        self.assertEqual(r["prepared"], 1)
        self.assertEqual(r["stored"], 1)
        self.assertEqual(r["sent"], 0)
        saved.assert_called_once()
        self.assertRegex(created[0]["draft_id"], r"^draft-[0-9a-f]{32}$")
        mail.assert_called_once_with([created[0]["draft_id"]])

    def test_invalid_run_or_missing_state_is_fail_closed(self):
        for value in ("", "main", "../", "123\n456"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    a.scheduled_draft_run(value, conn=Mock())

    def test_atomic_batch_write_and_readback(self):
        old_q = [a.DRAFT_HEADERS]
        q = queue_row()
        old_s = []
        state = {"auto_run_id": "777", "draft_id": q["draft_id"],
                 "identity_sha256": "hash", "source_sha256": "sha",
                 "quality_status": "source_verified_human_review_required"}
        expected_q = old_q + [[q[h] for h in a.DRAFT_HEADERS]]
        expected_s = [a.STATE_HEADERS, [state[h] for h in a.STATE_HEADERS]]
        client = Mock()
        client.post.return_value.status_code = 200
        with patch.object(a, "_read", side_effect=[
                old_q, old_s, expected_q, expected_s]):
            a._write_atomic(client, 1, 2, old_q, old_s, [q], [state])
        requests = client.post.call_args.kwargs["json"]["requests"]
        self.assertEqual(len(requests), 3)
        self.assertEqual(requests[-1]["appendCells"]["sheetId"], 2)
        self.assertEqual(requests[-2]["appendCells"]["sheetId"], 1)

    def test_atomic_bad_readback_blocks_mailbox(self):
        old_q = [a.DRAFT_HEADERS]
        state = {"auto_run_id":"777","draft_id":"draft-"+"2"*32,
                 "identity_sha256":"a","source_sha256":"b",
                 "quality_status":"source_verified_human_review_required"}
        client = Mock()
        client.post.return_value.status_code = 200
        with patch.object(a, "_read", side_effect=[
                old_q, [], [["wrong"]], [["wrong"]]]):
            with self.assertRaisesRegex(RuntimeError, "readback"):
                a._write_atomic(client, 1, 2, old_q, [], [queue_row()], [state])

    def test_empty_sheet_values_response_is_valid_for_new_state_only(self):
        session = Mock()
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {
            "range": "AutoDraftState!A1:E1000", "majorDimension": "ROWS"}
        self.assertEqual(a._read(session, a.DRAFT_QUEUE_ID, "AutoDraftState!A:E"), [])
        with self.assertRaisesRegex(RuntimeError, "missing_private_headers"):
            a._parse_table([], a.DRAFT_HEADERS)

    def test_malformed_sheet_response_still_fails_closed(self):
        session = Mock()
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {"values": "not-an-array"}
        with self.assertRaisesRegex(RuntimeError, "source_shape_invalid"):
            a._read(session, a.DRAFT_QUEUE_ID, "AutoDraftState!A:E")

    def test_live_candidate_quality_audit_is_read_only_and_anonymous(self):
        row = approved()
        site = fact()
        approved_rows = [list(a.APPROVED_HEADERS),
                         [row[h] for h in a.APPROVED_HEADERS]]
        evidence_rows = [list(a.EVIDENCE_HEADERS),
                         [str(site.get(h, "")) for h in a.EVIDENCE_HEADERS]]
        conn = Mock()
        with patch.object(a, "_read", side_effect=[
                  approved_rows, evidence_rows]) as reads, \
             patch.object(a, "create_batch_from_queue") as mailbox:
            result = a.audit_existing_sources(conn=conn)
        self.assertEqual(result["status"], "read_only_proof_audit")
        self.assertEqual(result["approved_source_rows"], 1)
        self.assertEqual(result["content_candidates_before_dedupe"], 1)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["mailbox_writes"], 0)
        self.assertEqual(reads.call_count, 2)
        conn.post.assert_not_called()
        mailbox.assert_not_called()
        self.assertNotIn("Hovenier", str(result))
        self.assertNotIn("@", str(result))

    def test_read_only_quality_audit_marks_no_unsupported_candidates(self):
        row = approved()
        content = [list(a.APPROVED_HEADERS),
                   [row[h] for h in a.APPROVED_HEADERS]]
        with patch.object(a, "_read", side_effect=[
                  content, [list(a.EVIDENCE_HEADERS)]]):
            result = a.audit_existing_sources(conn=Mock())
        self.assertEqual(result["content_candidates_before_dedupe"], 0)
        self.assertEqual(result["skipped_for_evidence_or_copy"], 1)

    def test_live_preflight_only_initializes_private_state_metadata(self):
        client = Mock()
        client.post.return_value.status_code = 200
        with patch.object(a, "_state_id", return_value=(12,13)), \
             patch.object(a, "_read", side_effect=[
                [list(a.APPROVED_HEADERS)], [list(a.DRAFT_HEADERS)], [],
                [list(a.STATE_HEADERS)]]) as reads, \
             patch.object(a, "create_batch_from_queue") as imap:
            result = a.private_preflight(conn=client)
        self.assertEqual(result["status"], "private_state_ready")
        self.assertEqual(result["mailbox_writes"], 0)
        self.assertEqual(result["review450_rows_touched"], 0)
        self.assertEqual(reads.call_count, 4)
        self.assertEqual(client.post.call_count, 1)
        tx = client.post.call_args.kwargs["json"]["requests"]
        self.assertEqual(len(tx), 1)
        self.assertIn("updateCells", tx[0])
        imap.assert_not_called()

    def test_preflight_fails_on_unexpected_existing_state(self):
        with patch.object(a, "_state_id", return_value=(12,13)), \
             patch.object(a, "_read", side_effect=[
                [list(a.APPROVED_HEADERS)], [list(a.DRAFT_HEADERS)], [["wrong"]]]), \
             patch.object(a, "create_batch_from_queue") as imap:
            with self.assertRaisesRegex(RuntimeError, "headers_changed"):
                a.private_preflight(conn=Mock())
        imap.assert_not_called()

    def test_only_allowlisted_private_diagnostic_codes_reach_ci(self):
        from contextlib import redirect_stdout
        from io import StringIO
        import sys
        for cause,expected in [
            ("autodraft_preflight_header_write_failed",
             "autodraft_preflight_header_write_failed"),
            ("PII test@example.invalid on company website",
             "unclassified_failure"),
        ]:
            with self.subTest(cause=expected), patch.object(
                  a, "private_preflight", side_effect=RuntimeError(cause)), \
                 patch.object(sys, "argv", ["script.py","--preflight"]), \
                 redirect_stdout(StringIO()) as capture:
                code = a.main()
            self.assertEqual(code, 1)
            info = json.loads(capture.getvalue())
            self.assertEqual(info["reason"], expected)
            self.assertNotIn("test@example.invalid", capture.getvalue())

    def test_mailbox_preflight_uses_real_imaplib_readonly_select(self):
        # Restricted mock: an imaginary IMAP4.examine() method cannot pass.
        client = Mock(spec=["select", "logout", "append", "store", "expunge"])
        self.assertFalse(hasattr(client, "examine"))
        client.select.return_value = ("OK", [b"0"])
        with patch("myhost_draft.connect_imap", return_value=client), \
             patch("myhost_draft.find_drafts_folder", return_value="Drafts"):
            result = a.mailbox_readonly_preflight()
        self.assertEqual(result["status"], "imap_drafts_examined_readonly")
        self.assertEqual(result["mailbox_writes"], 0)
        self.assertEqual(result["sent"], 0)
        client.select.assert_called_once_with('"Drafts"', readonly=True)
        client.append.assert_not_called()
        client.store.assert_not_called()
        client.expunge.assert_not_called()
        client.logout.assert_called_once()

    def test_bad_readonly_select_blocks_without_any_mailbox_mutation(self):
        client = Mock(spec=["select", "logout", "append", "store", "expunge"])
        client.select.return_value = ("NO", [b"permission denied"])
        with patch("myhost_draft.connect_imap", return_value=client), \
             patch("myhost_draft.find_drafts_folder", return_value="Drafts"):
            with self.assertRaisesRegex(RuntimeError, "readonly_drafts_folder_unavailable"):
                a.mailbox_readonly_preflight()
        client.select.assert_called_once_with('"Drafts"', readonly=True)
        client.append.assert_not_called()
        client.store.assert_not_called()
        client.logout.assert_called_once()

    def test_live_canary_secrets_are_scoped_to_read_only_check(self):
        source = (Path(__file__).resolve().parents[1] /
                  ".github/workflows/fresh-leads.yml").read_text()
        preflight = source.split("  auto_draft_preflight:", 1)[1]
        self.assertIn("scripts/auto_draft_new.py --mailbox-preflight", preflight)
        self.assertIn("IMAP EXAMINE", preflight)
        self.assertIn("OUTREACH_MAIL_PASSWORD", preflight)
        self.assertNotIn("append", preflight.lower())
        self.assertNotIn("smtp", preflight.lower())

    def test_disabled_scheduled_first_draft_job_is_absent(self):
        path = Path(__file__).resolve().parents[1] / ".github/workflows/fresh-leads.yml"
        workflow = path.read_text()
        triggers = workflow.split("\npermissions:", 1)[0]
        self.assertNotIn("\n  schedule:", triggers)
        self.assertNotIn("\n  auto_first_drafts:", workflow)
        preflight = workflow.split("\n  auto_draft_preflight:", 1)[1]
        self.assertIn("github.event_name == 'push'", preflight)
        self.assertIn("scripts/auto_draft_new.py --mailbox-preflight", preflight)
        self.assertNotIn("smtp", preflight.lower())
        self.assertNotIn("LEADS_IMPROVE450", preflight)


if __name__ == "__main__":
    unittest.main()
