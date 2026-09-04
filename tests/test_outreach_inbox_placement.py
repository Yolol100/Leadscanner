import json
import os
import unittest
from unittest.mock import patch

import outreach_inbox_placement as m


class Mailbox:
    sender_email = "sender@example.nl"
    sender_name = "Andrew"


class PlacementTests(unittest.TestCase):
    def seed_json(self):
        return json.dumps([{
            "seed_id": "g1",
            "email": "seed@example.com",
            "imap_host": "imap.example.com",
            "username": "seed@example.com",
            "password": "secret",
        }])

    def test_seed_config_is_bounded(self):
        seeds = m.load_seeds(self.seed_json(), require_credentials=True)
        self.assertEqual(len(seeds), 1)
        too_many = [{"seed_id": str(i), "email": f"x{i}@example.com"} for i in range(6)]
        with self.assertRaises(m.PlacementError):
            m.load_seeds(json.dumps(too_many))

    @patch.object(m, "build_sheets_service")
    @patch.object(m, "get_values", return_value=[m.PLACEMENT_HEADERS])
    def test_validate_mode_never_sends(self, _values, _service):
        env = {
            "OUTREACH_SPREADSHEET_ID": "sheet",
            "GOOGLE_SERVICE_ACCOUNT_JSON": "{}",
            "OUTREACH_SEED_INBOXES_JSON": self.seed_json(),
        }
        with patch.dict(os.environ, env, clear=True), patch.object(m, "smtp_send") as send:
            rows = m.run("validate")
            self.assertEqual(rows, [])
            send.assert_not_called()

    @patch.object(m, "build_sheets_service")
    @patch.object(m, "get_values", return_value=[m.PLACEMENT_HEADERS])
    def test_test_mode_requires_explicit_enable(self, _values, _service):
        env = {
            "OUTREACH_SPREADSHEET_ID": "sheet",
            "GOOGLE_SERVICE_ACCOUNT_JSON": "{}",
            "OUTREACH_SEED_INBOXES_JSON": self.seed_json(),
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(m.PlacementError):
                m.run("test")

    def test_controlled_rows_classify_inbox_and_spam(self):
        seeds = m.load_seeds(json.dumps([
            {"seed_id": "a", "email": "a@example.com", "imap_host": "i", "username": "a", "password": "x"},
            {"seed_id": "b", "email": "b@example.com", "imap_host": "i", "username": "b", "password": "x"},
        ]), require_credentials=True)
        sent = []

        def send(msg, mailbox):
            sent.append(msg["To"])

        def locate(seed, test_id):
            return ("inbox", "INBOX") if seed.seed_id == "a" else ("spam", "INBOX,Junk")

        rows = m._test_rows(seeds, Mailbox(), test_id="placement-123", poll_seconds=2, max_wait_seconds=10, send=send, locator=locate)
        self.assertEqual(sent, ["a@example.com", "b@example.com"])
        self.assertEqual([row["result"] for row in rows], ["inbox", "spam"])


if __name__ == "__main__":
    unittest.main()
