import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

RETIRED_WORKFLOWS = (
    "outreach-smtp.yml", "live-outreach-command.yml", "one-time-us-outreach.yml",
    "daily-agent-drafts-v14.yml", "daily-lead-drafts-v16.yml", "daily-lead-drafts.yml",
    "leads-autopilot.yml", "leads-replacement-continue.yml", "reprepare-agent-lead-command.yml",
    "sync-myhost-drafts-command.yml", "myhost-draft-command.yml", "prospect-intelligence.yml",
)

class LeadsWorkflowSecurityTests(unittest.TestCase):
    def test_retired_parallel_workflows_are_absent(self):
        for workflow in RETIRED_WORKFLOWS:
            self.assertFalse((WORKFLOWS / workflow).exists(), workflow)

    def test_default_registry_is_v17_draft_only_and_no_send(self):
        registry = json.loads((ROOT / "tool-registry.json").read_text(encoding="utf-8"))
        policy = registry["policy"]
        self.assertEqual(policy["default_route"], "filter_core_v17")
        self.assertEqual(policy["default_source_set_version"], "17.2.0-compliance-gate")
        self.assertTrue(policy["draft_only"])
        self.assertEqual(policy["send_permission"], "none")
        self.assertTrue(policy["contact_and_compliance_separated"])
        self.assertEqual(policy["compliance_default"], "COMPLIANCE_NOT_PROVEN")
        self.assertTrue(policy["compliance_pass_required_for_outreach"])
        self.assertFalse(policy["instantly_can_override_compliance"])

    def test_filter_core_requires_contact_and_compliance_separately(self):
        registry = json.loads((ROOT / "tool-registry.json").read_text(encoding="utf-8"))
        required = set(registry["capabilities"]["filter_core"]["required_pass_conditions"])
        self.assertIn("contact_verified_from_official_business_source", required)
        self.assertIn("separate_compliance_gate_passed_with_evidence", required)
        self.assertEqual(registry["capabilities"]["compliance_gate"]["default_status"], "COMPLIANCE_NOT_PROVEN")
        self.assertFalse(registry["capabilities"]["compliance_gate"]["public_email_alone_is_permission"])
        self.assertFalse(registry["capabilities"]["compliance_gate"]["instantly_override"])

    def test_registered_default_surface_has_no_live_or_parallel_entrypoint(self):
        registry = json.loads((ROOT / "tool-registry.json").read_text(encoding="utf-8"))
        raw = json.dumps(registry, sort_keys=True)
        self.assertNotIn("outreach-smtp.yml", raw)
        self.assertNotIn("outreach_direct_smtp_runtime.py", raw)
        for workflow in RETIRED_WORKFLOWS:
            self.assertNotIn(workflow, raw)

    def test_registered_remote_actions_are_sha_pinned(self):
        registry = json.loads((ROOT / "tool-registry.json").read_text(encoding="utf-8"))
        workflow_paths = sorted({capability["workflow"] for capability in registry["capabilities"].values() if capability.get("workflow")})
        self.assertTrue(workflow_paths)
        for relative_path in workflow_paths:
            path = ROOT / relative_path
            self.assertTrue(path.exists(), relative_path)
            text = path.read_text(encoding="utf-8")
            for raw in text.splitlines():
                stripped = raw.strip()
                if not stripped.startswith("uses:"):
                    continue
                target = stripped.split("uses:", 1)[1].strip().split()[0]
                if target.startswith("./"):
                    continue
                self.assertIn("@", target, relative_path)
                self.assertRegex(target.rsplit("@", 1)[1], FULL_SHA, relative_path)

    def test_discovery_never_receives_mail_credentials(self):
        text = (WORKFLOWS / "prospect-discovery.yml").read_text(encoding="utf-8")
        self.assertIn("GOOGLE_SERVICE_ACCOUNT_JSON", text)
        for forbidden in ("OUTREACH_MAIL_PASSWORD", "OUTREACH_MAILBOXES_JSON", "REOON_API_KEY"):
            self.assertNotIn(forbidden, text)

    def test_selected_draft_sync_serializes_mailbox_writes(self):
        text = (WORKFLOWS / "sync-selected-myhost-drafts-command.yml").read_text(encoding="utf-8")
        header = text.split("\njobs:\n", 1)[0]
        self.assertIn("group: sync-selected-myhost-drafts-${{ vars.OUTREACH_MAILBOX_ID || 'primary' }}", header)
        self.assertIn("cancel-in-progress: false", header)
        self.assertIn("queue: max", header)
        self.assertNotIn("github.event.issue.number", header)

if __name__ == "__main__":
    unittest.main()
