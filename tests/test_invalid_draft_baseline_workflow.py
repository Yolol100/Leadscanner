import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class OpeningWorkflowTests(unittest.TestCase):
    def test_generic_opening_route_is_bounded_review_only(self):
        text = (ROOT / '.github/workflows/leads-opening-remediation.yml').read_text()
        self.assertIn('github.event.issue.user.login == github.repository_owner', text)
        self.assertIn('opening_transport.py resolve', text)
        self.assertIn('validate_request', (ROOT / 'scripts/opening_transport.py').read_text())
        self.assertIn('--audit', text)
        self.assertIn('opening-report.json', text)
        self.assertIn('leads-content-remediation-write', text)
        self.assertNotIn('smtplib', text)
        self.assertNotIn('sendmail(', text)
        for name in ('leads-audited-draft-remediation-once.yml', 'tmp-batch12-parallel-audit.yml', 'tmp-batch12-readonly-audit.yml'):
            self.assertFalse((ROOT / '.github/workflows' / name).exists())
