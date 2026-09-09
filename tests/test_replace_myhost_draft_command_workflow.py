from pathlib import Path
import unittest


class WorkflowContractTests(unittest.TestCase):
    def test_exact_owner_only_imap_replace_no_smtp(self):
        text = Path('.github/workflows/replace-myhost-draft-command.yml').read_text(encoding='utf-8')
        self.assertIn("github.actor == 'Yolol100'", text)
        self.assertIn("github.event.issue.title == 'REPLACE MYHOST DRAFT'", text)
        self.assertIn("COMMAND=REPLACE_MYHOST_DRAFT", text)
        self.assertIn("REPLACE_TEST_ID=", text)
        self.assertIn("outreach_queue_imap_draft_replace.py", text)
        self.assertIn("SMTP_SEND=not_invoked", text)
        self.assertNotIn("outreach_direct_smtp_runtime.py", text)
        self.assertNotIn("actions: write", text)


if __name__ == '__main__':
    unittest.main()
