import unittest
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default

from myhost_fast_mailbox import (
    bulk_inventory_drafts,
    current_from_inventory,
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
    def __init__(self, lead_id):
        self.messages = {b"10": raw_message(lead_id)}
        self.deleted = set()
        self.next_uid = 11
        self.uid_searches = 0

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
            rows = []
            for uid in uid_values:
                msg = BytesParser(policy=default).parsebytes(self.messages[uid])
                if "HEADER.FIELDS" in query:
                    header = EmailMessage(policy=default)
                    header["X-Webactueel-Lead-ID"] = msg.get("X-Webactueel-Lead-ID")
                    payload = header.as_bytes(policy=default)
                else:
                    payload = self.messages[uid]
                rows.append((b"1 (UID " + uid + b" RFC822 {1}", payload))
            return "OK", rows
        if command == "store":
            self.deleted.add(str(args[0]).encode())
            return "OK", [b""]
        raise AssertionError((command, args))

    def append(self, folder, flags, date, raw):
        uid = str(self.next_uid).encode()
        self.next_uid += 1
        self.messages[uid] = raw
        return "OK", [b""]

    def expunge(self):
        for uid in list(self.deleted):
            self.messages.pop(uid, None)
        self.deleted.clear()
        return "OK", [b""]


class FastMailboxTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
