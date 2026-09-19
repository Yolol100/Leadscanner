import os
import unittest
from email.parser import BytesParser
from email.policy import SMTP
from unittest.mock import patch

from myhost_draft import append_and_verify, append_many_and_verify, build_message, exact_message_matches


class FakeIMAP:
    def __init__(self):
        self.messages = []
        self.select_calls = 0
        self.append_calls = 0

    def select(self, folder, readonly=True):
        self.select_calls += 1
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
        self.append_calls += 1
        self.messages.append(raw)
        return "OK", [b"APPEND completed"]


class FailingIMAP(FakeIMAP):
    def __init__(self, fail_on_append: int):
        super().__init__()
        self.fail_on_append = fail_on_append
        self.failure_enabled = True

    def append(self, folder, flags, date_time, raw):
        next_call = self.append_calls + 1
        self.append_calls = next_call
        if self.failure_enabled and next_call == self.fail_on_append:
            return "NO", [b"simulated append failure"]
        self.messages.append(raw)
        return "OK", [b"APPEND completed"]


class DraftTests(unittest.TestCase):
    def row(self, index=1):
        return {
            "lead_id": f"lead-{index}",
            "email": f"info{index}@example.nl",
            "subject": f"Kleine website kans {index}",
            "body": (
                f"Beste team, op jullie website zag ik concrete kans {index} in de contactroute. "
                "Ik kan een kort voorbeeld maken dat beter aansluit op de huidige pagina. "
                "Zal ik het voorbeeld sturen? Geen interesse? Een kort nee is genoeg. "
                "Met vriendelijke groet, Andrew Baeten, andrewbaeten.nl"
            ),
        }

    def message(self, subject=None, index=1):
        row = self.row(index=index)
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

    def batch(self, count=100):
        return [(f"lead-{index}", self.message(index=index)) for index in range(1, count + 1)]

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

    def test_batch_100_exact_readback_reuses_mailbox_selection(self):
        client = FakeIMAP()
        batch = self.batch(100)
        append_many_and_verify(client, "Drafts", batch)

        self.assertEqual(len(client.messages), 100)
        self.assertEqual(client.append_calls, 100)
        self.assertEqual(client.select_calls, 101)

        for index, (_, expected) in enumerate(batch):
            actual = BytesParser(policy=SMTP).parsebytes(client.messages[index])
            self.assertTrue(exact_message_matches(actual, expected))

        append_many_and_verify(client, "Drafts", batch)
        self.assertEqual(len(client.messages), 100)
        self.assertEqual(client.append_calls, 100)
        self.assertEqual(client.select_calls, 102)

    def test_batch_partial_failure_can_resume_idempotently(self):
        client = FailingIMAP(fail_on_append=51)
        batch = self.batch(100)

        with self.assertRaises(RuntimeError):
            append_many_and_verify(client, "Drafts", batch)
        self.assertEqual(len(client.messages), 50)

        client.failure_enabled = False
        append_many_and_verify(client, "Drafts", batch)
        self.assertEqual(len(client.messages), 100)

        lead_ids = [
            str(BytesParser(policy=SMTP).parsebytes(raw).get("X-Webactueel-Lead-ID", ""))
            for raw in client.messages
        ]
        self.assertEqual(len(lead_ids), len(set(lead_ids)))


if __name__ == "__main__":
    unittest.main()
