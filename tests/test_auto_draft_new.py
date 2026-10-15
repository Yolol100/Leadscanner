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
        self.assertIn("tuinontwerp", body)
        self.assertIn("bestaande werkwijze", body)
        self.assertNotIn("Ik kwam jullie website tegen", body)
        self.assertNotIn("Ik ben Andrew van Webactueel", body)
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
        state = {"auto_run_id": "777", "draft_id": "draft-" + "1"*32,
                 "identity_sha256": a._identity(approved()),
                 "source_sha256": e._digest([
                    approved()["company"], approved()["website"],
                    approved()["email"], approved()["branche_meervoud"]]),
                 "quality_status": "source_verified_human_review_required"}
        existing = queue_row()
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

    def test_schedule_is_bound_to_main_and_no_smtp(self):
        path = Path(__file__).resolve().parents[1] / ".github/workflows/fresh-leads.yml"
        workflow = path.read_text()
        section = workflow.split("  auto_first_drafts:",1)[1]
        self.assertIn("github.event_name == 'schedule'", section)
        self.assertIn("github.ref == 'refs/heads/main'", section)
        self.assertIn("OUTREACH_IMAP_PORT", section)
        self.assertIn("scripts/auto_draft_new.py", section)
        self.assertNotIn("smtp", section.lower())
        self.assertNotIn("LEADS_IMPROVE450", section)


if __name__ == "__main__":
    unittest.main()
