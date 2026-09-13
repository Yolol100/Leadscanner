import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


class LeadsWorkflowSecurityTests(unittest.TestCase):
    def test_retired_smtp_workflow_is_absent(self):
        self.assertFalse((WORKFLOWS / "outreach-smtp.yml").exists())

    def test_default_registry_is_v17_draft_only_and_no_send(self):
        registry = json.loads((ROOT / "tool-registry.json").read_text(encoding="utf-8"))
        policy = registry["policy"]
        self.assertEqual(policy["default_route"], "filter_core_v17")
        self.assertEqual(policy["default_source_set_version"], "17.0.0-filter-core")
        self.assertTrue(policy["draft_only"])
        self.assertEqual(policy["send_permission"], "none")

    def test_registered_default_surface_has_no_live_smtp_entrypoint(self):
        registry = json.loads((ROOT / "tool-registry.json").read_text(encoding="utf-8"))
        raw = json.dumps(registry, sort_keys=True)
        self.assertNotIn("outreach-smtp.yml", raw)
        self.assertNotIn("outreach_direct_smtp_runtime.py", raw)

    def test_registered_remote_actions_are_sha_pinned(self):
        registry = json.loads((ROOT / "tool-registry.json").read_text(encoding="utf-8"))
        workflow_paths = sorted({
            capability["workflow"]
            for capability in registry["capabilities"].values()
            if capability.get("workflow")
        })
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


if __name__ == "__main__":
    unittest.main()
