import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MailboxDraftContractTests(unittest.TestCase):
    def test_contracts_define_mailbox_draft_as_no_send(self):
        toolkit = json.loads((ROOT / 'toolkit-contract.json').read_text(encoding='utf-8'))
        registry = json.loads((ROOT / 'tool-registry.json').read_text(encoding='utf-8'))
        for source in (toolkit, registry):
            cap = source['capabilities']['mailbox_draft']
            self.assertEqual(cap['send_permission'], 'none')
        self.assertEqual(toolkit['capabilities']['mailbox_draft']['transport'], 'IMAP APPEND + same-folder readback only')
        self.assertTrue(registry['policy']['mailbox_draft_imap_only'])


if __name__ == '__main__':
    unittest.main()
