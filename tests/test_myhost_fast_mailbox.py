import unittest
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default

from myhost_fast_mailbox import (
    bulk_inventory_drafts,
    current_from_inventory,
    delete_known_draft_and_verify,
    replace_known_draft_and_verify,
    uid_from_inventory,
)


def raw_message(lead_id, body="old"):
    msg = EmailMessage(policy=default)
    msg["To"] = "info@example.nl"
    msg["Subject"] = "Idee"
    msg["X-Webactueel-Lead-ID"] = lead_id
    msg["X-Webactueel-Review-Required"] = "contact-basis"
    msg.set_content(body)
    return msg.as_bytes(policy=default)


class FakeUIDIMAP:
    def __init__(self, lead_id, *, uidplus=True):
        self.messages = {b"10": raw_message(lead_id)}
        self.capabilities = (b"IMAP4REV1", b"UIDPLUS") if uidplus else (b"IMAP4REV1",)
        self.deleted = set()
        self.next_uid = 11
        self.uid_searches = 0
        self.full_fetch_calls = 0
        self.append_calls = 0
        self.tamper_new_uid_fetch = False
        self.last_appended_uid = None

    def select(self, folder, readonly=True):
        return "OK", [str(len(self.messages)).encode()]

    def uid(self, command, *args):
        command = command.casefold()
        if command == "search":
            self.uid_searches += 1
            if args[-1] == "ALL":
                return "OK", [b" ".join(sorted(self.messages, key=int))]
            lead_id = str(args[-1]).strip('"')
            found = []
            for uid, raw in self.messages.items():
                if uid in self.deleted:
                    continue
                msg = BytesParser(policy=default).parsebytes(raw)
                if msg.get("X-Webactueel-Lead-ID") == lead_id:
                    found.append(uid)
            return "OK", [b" ".join(found)]
        if command == "fetch":
            uid_values = str(args[0]).encode().split(b",")
            query = str(args[1])
            if "HEADER.FIELDS" not in query:
                self.full_fetch_calls += 1
            rows = []
            for uid in uid_values:
                msg = BytesParser(policy=default).parsebytes(self.messages[uid])
                if "HEADER.FIELDS" in query:
                    header = EmailMessage(policy=default)
                    header["X-Webactueel-Lead-ID"] = msg.get("X-Webactueel-Lead-ID")
                    payload = header.as_bytes(policy=default)
                else:
                    payload = self.messages[uid]
                    if self.tamper_new_uid_fetch and uid == self.last_appended_uid:
                        tampered = BytesParser(policy=default).parsebytes(payload)
                        tampered.set_content("tampered")
                        payload = tampered.as_bytes(policy=default)
                rows.append((b"1 (UID " + uid + b" RFC822 {1}", payload))
            return "OK", rows
        if command == "store":
            self.deleted.add(str(args[0]).encode())
            return "OK", [b""]
        if command == "expunge":
            uid = str(args[0]).encode()
            if uid in self.deleted:
                self.messages.pop(uid, None)
                self.deleted.discard(uid)
            return "OK", [b""]
        raise AssertionError((command, args))

    def append(self, folder, flags, date, raw):
        self.append_calls += 1
        uid = str(self.next_uid).encode()
        self.next_uid += 1
        self.last_appended_uid = uid
        self.messages[uid] = raw
        return "OK", [b""]

    def expunge(self):
        raise AssertionError("global EXPUNGE must never be used")


class FastMailboxTests(unittest.TestCase):
    def test_bulk_inventory_fetches_full_messages_in_one_uid_batch(self):
        lead_a = "growth-" + "a" * 20
        lead_b = "growth-" + "b" * 20
        client = FakeUIDIMAP(lead_a)
        client.messages[b"20"] = raw_message(lead_b, body="other")
        inventory = bulk_inventory_drafts(client, "Drafts", [lead_a, lead_b])
        self.assertEqual(current_from_inventory(inventory, lead_a)["body"], "old")
        self.assertEqual(current_from_inventory(inventory, lead_b)["body"], "other")
        self.assertEqual(client.uid_searches, 1)
        self.assertEqual(client.full_fetch_calls, 1)

    def test_one_bulk_inventory_then_uid_replacement(self):
        lead_id = "growth-" + "a" * 20
        client = FakeUIDIMAP(lead_id)
        inventory = bulk_inventory_drafts(client, "Drafts", [lead_id])
        current = current_from_inventory(inventory, lead_id)
        self.assertEqual(current["count"], 1)
        self.assertEqual(client.uid_searches, 1)

        expected = EmailMessage(policy=default)
        expected["To"] = "info@example.nl"
        expected["Subject"] = "Idee"
        expected["X-Webactueel-Lead-ID"] = lead_id
        expected["X-Webactueel-Review-Required"] = "contact-basis"
        expected.set_content("new")

        outcome, final_uid, final_msg = replace_known_draft_and_verify(
            client,
            "Drafts",
            lead_id,
            uid_from_inventory(inventory, lead_id),
            expected,
            current,
        )
        self.assertEqual(outcome, "replaced")
        self.assertEqual(final_uid, b"11")
        self.assertEqual(list(client.messages), [b"11"])
        self.assertEqual(final_msg.get_content().strip(), "new")
        self.assertEqual(client.uid_searches, 3)

    def test_replacement_readback_failure_rolls_back_new_uid(self):
        lead_id = "growth-" + "f" * 20
        client = FakeUIDIMAP(lead_id)
        inventory = bulk_inventory_drafts(client, "Drafts", [lead_id])
        current = current_from_inventory(inventory, lead_id)

        expected = EmailMessage(policy=default)
        expected["To"] = "info@example.nl"
        expected["Subject"] = "Idee"
        expected["X-Webactueel-Lead-ID"] = lead_id
        expected["X-Webactueel-Review-Required"] = "contact-basis"
        expected.set_content("new")

        client.tamper_new_uid_fetch = True
        with self.assertRaisesRegex(RuntimeError, "readback mismatch"):
            replace_known_draft_and_verify(
                client,
                "Drafts",
                lead_id,
                uid_from_inventory(inventory, lead_id),
                expected,
                current,
            )
        self.assertEqual(list(client.messages), [b"10"])
        self.assertFalse(client.deleted)

    def test_replacement_fails_before_append_without_uidplus(self):
        lead_id = "growth-" + "e" * 20
        client = FakeUIDIMAP(lead_id, uidplus=False)
        inventory = bulk_inventory_drafts(client, "Drafts", [lead_id])
        current = current_from_inventory(inventory, lead_id)

        expected = EmailMessage(policy=default)
        expected["To"] = "info@example.nl"
        expected["Subject"] = "Idee"
        expected["X-Webactueel-Lead-ID"] = lead_id
        expected["X-Webactueel-Review-Required"] = "contact-basis"
        expected.set_content("new")

        with self.assertRaisesRegex(RuntimeError, "UIDPLUS"):
            replace_known_draft_and_verify(
                client,
                "Drafts",
                lead_id,
                uid_from_inventory(inventory, lead_id),
                expected,
                current,
            )
        self.assertEqual(client.append_calls, 0)
        self.assertEqual(list(client.messages), [b"10"])
        self.assertFalse(client.deleted)

    def test_delete_fails_closed_without_uidplus(self):
        lead_id = "growth-" + "b" * 20
        client = FakeUIDIMAP(lead_id, uidplus=False)
        inventory = bulk_inventory_drafts(client, "Drafts", [lead_id])
        current = current_from_inventory(inventory, lead_id)
        with self.assertRaisesRegex(RuntimeError, "UIDPLUS"):
            delete_known_draft_and_verify(
                client,
                "Drafts",
                lead_id,
                uid_from_inventory(inventory, lead_id),
                current,
            )
        self.assertIn(b"10", client.messages)
        self.assertFalse(client.deleted)

    def test_uidplus_delete_removes_only_target_uid(self):
        lead_id = "growth-" + "c" * 20
        other_id = "growth-" + "d" * 20
        client = FakeUIDIMAP(lead_id)
        client.messages[b"20"] = raw_message(other_id)
        client.deleted.add(b"20")
        inventory = bulk_inventory_drafts(client, "Drafts", [lead_id])
        current = current_from_inventory(inventory, lead_id)
        removed = delete_known_draft_and_verify(
            client,
            "Drafts",
            lead_id,
            uid_from_inventory(inventory, lead_id),
            current,
        )
        self.assertEqual(removed, 1)
        self.assertNotIn(b"10", client.messages)
        self.assertIn(b"20", client.messages)
        self.assertIn(b"20", client.deleted)


if __name__ == "__main__":
    unittest.main()
