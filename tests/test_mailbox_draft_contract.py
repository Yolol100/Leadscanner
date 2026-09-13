import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MailboxDraftContractTests(unittest.TestCase):
    def test_contracts_define_mailbox_draft_as_no_send(self):
        toolkit = json.loads((ROOT / "toolkit-contract.json").read_text(encoding="utf-8"))
        registry = json.loads((ROOT / "tool-registry.json").read_text(encoding="utf-8"))
        toolkit_mailbox = toolkit["mailbox_contract"]
        registry_mailbox = registry["capabilities"]["mailbox_draft"]

        self.assertEqual(toolkit_mailbox["send_permission"], "none")
        self.assertEqual(registry_mailbox["send_permission"], "none")
        self.assertTrue(toolkit_mailbox["transport"].startswith("IMAP_APPEND"))
        self.assertTrue(registry_mailbox["transport"].startswith("IMAP_APPEND"))
        self.assertTrue(registry["policy"]["draft_only"])
        self.assertEqual(registry["policy"]["send_permission"], "none")


if __name__ == "__main__":
    unittest.main()
