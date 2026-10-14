"""Fully in-memory IMAP simulation: 50 draft APPENDs, exact reads and retry."""
import time
import unittest
from email import policy
from email.parser import BytesParser
from unittest.mock import patch

import myhost_draft as draft


def make_rows(count=50):
    return [{
        "draft_id": "draft-" + format(index, "032x"),
        "company": "Fictief Hoveniersbedrijf " + str(index),
        "email": "info@fictief-" + str(index) + ".nl",
        "source_url": "https://fictief-" + str(index) + ".nl/contact",
        "subject": "Vraag over Fictief Hoveniersbedrijf " + str(index),
        "body": "Goedendag,\n\nKorte fictieve testmail.\n\nWebactueel",
    } for index in range(1, count + 1)]


class InMemoryIMAP:
    def __init__(self):
        self.messages = []
        self.fail_at = None
        self.append_attempts = 0
        self.logout_count = 0

    def list(self):
        return "OK", [b'(\\HasNoChildren \\Drafts) "/" "Drafts"']

    def select(self, folder, readonly=True):
        if not readonly or folder != '"Drafts"':
            raise AssertionError("Unexpected folder or unsafe write select")
        return "OK", [str(len(self.messages)).encode()]

    def search(self, charset, *criteria):
        target = str(criteria[-1]).strip('"')
        ids = []
        for pos, (raw, flags) in enumerate(self.messages, 1):
            message = BytesParser(policy=policy.default).parsebytes(raw)
            if message.get(draft.DRAFT_HEADER) == target:
                ids.append(str(pos).encode())
        return "OK", [b" ".join(ids)]

    def fetch(self, seq, query):
        raw, flags = self.messages[int(seq) - 1]
        return "OK", [(b"1 (FLAGS (" + flags + b") RFC822 {123}", raw), b")"]

    def append(self, folder, flags, date_time, raw):
        self.append_attempts += 1
        if self.fail_at == self.append_attempts:
            return "NO", [b"simulated failure"]
        if folder != '"Drafts"' or flags != "(\\Draft)":
            raise AssertionError("Not a Drafts APPEND")
        self.messages.append((raw, b"\\Draft"))
        return "OK", [b"APPENDUID 1 1"]

    def logout(self):
        self.logout_count += 1


class BatchIMAPSimulation(unittest.TestCase):
    def test_50_individual_drafts_read_back_in_one_session(self):
        rows = make_rows()
        client = InMemoryIMAP()
        start = time.monotonic()
        with patch("myhost_draft.load_drafts", return_value=rows), \
             patch("myhost_draft.load_suppressions", return_value=[]), \
             patch("myhost_draft.connect_imap", return_value=client), \
             patch("myhost_draft.time.sleep", return_value=None):
            outcome = draft.create_batch_from_queue([r["draft_id"] for r in rows])
        seconds = time.monotonic() - start
        self.assertEqual(outcome, {"total": 50, "created": 50, "existing": 0})
        self.assertEqual(len(client.messages), 50)
        self.assertEqual(client.append_attempts, 50)
        self.assertEqual(client.logout_count, 1)
        self.assertEqual(
            len({BytesParser(policy=policy.default).parsebytes(raw)[draft.DRAFT_HEADER]
                 for raw, _ in client.messages}), 50)
        print("BATCH50_IMAP_SIM=green appended=50 readback=50 sent=0 elapsed_s={:.3f}".format(seconds))

    def test_100_individual_drafts_exact_imap_readback(self):
        rows = make_rows(100)
        client = InMemoryIMAP()
        with patch("myhost_draft.load_drafts", return_value=rows), \
             patch("myhost_draft.load_suppressions", return_value=[]), \
             patch("myhost_draft.connect_imap", return_value=client), \
             patch("myhost_draft.time.sleep", return_value=None):
            outcome = draft.create_batch_from_queue([row["draft_id"] for row in rows])
        self.assertEqual(outcome, {"total": 100, "created": 100, "existing": 0})
        self.assertEqual(client.append_attempts, 100)
        self.assertEqual(len(client.messages), 100)
        self.assertEqual(client.logout_count, 1)
        print("BATCH100_IMAP_SIM=green appended=100 readback=100 sent=0")

    def test_retry_after_partial_failure_is_idempotent(self):
        rows = make_rows()
        client = InMemoryIMAP()
        client.fail_at = 25
        with patch("myhost_draft.load_drafts", return_value=rows), \
             patch("myhost_draft.load_suppressions", return_value=[]), \
             patch("myhost_draft.connect_imap", return_value=client), \
             patch("myhost_draft.time.sleep", return_value=None):
            with self.assertRaises(RuntimeError):
                draft.create_batch_from_queue([r["draft_id"] for r in rows])
            self.assertEqual(len(client.messages), 24)
            client.fail_at = None
            outcome = draft.create_batch_from_queue([r["draft_id"] for r in rows])
        self.assertEqual(outcome, {"total": 50, "created": 26, "existing": 24})
        self.assertEqual(len(client.messages), 50)
        self.assertEqual(client.logout_count, 2)


if __name__ == "__main__":
    unittest.main()
