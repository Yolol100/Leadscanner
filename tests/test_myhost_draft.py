import os
import unittest
from email.parser import BytesParser
from email.policy import SMTP
from unittest.mock import patch

from myhost_draft import append_and_verify, build_message, exact_message_matches


class FakeIMAP:
    def __init__(self):
        self.messages = []

    def select(self, folder, readonly=True):
        return "OK", [str(len(self.messages)).encode()]

    def search(self, charset, *criteria):
        lead_id = str(criteria[-1]).strip('"')
        found = []
        for index, raw in enumerate(self.messages, start=1):
            msg = BytesParser(policy=SMTP).parsebytes(raw)
            if str(msg.get("X-Webactueel-Lead-ID", "")) == lead_id:
                found.append(str(index).encode())
        return "OK", [b" ".join(found)]

    def fetch(self, message_id, query):
        index = int(message_id) - 1
        raw = self.messages[index]
        return "OK", [(b"1 (RFC822)", raw)]

    def append(self, folder, flags, date_time, raw):
        self.messages.append(raw)
        return "OK", [b"APPEND completed"]


class DraftTests(unittest.TestCase):
    def row(self):
        return {
            "lead_id": "lead-1",
            "email": "info@example.nl",
            "subject": "Kleine website kans",
            "body": (
                "Beste team, op jullie website zag ik een concrete kans in de contactroute. "
                "Ik kan één kort voorbeeld maken dat beter aansluit op de huidige pagina. "
                "Zal ik het voorbeeld sturen? Geen interesse? Een kort nee is genoeg. "
                "Met vriendelijke groet, Andrew Baeten, andrewbaeten.nl"
            ),
        }

    def message(self, subject=None):
        row = self.row()
        if subject:
            row["subject"] = subject
        with patch.dict(
            os.environ,
            {
                "OUTREACH_SENDER_NAME": "Andrew Baeten",
                "OUTREACH_SENDER_EMAIL": "info@andrewbaeten.nl",
            },
            clear=False,
        ):
            return build_message(row)

    def test_queue_body_is_final_body(self):
        row = self.row()
        msg = self.message()
        self.assertEqual(msg.get_content().strip(), row["body"].strip())

    def test_exact_message_match(self):
        expected = self.message()
        actual = BytesParser(policy=SMTP).parsebytes(expected.as_bytes(policy=SMTP))
        self.assertTrue(exact_message_matches(actual, expected))

    def test_append_then_exact_readback(self):
        client = FakeIMAP()
        msg = self.message()
        append_and_verify(client, "Drafts", msg, "lead-1")
        self.assertEqual(len(client.messages), 1)

    def test_second_identical_run_is_idempotent(self):
        client = FakeIMAP()
        msg = self.message()
        append_and_verify(client, "Drafts", msg, "lead-1")
        append_and_verify(client, "Drafts", msg, "lead-1")
        self.assertEqual(len(client.messages), 1)

    def test_existing_mismatched_draft_blocks(self):
        client = FakeIMAP()
        old = self.message(subject="Oud onderwerp")
        client.messages.append(old.as_bytes(policy=SMTP))
        with self.assertRaises(RuntimeError):
            append_and_verify(client, "Drafts", self.message(), "lead-1")

    def test_duplicate_drafts_block(self):
        client = FakeIMAP()
        msg = self.message()
        raw = msg.as_bytes(policy=SMTP)
        client.messages.extend([raw, raw])
        with self.assertRaises(RuntimeError):
            append_and_verify(client, "Drafts", msg, "lead-1")


if __name__ == "__main__":
    unittest.main()
