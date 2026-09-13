import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "daily-lead-drafts-v16.yml"


class DailyLeadDraftV16WorkflowTests(unittest.TestCase):
    def test_route_is_isolated_owner_bound_and_draft_only(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("CREATE DAILY LEAD DRAFTS V16", text)
        self.assertIn("COMMAND=CREATE_DAILY_LEAD_DRAFTS_V16", text)
        self.assertIn("github.actor == 'Yolol100'", text)
        self.assertIn("cancel-in-progress: true", text)
        self.assertIn("IMAP_DRAFT_ONLY", text)
        self.assertIn("SMTP_SEND=not_invoked", text)
        for forbidden in ("smtplib", "smtp.send", "outreach_direct_smtp_runtime.py", "outreach-smtp.yml"):
            self.assertNotIn(forbidden, text)

    def test_modes_keep_mailbox_write_out_of_validate_and_refresh(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("validate|refresh|create", text)
        self.assertIn("Validate current v16 pool without writes", text)
        self.assertIn("Refresh safe unsent copy to v16 contract", text)
        self.assertIn("mailbox_write=not_invoked smtp_send=not_invoked", text)
        self.assertIn("if: steps.command.outputs.mode == 'create'", text)

    def test_v16_scripts_own_refresh_refill_and_creation(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        required = (
            "outreach_agent_copy_refresh_batch_v16.py",
            "outreach_daily_batch_drafts_v16.py",
            "prospect_contact_enrichment_v16.py",
            "outreach_daily_prepare_v16.py",
            "prospect_discovery_runtime.py",
            "prospect_signal_discovery_runtime.py",
            "prospect_agent_qualification.py",
        )
        for name in required:
            self.assertIn(name, text)
        self.assertNotIn("prospect_campaign_gate.py", text)
        self.assertNotIn("outreach_daily_prepare_new.py", text)
        self.assertNotIn("outreach_daily_batch_drafts_v2.py", text)

    def test_exact_target_and_readback_remain_required(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("Refill v16 until requested target is ready", text)
        self.assertIn("while true", text)
        self.assertIn("BLOCKED_NO_PROGRESS", text)
        self.assertIn('grep -q "drafts=${{ steps.command.outputs.target }}"', text)
        self.assertIn("Create exact v16 IMAP drafts and verify readback", text)
        self.assertIn("assert len(selected) == target", text)
        self.assertIn("assert len(receipts) == target", text)
        self.assertIn("assert all(x.get('readback_count') == 1 for x in receipts)", text)
        self.assertIn("CLOSURE_V16_AUDIT=green", text)

    def test_remote_actions_are_sha_pinned(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        for raw in text.splitlines():
            stripped = raw.strip()
            if stripped.startswith("uses:") and not stripped.split("uses:", 1)[1].strip().startswith("./"):
                target = stripped.split("uses:", 1)[1].strip().split()[0]
                self.assertRegex(target.rsplit("@", 1)[1], r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
