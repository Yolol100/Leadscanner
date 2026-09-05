import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "prospect-intelligence.yml"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
CANONICAL_SHEET_ID = "1p4vZnCdcex9zpTAV-ssebXqZcBS2TU6KfXwS-4d2iSI"


class ProspectIntelligenceWorkflowTests(unittest.TestCase):
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

    def test_scheduled_mode_is_validate_by_default(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("INTELLIGENCE_ENABLED: ${{ vars.PROSPECT_INTELLIGENCE_ENABLED }}", text)
        self.assertIn('elif [ "$INTELLIGENCE_ENABLED" = "true" ]; then', text)
        self.assertIn('mode="refresh"', text)
        self.assertIn('mode="validate"', text)

    def test_standalone_runtime_has_safe_canonical_defaults(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(f"OUTREACH_SPREADSHEET_ID: ${{{{ vars.OUTREACH_SPREADSHEET_ID || '{CANONICAL_SHEET_ID}' }}}}", text)
        self.assertIn("PROSPECT_INTELLIGENCE_STALE_DAYS: ${{ vars.PROSPECT_INTELLIGENCE_STALE_DAYS || '30' }}", text)

    def test_intelligence_does_not_invoke_delivery_runtime(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("prospect_intelligence_runtime.py", text)
        self.assertNotIn("outreach_direct_smtp_runtime.py", text)
        self.assertNotIn("contact-enrichment", text)

    def test_machine_contract_and_registry_keep_intelligence_advisory(self):
        contract = json.loads((ROOT / "toolkit-contract.json").read_text(encoding="utf-8"))
        registry = json.loads((ROOT / "tool-registry.json").read_text(encoding="utf-8"))
        discovery = contract["capabilities"]["prospect_discovery"]
        intelligence = contract["capabilities"]["prospect_intelligence"]
        self.assertIn("ProspectObservations", discovery["outputs"])
        self.assertIn("PROSPECT_DISCOVERY_TARGET_NEW", discovery["optional_variables"])
        self.assertEqual(intelligence["send_permission"], "none")
        self.assertFalse(intelligence["automatic_score_effect"])
        self.assertEqual(intelligence["scheduled_default"], "validate")
        self.assertEqual(intelligence["scheduled_refresh_gate"], "PROSPECT_INTELLIGENCE_ENABLED=true")
        self.assertTrue(registry["policy"]["prospect_intelligence_advisory_only"])
        self.assertFalse(registry["tools"]["prospect_intelligence"]["automatic_score_effect"])

    def test_integration_contract_documents_target_gap_and_intelligence_boundaries(self):
        text = (ROOT / "LEADS-INTEGRATION.md").read_text(encoding="utf-8")
        self.assertIn("PROSPECT_DISCOVERY_TARGET_NEW", text)
        self.assertIn("target_gap", text)
        self.assertIn("Capability 9 — prospect_intelligence", text)
        self.assertIn("wijzigen nooit zelfstandig Customer Potential", text)


if __name__ == "__main__":
    unittest.main()
