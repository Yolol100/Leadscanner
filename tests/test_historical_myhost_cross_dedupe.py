"""Synthetic full-folder To/domain dedupe evidence without PII logging."""
from unittest.mock import patch
import unittest

import _once_historical_myhost_audit as audit


class HeaderOnlyIMAP:
    def __init__(self, texts):
        self.texts = texts
        self.readonly = []
        self.fetch_calls = []
        self.closed = False
    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "Drafts"']
    def select(self, mailbox, readonly=True):
        self.readonly.append(readonly)
        return "OK", [b"3"]
    def search(self, *args):
        return "OK", [b" ".join(str(i + 1).encode()
                                for i in range(len(self.texts)))]
    def fetch(self, seq, selector):
        self.fetch_calls.append(selector)
        indices = [int(value) - 1 for value in seq.split(",")]
        return "OK", [(str(i+1).encode(), self.texts[i]) for i in indices]
    def logout(self):
        self.closed = True


class CrossDuplicateTests(unittest.TestCase):
    def _run(self, texts):
        texts = list(texts)
        while len(texts) < 43:
            i = len(texts)
            texts.append((f"To: one{i}@unique{i}.nl\r\n\r\n").encode())
        client = HeaderOnlyIMAP(texts)
        baseline = (
            None, None, None, {"source_checked": 1128},
            [{"lead_id": "growth-" + "a" * 20,
              "email": "info@sample.nl", "domain": "sample.nl"}] * 43, {},
        )
        with patch.object(audit, "source_and_mailbox_snapshot", return_value=baseline), \
             patch.object(audit, "connect_imap", return_value=client):
            result = audit.deep_duplicate_report()
        self.assertTrue(client.closed)
        self.assertTrue(all(client.readonly))
        self.assertTrue(all("BODY.PEEK[HEADER" in x for x in client.fetch_calls))
        self.assertNotIn("@", str(result))
        return result

    def test_existing_draft_with_same_recipient_causes_hold(self):
        rows = [
            b"To: info@sample.nl\r\nX-Leadscanner-Lead-ID: growth-" + b"a"*20 + b"\r\n\r\n",
            b"To: info@sample.nl\r\nX-Leadscanner-Lead-ID: growth-" + b"b"*20 + b"\r\n\r\n",
            b"To: unrelated@different.nl\r\n\r\n",
        ]
        result = self._run(rows)
        self.assertEqual(result["status"], "hold")
        self.assertEqual(result["cross_recipient_duplicates"], 1)
        self.assertEqual(result["cross_business_domain_duplicates"], 1)
        self.assertEqual(result["writes"], 0)

    def test_other_draft_same_company_domain_blocks_even_with_other_mailbox(self):
        rows = [
            b"To: info@sample.nl\r\nX-Leadscanner-Lead-ID: growth-" + b"a"*20 + b"\r\n\r\n",
            b"To: eigenaar@sample.nl\r\nX-Leadscanner-Lead-ID: growth-" + b"b"*20 + b"\r\n\r\n",
            b"To: unrelated@different.nl\r\n\r\n",
        ]
        result = self._run(rows)
        self.assertEqual(result["status"], "hold")
        self.assertEqual(result["cross_recipient_duplicates"], 0)
        self.assertEqual(result["cross_business_domain_duplicates"], 1)

    def test_no_cross_folder_duplicates_returns_green(self):
        rows = [
            b"To: info@sample.nl\r\nX-Leadscanner-Lead-ID: growth-" + b"a"*20 + b"\r\n\r\n",
            b"To: info@another.nl\r\nX-Leadscanner-Lead-ID: growth-" + b"b"*20 + b"\r\n\r\n",
            b"To: unrelated@different.nl\r\n\r\n",
        ]
        result = self._run(rows)
        self.assertEqual(result["status"], "green")
        self.assertEqual(result["cross_recipient_duplicates"], 0)
        self.assertEqual(result["cross_business_domain_duplicates"], 0)


if __name__ == "__main__":
    unittest.main()
