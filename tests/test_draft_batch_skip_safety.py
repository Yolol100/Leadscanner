"""Batch isolation: never draft rejected candidates, never hide shared-system failures."""
import unittest
from email import policy
from email.parser import BytesParser
from unittest.mock import Mock, patch

import draft_queue_readonly as queue
import myhost_draft as drafts
from test_batch_imap_in_memory import InMemoryIMAP, make_rows


def fixture(count=100):
    data = make_rows(count)
    response = Mock(status_code=200)
    response.json.return_value = {
        "values": [queue.HEADERS] + [[r.get(h, "") for h in queue.HEADERS] for r in data]
    }
    session = Mock()
    session.get.return_value = response
    return data, session


class BatchSkipSafetyTests(unittest.TestCase):
    def test_hundred_candidates_skip_local_rejections_and_exactly_read_back_survivors(self):
        rows, session = fixture()
        values = session.get.return_value.json.return_value["values"]
        # Five invalid; real per-row validators decide what may be ignored.
        values[3][3] = "not-an-email"
        values[4][6] = "Hoi {{aanhef}}, niet ingevuld"
        values[5][4] = "http://127.0.0.1/private"
        values[6][5] = "Subject\nBcc: extra@example.org"
        values[7][6] = "woord " * 111
        # Three historically suppressed: HMAC/registry decisions are not bypassed.
        blocked = {8, 9, 10}
        # Three duplicates of accepted rows, by name, email, and website.
        values[12][2] = values[11][2]
        values[13][3] = values[11][3]
        values[14][4] = values[11][4]
        client = InMemoryIMAP()
        def historical(candidate, _registry):
            if candidate["name_hint"] in {"Fictief Hoveniersbedrijf " + str(i) for i in blocked}:
                return {"matched_by": ["historical_v2_email"]}
            return None
        ids = [row["draft_id"] for row in rows]
        with patch("draft_queue_readonly.authorized_session", return_value=session), \
             patch("draft_queue_readonly.is_public_http_url", side_effect=lambda s: "127.0.0.1" not in s), \
             patch("myhost_draft.load_suppressions", return_value=[{"status": "complete_historical_state"}]) as registry, \
             patch("myhost_draft.match_candidate", side_effect=historical), \
             patch("myhost_draft.connect_imap", return_value=client) as connect, \
             patch("myhost_draft.time.sleep", return_value=None):
            first = drafts.create_batch_from_queue(ids)
            self.assertEqual(first, {
                "total": 100, "created": 89, "existing": 0,
                "skipped_invalid": 5, "skipped_suppressed": 3,
                "skipped_duplicate": 3,
            })
            second = drafts.create_batch_from_queue(ids)
        self.assertEqual(second, {
            "total": 100, "created": 0, "existing": 89,
            "skipped_invalid": 5, "skipped_suppressed": 3,
            "skipped_duplicate": 3,
        })
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(registry.call_count, 2)
        self.assertEqual(connect.call_count, 2)
        self.assertEqual(client.append_attempts, 89)
        self.assertEqual(client.select_count, 2)
        self.assertEqual(client.logout_count, 2)
        self.assertEqual(len(client.messages), 89)
        self.assertEqual(len({BytesParser(policy=policy.default).parsebytes(msg)[drafts.DRAFT_HEADER]
                              for msg, _ in client.messages}), 89)
        self.assertTrue(all(flags == b"\\Draft" for _, flags in client.messages))
        print("BATCH100_SKIP_SIM=green requested=100 stored=89 skipped=11 retried_existing=89 sent=0")

    def test_loader_default_strict_and_batch_only_skips_known_row_errors(self):
        rows, session = fixture(3)
        data = session.get.return_value.json.return_value["values"]
        data[2][3] = "not-an-email"
        ids = [r["draft_id"] for r in rows]
        with patch("draft_queue_readonly.is_public_http_url", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "draft_queue_email_invalid"):
                queue.load_drafts(ids, session)
            good = queue.load_drafts(ids, session, skip_invalid=True)
        self.assertEqual([r["draft_id"] for r in good], [ids[0], ids[2]])
        self.assertEqual(session.get.call_count, 2)

    def test_missing_duplicate_or_bad_id_still_fatal_even_in_batch_mode(self):
        rows, session = fixture(3)
        ids = [r["draft_id"] for r in rows]
        data = session.get.return_value.json.return_value["values"]
        with patch("draft_queue_readonly.is_public_http_url", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "draft_queue_id_missing_or_duplicate"):
                queue.load_drafts(ids + ["draft-" + "a" * 32], session, skip_invalid=True)
            data.append(list(data[2]))
            with self.assertRaisesRegex(RuntimeError, "draft_queue_id_missing_or_duplicate"):
                queue.load_drafts(ids, session, skip_invalid=True)
            data.pop()
            data[2][0] = "corrupt-id"
            with self.assertRaisesRegex(RuntimeError, "draft_queue_id_missing_or_duplicate"):
                queue.load_drafts(ids, session, skip_invalid=True)

    def test_broken_registry_and_suppression_computation_never_reach_imap(self):
        data = make_rows(3)
        for reason in ("offline", "hmac_vault_incomplete"):
            with self.subTest(reason=reason), \
                 patch("myhost_draft.load_drafts", return_value=data), \
                 patch("myhost_draft.load_suppressions", side_effect=RuntimeError(reason)), \
                 patch("myhost_draft.connect_imap") as imap:
                with self.assertRaisesRegex(RuntimeError, "batch_preflight_unavailable"):
                    drafts.create_batch_from_queue([r["draft_id"] for r in data])
                imap.assert_not_called()
        with patch("myhost_draft.load_drafts", return_value=data), \
             patch("myhost_draft.load_suppressions", return_value=[{"status": "historical_v2"}]), \
             patch("myhost_draft.match_candidate", side_effect=RuntimeError("corrupt HMAC key")), \
             patch("myhost_draft.connect_imap") as imap:
            with self.assertRaisesRegex(RuntimeError, "batch_preflight_unavailable"):
                drafts.create_batch_from_queue([r["draft_id"] for r in data])
            imap.assert_not_called()

    def test_all_suppressed_requires_no_imap_connection(self):
        data = make_rows(100)
        with patch("myhost_draft.load_drafts", return_value=data), \
             patch("myhost_draft.load_suppressions", return_value=[{"status": "historical_v2"}]), \
             patch("myhost_draft.match_candidate", return_value={"matched_by": ["hmac"]}), \
             patch("myhost_draft.connect_imap") as imap:
            result = drafts.create_batch_from_queue([r["draft_id"] for r in data])
        self.assertEqual(result, {
            "total": 100, "created": 0, "existing": 0,
            "skipped_invalid": 0, "skipped_suppressed": 100,
            "skipped_duplicate": 0,
        })
        imap.assert_not_called()

    def test_imap_failure_stops_and_retry_remains_idempotent(self):
        rows = make_rows(12)
        client = InMemoryIMAP()
        client.fail_at = 5
        with patch("myhost_draft.load_drafts", return_value=rows), \
             patch("myhost_draft.load_suppressions", return_value=[]), \
             patch("myhost_draft.connect_imap", return_value=client), \
             patch("myhost_draft.time.sleep", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "imap_append_failed"):
                drafts.create_batch_from_queue([r["draft_id"] for r in rows])
            self.assertEqual(len(client.messages), 4)
            client.fail_at = None
            result = drafts.create_batch_from_queue([r["draft_id"] for r in rows])
        self.assertEqual(result, {
            "total": 12, "created": 8, "existing": 4,
            "skipped_invalid": 0, "skipped_suppressed": 0,
            "skipped_duplicate": 0,
        })
        self.assertEqual(len(client.messages), 12)


if __name__ == "__main__":
    unittest.main()
