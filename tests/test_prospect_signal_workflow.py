import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "prospect-signal-discovery.yml"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


class ProspectSignalWorkflowTests(unittest.TestCase):
    def test_workflow_is_read_only_and_actions_are_pinned(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("\npermissions:\n  contents: read\n", text)
        for raw in text.splitlines():
            stripped = raw.strip()
            if not stripped.startswith("uses:"):
                continue
            target = stripped.split("uses:", 1)[1].strip().split()[0]
            self.assertRegex(target.rsplit("@", 1)[1], FULL_SHA)

    def test_workflow_has_sheet_secret_only(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("GOOGLE_SERVICE_ACCOUNT_JSON", text)
        for forbidden in ("OUTREACH_MAIL_PASSWORD", "OUTREACH_MAILBOXES_JSON", "OUTREACH_SEED_INBOXES_JSON", "REOON_API_KEY"):
            self.assertNotIn(forbidden, text)

    def test_schedule_is_validate_until_explicitly_enabled(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("SIGNAL_DISCOVERY_ENABLED: ${{ vars.PROSPECT_SIGNAL_DISCOVERY_ENABLED }}", text)
        self.assertIn('elif [ "$SIGNAL_DISCOVERY_ENABLED" = "true" ]; then', text)
        self.assertIn('mode="discover"', text)
        self.assertIn('mode="validate"', text)

    def test_runtime_is_advisory_and_bounded(self):
        runtime = (ROOT / "scripts" / "prospect_signal_discovery_runtime.py").read_text(encoding="utf-8")
        self.assertIn("HARD_MAX_CANDIDATES = 25", runtime)
        self.assertIn("ALLOWED_CANDIDATE_STATUSES", runtime)
        self.assertIn('"send_permission": "none"', runtime)
        self.assertNotIn("outreach_direct_smtp_runtime", runtime)
        self.assertNotIn("ContactCandidates", runtime)

    def test_machine_contract_registers_signal_collector_as_advisory(self):
        contract = json.loads((ROOT / "toolkit-contract.json").read_text(encoding="utf-8"))
        capability = contract["capabilities"]["prospect_signal_discovery"]
        self.assertEqual(capability["send_permission"], "none")
        self.assertFalse(capability["automatic_score_effect"])
        self.assertEqual(capability["scheduled_default"], "validate")
        self.assertEqual(capability["scheduled_discover_gate"], "PROSPECT_SIGNAL_DISCOVERY_ENABLED=true")
        self.assertEqual(capability["required_secrets"], ["GOOGLE_SERVICE_ACCOUNT_JSON"])


if __name__ == "__main__":
    unittest.main()
