"""Security boundaries for the reusable, manual cohort validator."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CohortWorkflowTests(unittest.TestCase):
    def test_manual_only_and_no_send_or_dispatch_permissions(self):
        workflow = ROOT / '.github/workflows/outreach-cohort-validation.yml'
        text = workflow.read_text()
        self.assertIn('workflow_dispatch:', text)
        for forbidden in ('push:', 'schedule:', 'actions: write', 'contents: write',
                          'GH_TOKEN:', '/dispatches', 'OUTREACH_MAIL_PASSWORD',
                          'OUTREACH_MAILBOXES_JSON', 'mode: live'):
            self.assertNotIn(forbidden, text)
        self.assertIn('python3 scripts/outreach_one_time_us_guard.py', text)
        self.assertFalse((ROOT / '.github/workflows/one-time-us-outreach.yml').exists())

    def test_targets_are_runtime_inputs_and_actions_are_pinned(self):
        text = (ROOT / '.github/workflows/outreach-cohort-validation.yml').read_text()
        self.assertIn('${{ inputs.expected_lead_ids }}', text)
        self.assertIn('${{ vars.OUTREACH_SPREADSHEET_ID }}', text)
        self.assertNotIn('||', text)
        self.assertNotRegex(text, r'prospect-[0-9a-f]{20}')
        for target in re.findall(r'uses:\s*(\S+)', text):
            self.assertRegex(target.rsplit('@', 1)[-1], r'^[0-9a-f]{40}$')


if __name__ == '__main__':
    unittest.main()
