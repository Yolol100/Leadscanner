"""Private candidate handoff + 100-draft limits; all test data is fictional."""
import unittest
from unittest.mock import Mock, patch

from private_candidate_handoff import COLUMNS, MAX_CANDIDATES, store_candidates
from draft_queue_readonly import HEADERS, load_drafts
from draft_trigger import resolve_batch_request
from myhost_draft import create_batch_from_queue


def candidates(n):
    return [
        {"company": "Fictief Hoveniersbedrijf " + str(i),
         "website_hint": "https://fictieve-hovenier-" + str(i) + ".nl/",
         "status": "requires_official_site_verification"}
        for i in range(1, n + 1)
    ]


def drafts(n):
    return [
        {"draft_id": "draft-" + f"{i:032x}",
         "company": "Fictief Hoveniersbedrijf " + str(i),
         "email": "info@fictieve-hovenier-" + str(i) + ".nl",
         "source_url": "https://fictieve-hovenier-" + str(i) + ".nl/contact/",
         "created_at": "2026-10-14T20:00:00+02:00",
         "subject": "Vraag over Fictief Hoveniersbedrijf " + str(i),
         "body": "Goedendag,\n\nIk heb een vraag over jullie website.\n\nWebactueel"}
        for i in range(1, n + 1)
    ]


class PrivateCandidateHandoffTests(unittest.TestCase):
    def test_hundred_candidates_one_write_one_readback_no_public_details(self):
        data = candidates(100)
        expected = [list(COLUMNS)] + [
            ["38612345678", row["company"], row["website_hint"], row["status"]]
            for row in data
        ]
        session = Mock()
        session.post.return_value.status_code = 200
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {"values": expected}
        n = store_candidates(data, run_id="38612345678", session=session)
        self.assertEqual(n, 100)
        session.post.assert_called_once()
        session.get.assert_called_once()
        body = session.post.call_args.kwargs["json"]
        self.assertEqual(len(body["requests"][0]["updateCells"]["rows"]), 101)
        self.assertEqual(
            body["requests"][0]["updateCells"]["rows"][100]["values"][1]
                ["userEnteredValue"]["stringValue"],
            data[-1]["company"]
        )
        self.assertNotIn("info@", str(body))
        self.assertNotIn("draft-", str(body))

    def test_empty_search_clears_old_candidates(self):
        session = Mock()
        session.post.return_value.status_code = 200
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {"values": [list(COLUMNS)]}
        self.assertEqual(store_candidates([], run_id="38612345678", session=session), 0)
        rows = session.post.call_args.kwargs["json"]["requests"][0]["updateCells"]["rows"]
        self.assertEqual(len(rows), 101)
        self.assertEqual(rows[1]["values"], [{}, {}, {}, {}])

    def test_handoff_rejects_invalid_unverified_or_excess_candidates(self):
        session = Mock()
        bad = candidates(1)
        bad[0]["website_hint"] = "http://localhost/"
        with self.assertRaises(RuntimeError):
            store_candidates(bad, run_id="38612345678", session=session)
        bad = candidates(1)
        bad[0]["status"] = "verified"
        with self.assertRaises(RuntimeError):
            store_candidates(bad, run_id="38612345678", session=session)
        with self.assertRaises(RuntimeError):
            store_candidates(candidates(101), run_id="38612345678", session=session)
        session.post.assert_not_called()

    def test_failed_google_readback_blocks_success(self):
        session = Mock()
        session.post.return_value.status_code = 200
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {"values": [list(COLUMNS)]}
        with self.assertRaises(RuntimeError):
            store_candidates(candidates(1), run_id="38612345678", session=session)


class HundredDraftBatchTests(unittest.TestCase):
    def test_read_hundred_drafts_in_one_private_sheets_request(self):
        data = drafts(100)
        session = Mock()
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {
            "values": [HEADERS] + [[row[key] for key in HEADERS] for row in data]
        }
        with patch("draft_queue_readonly.is_public_http_url", return_value=True):
            result = load_drafts([row["draft_id"] for row in data], session)
        self.assertEqual(len(result), 100)
        session.get.assert_called_once()

    def test_hundred_drafts_share_single_registry_and_imap_session(self):
        data = drafts(100)
        client = Mock()
        with patch("myhost_draft.load_drafts", return_value=data) as loader, \
             patch("myhost_draft.load_suppressions", return_value=[]) as registry, \
             patch("myhost_draft.match_candidate", return_value=None), \
             patch("myhost_draft.connect_imap", return_value=client) as connector, \
             patch("myhost_draft.find_drafts_folder", return_value="Drafts"), \
             patch("myhost_draft.save_draft", return_value="created") as writer:
            output = create_batch_from_queue([row["draft_id"] for row in data])
        self.assertEqual(output, {"total": 100, "created": 100, "existing": 0})
        loader.assert_called_once()
        registry.assert_called_once()
        connector.assert_called_once()
        self.assertEqual(writer.call_count, 100)
        client.logout.assert_called_once()

    def test_hundred_valid_ids_but_hundred_and_one_blocked(self):
        ids = [row["draft_id"] for row in drafts(100)]
        event = {"issue": {"number": 1659}, "comment": {
            "author_association": "OWNER",
            "body": "LEADS_DRAFT_BATCH_ONLY: " + ",".join(ids)
        }}
        self.assertEqual(resolve_batch_request("issue_comment", event, {}), ids)
        event["comment"]["body"] += ",draft-" + "f" * 32
        with self.assertRaises(ValueError):
            resolve_batch_request("issue_comment", event, {})
        with self.assertRaises(RuntimeError):
            load_drafts(ids + ["draft-" + "f" * 32], Mock())


if __name__ == "__main__":
    unittest.main()
