import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "daily-lead-drafts.yml"
SCRIPT = ROOT / "scripts" / "outreach_daily_batch_drafts.py"
HARDENED_SCRIPT = ROOT / "scripts" / "outreach_daily_batch_drafts_v2.py"


class DailyLeadDraftWorkflowTests(unittest.TestCase):
    def test_trigger_is_owner_bound_and_single_command(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("issues:", text)
        self.assertIn("types: [opened]", text)
        self.assertIn("github.actor == 'Yolol100'", text)
        self.assertIn("github.ref == 'refs/heads/main'", text)
        self.assertIn("CREATE DAILY LEAD DRAFTS", text)
        self.assertIn("COMMAND=CREATE_DAILY_LEAD_DRAFTS", text)
        self.assertIn("concurrency:", text)
        self.assertIn("cancel-in-progress: false", text)

    def test_route_is_draft_only_and_never_invokes_smtp_send(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        script = SCRIPT.read_text(encoding="utf-8") + HARDENED_SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("outreach_direct_smtp_runtime.py", "outreach-smtp.yml", "smtplib", "send_email(", "smtp.send"):
            self.assertNotIn(forbidden, workflow + "\n" + script)
        self.assertIn("IMAP_DRAFT_ONLY", workflow)
        self.assertIn("smtp_send=not_invoked", script)
        self.assertIn("send_permission=none", script)

    def test_runtime_uses_current_prepare_and_evidence_chain(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        for required in (
            "prospect_discovery_runtime.py",
            "prospect_candidate_sanitizer.py",
            "prospect_signal_discovery_runtime.py",
            "prospect_agent_qualification.py",
            "prospect_campaign_gate.py",
            "prospect_contact_enrichment_campaign.py",
            "prospect_intelligence_runtime.py",
            "outreach_daily_prepare_new.py",
            "outreach_daily_batch_drafts_v2.py",
        ):
            self.assertIn(required, text)
        self.assertNotIn("AGENT_SALES_TARGET_TYPE: auto", text)
        helper = (ROOT / "scripts" / "outreach_daily_prepare_new.py").read_text(encoding="utf-8")
        self.assertIn("from outreach_agent_prepare_v2 import build_prepared_row", helper)
        self.assertIn("candidate_id in queued_ids", helper)
        self.assertIn("13.5.0-evidence-personalization", text)

    def test_remote_actions_are_full_sha_pinned(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        for raw in text.splitlines():
            stripped = raw.strip()
            if stripped.startswith("uses:") and not stripped.split("uses:", 1)[1].strip().startswith("./"):
                target = stripped.split("uses:", 1)[1].strip().split()[0]
                self.assertRegex(target.rsplit("@", 1)[1], r"^[0-9a-f]{40}$")

    def test_least_privilege_and_no_secret_content_in_issue(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("contents: read", text)
        self.assertIn("issues: write", text)
        self.assertNotIn("actions: write", text)
        self.assertNotIn("SUBJECT=", text)
        self.assertNotIn("BODY=", text)
        self.assertNotIn("RECIPIENT=", text)
        self.assertNotIn("OUTREACH_MAIL_PASSWORD=", text)

    def test_target_is_hard_capped_at_50(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertRegex(text, r"\[ \"\$target\" -gt 50 \]")
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("target must be between 1 and 50", script)


if __name__ == "__main__":
    unittest.main()
