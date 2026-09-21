import os
import time
import unittest
from email.parser import BytesParser
from email.policy import SMTP
from unittest.mock import patch

from myhost_draft import append_and_verify, append_many_and_verify, build_message, exact_message_matches

POSTAL_ADDRESS = "123 Main Street, Example City"


class FakeIMAP:
    def __init__(self):
        self.messages = []
        self.select_calls = 0
        self.append_calls = 0
        self.search_calls = 0

    def select(self, folder, readonly=True):
        self.select_calls += 1
        return "OK", [str(len(self.messages)).encode()]

    def search(self, charset, *criteria):
        self.search_calls += 1
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



class UIDPlusFakeIMAP(FakeIMAP):
    def __init__(self):
        super().__init__()
        self.uid_fetch_calls = 0

    def append(self, folder, flags, date_time, raw):
        self.append_calls += 1
        self.messages.append(raw)
        uid = len(self.messages)
        return "OK", [f"[APPENDUID 777 {uid}] APPEND completed".encode()]

    def uid(self, command, message_set, query):
        self.assertable_command = command
        if str(command).casefold() != "fetch":
            return "BAD", [b"unsupported"]
        self.uid_fetch_calls += 1
        tokens = [token for token in str(message_set).split(",") if token]
        data = []
        for token in tokens:
            index = int(token) - 1
            raw = self.messages[index]
            data.append(
                (
                    f"{index + 1} (UID {token} RFC822 {{{len(raw)}}}".encode(),
                    raw,
                )
            )
        return "OK", data


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
            return build_message(row, POSTAL_ADDRESS)

    def batch(self, count=100):
        return [(f"lead-{index}", self.message(index=index)) for index in range(1, count + 1)]

    def test_private_postal_footer_is_added_without_mutating_queue_body(self):
        row = self.row()
        stored_body = row["body"]
        msg = build_message(row, POSTAL_ADDRESS)
        content = msg.get_content().strip()
        self.assertEqual(row["body"], stored_body)
        self.assertIn(stored_body, content)
        self.assertIn("Postadres: " + POSTAL_ADDRESS, content)

    def test_missing_private_postal_address_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "OUTREACH_POSTAL_ADDRESS"):
            build_message(self.row(), "")

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

    def test_existing_to_mismatch_blocks(self):
        client = FakeIMAP()
        actual = self.message()
        actual.replace_header("To", "other@example.nl")
        client.messages.append(actual.as_bytes(policy=SMTP))
        with self.assertRaises(RuntimeError):
            append_and_verify(client, "Drafts", self.message(), "lead-1")

    def test_existing_body_mismatch_blocks(self):
        client = FakeIMAP()
        actual = self.message()
        actual.set_content(actual.get_content().strip() + " Extra unintended text.")
        client.messages.append(actual.as_bytes(policy=SMTP))
        with self.assertRaises(RuntimeError):
            append_and_verify(client, "Drafts", self.message(), "lead-1")


    def test_batch_appenduid_uses_one_bulk_uid_readback(self):
        client = UIDPlusFakeIMAP()
        batch = self.batch(100)
        append_many_and_verify(client, "Drafts", batch)

        self.assertEqual(len(client.messages), 100)
        self.assertEqual(client.append_calls, 100)
        self.assertEqual(client.search_calls, 100)
        self.assertEqual(client.uid_fetch_calls, 1)

        for index, (_, expected) in enumerate(batch):
            actual = BytesParser(policy=SMTP).parsebytes(client.messages[index])
            self.assertTrue(exact_message_matches(actual, expected))

        append_many_and_verify(client, "Drafts", batch)
        self.assertEqual(len(client.messages), 100)
        self.assertEqual(client.append_calls, 100)
        self.assertEqual(client.uid_fetch_calls, 1)
        self.assertEqual(client.search_calls, 200)

    def test_batch_100_exact_readback_reuses_mailbox_selection(self):
        client = FakeIMAP()
        batch = self.batch(100)
        append_many_and_verify(client, "Drafts", batch)

        self.assertEqual(len(client.messages), 100)
        self.assertEqual(client.append_calls, 100)
        self.assertEqual(client.select_calls, 1)
        self.assertEqual(client.search_calls, 200)

        for index, (_, expected) in enumerate(batch):
            actual = BytesParser(policy=SMTP).parsebytes(client.messages[index])
            self.assertTrue(exact_message_matches(actual, expected))

        append_many_and_verify(client, "Drafts", batch)
        self.assertEqual(len(client.messages), 100)
        self.assertEqual(client.append_calls, 100)
        self.assertEqual(client.select_calls, 2)
        self.assertEqual(client.search_calls, 300)

    def test_batch_load_sizes_1_10_25_50_100(self):
        for count in (1, 10, 25, 50, 100):
            with self.subTest(count=count):
                client = FakeIMAP()
                batch = self.batch(count)
                started = time.perf_counter()
                append_many_and_verify(client, "Drafts", batch)
                elapsed = time.perf_counter() - started

                self.assertEqual(len(client.messages), count)
                self.assertEqual(client.append_calls, count)
                self.assertEqual(client.select_calls, 1)
                self.assertEqual(client.search_calls, count * 2)
                self.assertEqual(
                    len(
                        {
                            str(
                                BytesParser(policy=SMTP)
                                .parsebytes(raw)
                                .get("X-Webactueel-Lead-ID", "")
                            )
                            for raw in client.messages
                        }
                    ),
                    count,
                )
                print(f"BATCH_BENCH count={count} seconds={elapsed:.6f}")

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
