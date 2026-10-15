"""End-to-end offline first-draft rehearsal: private Sheets -> IMAP Drafts.

Uses real parsing, queue integrity, MIME, IMAP APPEND, exact fetch/readback.
Only the two external transports are replaced by in-memory fakes. No network.
"""
import unittest
from urllib.parse import unquote
from unittest.mock import Mock, patch

import auto_draft_new as a
import draft_queue_readonly as queue
import myhost_draft
import fast_website_evidence as evidence
from test_auto_draft_new import approved, fact
from test_batch_imap_in_memory import InMemoryIMAP


class SheetMemory:
    def __init__(self):
        row = approved()
        proof = fact()
        self.data = {
            "Approved": [list(a.APPROVED_HEADERS), [row[k] for k in a.APPROVED_HEADERS]],
            "WebsiteEvidence": [list(a.EVIDENCE_HEADERS),
                                [proof.get(k, "") for k in a.EVIDENCE_HEADERS]],
            "LeadHistory": [list(a.HISTORY_COLS), [
                row["run_id"], row["company"], row["website"], row["email"],
                row["source_url"], "verified_lead", "", "2026-10-15T12:00:00Z"]],
            "DraftQueue": [a.DRAFT_HEADERS],
            "AutoDraftState": [a.STATE_HEADERS],
        }
        self.atomic_commits = 0
        self.client = Mock()
        self.client.get.side_effect = self.get
        self.client.post.side_effect = self.post

    @staticmethod
    def _values(rows):
        return [[cell.get("userEnteredValue", {}).get("stringValue", "")
                 for cell in row["values"]] for row in rows]

    def get(self, url, **_kwargs):
        result = Mock(status_code=200)
        if "?fields=sheets(properties(" in url:
            result.json.return_value = {"sheets": [
                {"properties": {"title": "DraftQueue", "sheetId": 100}},
                {"properties": {"title": "AutoDraftState", "sheetId": 101}}]}
        elif "/values/" in url:
            tail = unquote(url.split("/values/", 1)[1])
            name = tail.split("!", 1)[0].strip("'")
            if name not in self.data:
                raise AssertionError("unknown private range")
            result.json.return_value = {"values": [r[:] for r in self.data[name]]}
        else:
            raise AssertionError("unapproved API")
        return result

    def post(self, url, **kwargs):
        if not url.endswith(":batchUpdate"):
            raise AssertionError("no writes outside one Sheets transaction")
        operations = kwargs["json"]["requests"]
        # The first-draft transaction adds 1 queue row and matching private
        # AutoDraftState row, or fails atomically.
        if len(operations) != 2:
            raise AssertionError("wrong first-draft transaction shape")
        pending = {name: [r[:] for r in value] for name, value in self.data.items()}
        for item in operations:
            append = item["appendCells"]
            title = {100: "DraftQueue", 101: "AutoDraftState"}[append["sheetId"]]
            pending[title] += self._values(append["rows"])
        self.data = pending
        self.atomic_commits += 1
        return Mock(status_code=200)


class AutoFirstDraftE2ETests(unittest.TestCase):
    def test_full_first_draft_and_resume_exact_imap_readback(self):
        private = SheetMemory()
        mailbox = InMemoryIMAP()

        def write(ids):
            def read(ids, skip_invalid=True):
                return queue.load_drafts(ids, session=private.client,
                                         skip_invalid=skip_invalid)
            with patch.object(myhost_draft, "load_drafts", side_effect=read), \
                 patch.object(queue, "is_public_http_url", return_value=True), \
                 patch.object(myhost_draft, "load_suppressions", return_value=[]), \
                 patch.object(myhost_draft, "connect_imap", return_value=mailbox), \
                 patch.object(myhost_draft.time, "sleep", return_value=None):
                return myhost_draft.create_batch_from_queue(ids)

        with patch.object(queue, "is_public_http_url", return_value=True):
            out = a.scheduled_draft_run(
                "777", conn=private.client, mailbox=write,
                suppressions=lambda session: [])
        self.assertEqual((out["prepared"], out["stored"], out["sent"]), (1, 1, 0))
        self.assertEqual(len(private.data["DraftQueue"]), 2)
        self.assertEqual(len(private.data["AutoDraftState"]), 2)
        self.assertEqual(private.atomic_commits, 1)
        self.assertEqual(mailbox.append_attempts, 1)
        self.assertEqual(len(mailbox.messages), 1)
        self.assertEqual(mailbox.messages[0][1], b"\\Draft")
        self.assertNotIn("Review450", private.data)

        with patch.object(queue, "is_public_http_url", return_value=True):
            again = a.scheduled_draft_run(
                "777", conn=private.client, mailbox=write,
                suppressions=lambda session: [])
        self.assertEqual(again["status"], "resumed")
        self.assertEqual(again["stored"], 1)
        self.assertEqual(mailbox.append_attempts, 1)
        self.assertEqual(private.atomic_commits, 1)

    def test_mailbox_failure_after_private_transaction_is_idempotent(self):
        private = SheetMemory()
        mailbox = InMemoryIMAP()
        mailbox.fail_at = 1

        def write(ids):
            with patch.object(myhost_draft, "load_drafts",
                              side_effect=lambda ids, skip_invalid=True:
                              queue.load_drafts(ids, session=private.client,
                                                skip_invalid=skip_invalid)), \
                 patch.object(queue, "is_public_http_url", return_value=True), \
                 patch.object(myhost_draft, "load_suppressions", return_value=[]), \
                 patch.object(myhost_draft, "connect_imap", return_value=mailbox):
                return myhost_draft.create_batch_from_queue(ids)

        with patch.object(queue, "is_public_http_url", return_value=True):
            with self.assertRaises(RuntimeError):
                a.scheduled_draft_run(
                    "777", conn=private.client, mailbox=write,
                    suppressions=lambda session: [])
        self.assertEqual(private.atomic_commits, 1)
        self.assertEqual(len(private.data["DraftQueue"]), 2)
        self.assertEqual(mailbox.messages, [])
        mailbox.fail_at = None
        with patch.object(queue, "is_public_http_url", return_value=True):
            resumed = a.scheduled_draft_run(
                "777", conn=private.client, mailbox=write,
                suppressions=lambda session: [])
        self.assertEqual((resumed["stored"], resumed["sent"]), (1, 0))
        self.assertEqual(private.atomic_commits, 1)
        self.assertEqual(len(mailbox.messages), 1)


if __name__ == "__main__":
    unittest.main()
