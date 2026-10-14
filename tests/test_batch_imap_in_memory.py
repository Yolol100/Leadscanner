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


    def test_six_rendered_queue_entries_to_imap_drafts(self):
        """Six fictional rendered handoffs: private queue -> registry -> IMAP readback."""
        from unittest.mock import Mock
        import draft_queue_readonly as queue
        from email import policy
        from email.parser import BytesParser

        subjects = (
            "offertes & avonduren Fictief Schildersbedrijf",
            "rust in de zaak & online agenda",
            "online reserveringen & zichtbaarheid",
            "telefoondrukte & spoedvragen",
            "duidelijke informatie over Fictief Dienstbedrijf",
            "servicevragen & online contact",
        )
        queue_rows = [list(queue.HEADERS)]
        draft_ids = []
        opt_out = "Liever geen e-mails meer? Antwoord met 'nee', dan laat ik het hierbij."
        for i, subject in enumerate(subjects, start=1):
            draft_id = "draft-" + f"{i:032x}"
            draft_ids.append(draft_id)
            name = "Hoi Ria," if i == 5 else "Goedendag,"
            email = "ria@fictief-dienstbedrijf.nl" if i == 5 else f"info@fictief-bedrijf-{i}.nl"
            body = name + "\n\nEen fictieve, volledig ingevulde testmail.\n\n" + opt_out + "\n\nGroet,\nAndrew"
            queue_rows.append([
                draft_id, "2026-10-15T12:00:00+02:00", f"Fictief Bedrijf {i}",
                email, f"https://fictief-bedrijf-{i}.nl/contact", subject, body,
            ])
        response = Mock(status_code=200)
        response.json.return_value = {"values": queue_rows}
        session = Mock()
        session.get.return_value = response
        client = InMemoryIMAP()
        with patch("draft_queue_readonly.authorized_session", return_value=session), \
             patch("myhost_draft.load_suppressions", return_value=[]), \
             patch("myhost_draft.connect_imap", return_value=client), \
             patch("myhost_draft.time.sleep", return_value=None):
            outcome = draft.create_batch_from_queue(draft_ids)
        self.assertEqual(outcome, {"total": 6, "created": 6, "existing": 0})
        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(client.append_attempts, 6)
        self.assertEqual(client.logout_count, 1)
        for i, (raw, flags) in enumerate(client.messages):
            msg = BytesParser(policy=policy.default).parsebytes(raw)
            self.assertEqual(flags, b"\\Draft")
            self.assertEqual(msg["Subject"], subjects[i])
            self.assertIn(opt_out, msg.get_content())
            self.assertTrue(msg.get_content().rstrip().endswith("Andrew"))
            self.assertNotIn("{{", msg.get_content())
            self.assertLessEqual(len(msg.get_content().split()), 110)
        print("SIX_CLUSTER_HANDOFF_SIM=green queue=6 imap_readback=6 sent=0")


if __name__ == "__main__":
    unittest.main()
