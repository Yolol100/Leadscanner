from pathlib import Path
import unittest


class WorkflowContractTests(unittest.TestCase):
    def test_owner_only_no_mailbox_secret_no_smtp(self):
        text = Path('.github/workflows/reprepare-agent-lead-command.yml').read_text(encoding='utf-8')
        self.assertIn("github.actor == 'Yolol100'", text)
        self.assertIn("github.event.issue.title == 'REFRESH AGENT COPY'", text)
        self.assertIn("COMMAND=REFRESH_AGENT_COPY", text)
        self.assertIn("OUTREACH_AGENT_COPY_REFRESH=green", text)
        self.assertIn("MAILBOX_CREDENTIAL=not_loaded", text)
        self.assertNotIn("OUTREACH_MAIL_PASSWORD", text)
        self.assertNotIn("outreach_direct_smtp_runtime.py", text)
        self.assertNotIn("actions: write", text)


if __name__ == '__main__':
    unittest.main()
