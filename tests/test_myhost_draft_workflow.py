import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'myhost-draft-test.yml'


class MyhostDraftWorkflowTests(unittest.TestCase):
    def test_workflow_is_draft_only_and_explicit(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn('workflow_dispatch:', text)
        self.assertIn('confirm_draft:', text)
        self.assertIn('draft-test-request.txt', text)
        self.assertNotIn('schedule:', text)
        self.assertNotIn('outreach_direct_smtp_runtime.py', text)
        self.assertNotIn('GOOGLE_SERVICE_ACCOUNT_JSON', text)
        self.assertIn("OUTREACH_DRAFT_SELF_ONLY: 'true'", text)
        self.assertIn('scripts/outreach_imap_draft.py', text)
        self.assertIn("grep -q '^MYHOST_DRAFT=green '", text)

    def test_secret_is_scoped_to_auth_and_draft_steps(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        self.assertEqual(text.count('OUTREACH_MAIL_PASSWORD: ${{ secrets.OUTREACH_MAIL_PASSWORD }}'), 2)
        self.assertIn('blocked_missing_outreach_mail_password', text)
        self.assertNotIn('echo "$OUTREACH_MAIL_PASSWORD"', text)

    def test_remote_actions_are_sha_pinned(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        for raw in text.splitlines():
            stripped = raw.strip()
            if stripped.startswith('uses:') and not stripped.split('uses:', 1)[1].strip().startswith('./'):
                target = stripped.split('uses:', 1)[1].strip().split()[0]
                self.assertRegex(target.rsplit('@', 1)[1], r'^[0-9a-f]{40}$')


if __name__ == '__main__':
    unittest.main()
