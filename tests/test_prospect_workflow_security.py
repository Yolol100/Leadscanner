import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "prospect-discovery.yml"
DISCOVERY = ROOT / "scripts" / "prospect_discovery.py"
CONTRACT = ROOT / "toolkit-contract.json"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


class ProspectWorkflowSecurityTests(unittest.TestCase):
    def test_workflow_is_read_only_at_github_permission_layer(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("\npermissions:\n  contents: read\n", text)
        self.assertNotIn("write-all", text)

    def test_remote_actions_are_sha_pinned(self):
        for raw in WORKFLOW.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if not stripped.startswith("uses:"):
                continue
            target = stripped.split("uses:", 1)[1].strip().split()[0]
            ref = target.rsplit("@", 1)[1]
            self.assertRegex(ref, FULL_SHA)

    def test_discovery_never_receives_mail_or_verifier_secrets(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        for forbidden in ("OUTREACH_MAIL_PASSWORD", "OUTREACH_MAILBOXES_JSON", "REOON_API_KEY"):
            self.assertNotIn(forbidden, text)
        self.assertIn("GOOGLE_SERVICE_ACCOUNT_JSON", text)

    def test_scheduled_runs_validate_when_discovery_is_disabled(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("DISCOVERY_ENABLED: ${{ vars.PROSPECT_DISCOVERY_ENABLED }}", text)
        self.assertIn('elif [ "$DISCOVERY_ENABLED" = "true" ]; then', text)
        self.assertIn('mode="discover"', text)
        self.assertIn('mode="validate"', text)
        self.assertNotIn("if: github.event_name == 'workflow_dispatch' || vars.PROSPECT_DISCOVERY_ENABLED == 'true'", text)

    def test_discovery_byte_default_stays_inside_existing_hard_cap(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        discovery = DISCOVERY.read_text(encoding="utf-8")
        self.assertIn("PROSPECT_DISCOVERY_MAX_BYTES: ${{ vars.PROSPECT_DISCOVERY_MAX_BYTES || '2097152' }}", workflow)
        self.assertIn("HARD_MAX_BYTES = 2_097_152", discovery)

    def test_machine_contract_matches_scheduled_discovery_gate(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        discovery = contract["capabilities"]["prospect_discovery"]
        self.assertEqual(discovery["scheduled_default"], "validate")
        self.assertEqual(discovery["scheduled_discover_gate"], "PROSPECT_DISCOVERY_ENABLED=true")
        self.assertIn(
            "Scheduled prospect discovery remains validate-only unless PROSPECT_DISCOVERY_ENABLED=true explicitly promotes the scheduled run to discover mode.",
            contract["boundaries"],
        )


if __name__ == "__main__": unittest.main()
