"""Fictional 50-draft regression; no real leads, IMAP connection or sending."""
import unittest
from unittest.mock import Mock, patch

from draft_queue_readonly import HEADERS, load_drafts
from draft_trigger import resolve_batch_request
from myhost_draft import create_batch_from_queue

PREFIX = "draft-"


def rows(n):
    return [
        {
            "draft_id": PREFIX + f"{index:032x}",
            "created_at": "2026-10-14T20:00:00+02:00",
            "company": f"Fictief Schildersbedrijf {index}",
            "email": f"info@fictief-{index}.nl",
            "source_url": f"https://fictief-{index}.nl/contact",
            "subject": f"Vraag over Fictief Schildersbedrijf {index}",
            "body": "Goedendag, een korte vraag over websites en vindbaarheid.\n\nWebactueel",
        }
        for index in range(1, n + 1)
    ]


class BatchOnlyTests(unittest.TestCase):
    def test_read_50_private_drafts_in_one_google_call(self):
        data = rows(50)
        sess = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"values": [HEADERS] + [
            [row[key] for key in HEADERS] for row in data
        ]}
        sess.get.return_value = response
        with patch("draft_queue_readonly.is_public_http_url", return_value=True):
            got = load_drafts([row["draft_id"] for row in data], sess)
        self.assertEqual(len(got), 50)
        sess.get.assert_called_once()

    def test_50_drafts_share_one_registry_and_imap_login(self):
        data = rows(50)
        client = Mock()
        with patch("myhost_draft.load_drafts", return_value=data) as fetch, \\
             patch("myhost_draft.load_suppressions", return_value=[]) as registry, \\
             patch("myhost_draft.match_candidate", return_value=None), \\
             patch("myhost_draft.connect_imap", return_value=client) as connect, \\
             patch("myhost_draft.find_drafts_folder", return_value="Drafts"), \\
             patch("myhost_draft.save_draft", return_value="created") as saved:
            result = create_batch_from_queue([row["draft_id"] for row in data])
        self.assertEqual(result, {"total": 50, "created": 50, "existing": 0})
        fetch.assert_called_once()
        registry.assert_called_once()
        connect.assert_called_once()
        self.assertEqual(saved.call_count, 50)
        client.logout.assert_called_once()

    def test_batch_rejects_already_contacted_before_mailbox_login(self):
        with patch("myhost_draft.load_drafts", return_value=rows(3)), \\
             patch("myhost_draft.load_suppressions", return_value=[{"status": "opt_out"}]), \\
             patch("myhost_draft.match_candidate", return_value={"registry_status": "opt_out"}), \\
             patch("myhost_draft.connect_imap") as imap:
            with self.assertRaises(RuntimeError):
                create_batch_from_queue(["draft-" + f"{i:032x}" for i in (1, 2, 3)])
            imap.assert_not_called()

    def test_batch_rejects_second_same_company(self):
        data = rows(2)
        data[1]["company"] = data[0]["company"]
        with patch("myhost_draft.load_drafts", return_value=data), \\
             patch("myhost_draft.load_suppressions", return_value=[]), \\
             patch("myhost_draft.match_candidate", return_value=None), \\
             patch("myhost_draft.connect_imap") as imap:
            with self.assertRaises(RuntimeError):
                create_batch_from_queue([row["draft_id"] for row in data])
            imap.assert_not_called()

    def test_batch_rejects_broken_registry(self):
        with patch("myhost_draft.load_drafts", return_value=rows(2)), \\
             patch("myhost_draft.load_suppressions", side_effect=RuntimeError("offline")), \\
             patch("myhost_draft.connect_imap") as imap:
            with self.assertRaises(RuntimeError):
                create_batch_from_queue(["draft-" + f"{i:032x}" for i in (1, 2)])
            imap.assert_not_called()

    def test_batch_limits_and_untrusted_payload(self):
        ids = [PREFIX + f"{index:032x}" for index in range(1, 51)]
        authorized = {"issue": {"number": 1659},
                      "comment": {"author_association": "OWNER",
                                  "body": "LEADS_DRAFT_BATCH_ONLY: " + ",".join(ids)}}
        self.assertEqual(resolve_batch_request("issue_comment", authorized, {}), ids)
        with self.assertRaises(ValueError):
            resolve_batch_request("issue_comment", {
                **authorized,
                "comment": {"author_association": "NONE",
                            "body": authorized["comment"]["body"]}
            }, {})
        with self.assertRaises(ValueError):
            resolve_batch_request("issue_comment", {
                **authorized,
                "comment": {"author_association": "OWNER",
                            "body": authorized["comment"]["body"] + ",info@fictief.nl"}
            }, {})
        with self.assertRaises(ValueError):
            resolve_batch_request("issue_comment", {
                **authorized,
                "comment": {"author_association": "OWNER",
                            "body": authorized["comment"]["body"] + "," + ids[0]}
            }, {})
        with self.assertRaises(RuntimeError):
            load_drafts(ids + [PREFIX + "f" * 32], Mock())


if __name__ == "__main__":
    unittest.main()
