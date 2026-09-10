import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "daily-lead-drafts.yml"
SCRIPT = ROOT / "scripts" / "outreach_daily_batch_drafts.py"
HARDENED_SCRIPT = ROOT / "scripts" / "outreach_daily_batch_drafts_v2.py"


class DailyLeadDraftWorkflowTests(unittest.TestCase):
    def test_trigger_is_owner_bound_and_single_command(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("types: [opened]", text)
        self.assertIn("github.actor == 'Yolol100'", text)
        self.assertIn("github.ref == 'refs/heads/main'", text)
        self.assertIn("CREATE DAILY LEAD DRAFTS", text)
        self.assertIn("COMMAND=CREATE_DAILY_LEAD_DRAFTS", text)
        self.assertIn("cancel-in-progress: false", text)

    def test_route_is_draft_only_and_never_invokes_smtp_send(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        script = SCRIPT.read_text(encoding="utf-8") + HARDENED_SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("outreach_direct_smtp_runtime.py", "outreach-smtp.yml", "smtplib", "send_email(", "smtp.send"):
            self.assertNotIn(forbidden, workflow + "\n" + script)
        self.assertIn("IMAP_DRAFT_ONLY", workflow)
        self.assertIn("smtp_send=not_invoked", script)
        self.assertIn("send_permission=none", script)

    def test_refill_is_target_driven_not_fixed_pass_count(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("Refill until target or bounded continuation", text)
        self.assertIn("while true", text)
        self.assertIn("REFILL_TARGET=green", text)
        self.assertIn("BLOCKED_NO_NEW_APPROVED_OUTPUT", text)
        self.assertIn("BLOCKED_BOUNDED_REFILL", text)
        self.assertNotIn("for pass in 1 2 3 4", text)
        self.assertRegex(text, r'\[ "\$ready" -ge "\$target" \]')

    def test_refill_rediscovers_and_requalifies_when_short(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        required = (
            "prospect_discovery_runtime.py",
            "prospect_candidate_sanitizer.py",
            "prospect_signal_discovery_runtime.py",
            "prospect_agent_qualification.py",
            "prospect_campaign_gate.py",
            "prospect_contact_enrichment_campaign.py",
            "prospect_intelligence_runtime.py",
            "outreach_daily_prepare_new.py",
            "outreach_daily_batch_drafts_v2.py",
        )
        for name in required:
            self.assertIn(name, text)
        self.assertNotIn("AGENT_SALES_TARGET_TYPE: auto", text)
        self.assertIn('discovered="$(python3 -c', text)
        self.assertIn('[ "$no_progress" -ge 3 ] && [ "$no_new" -ge 3 ]', text)
        helper = (ROOT / "scripts" / "outreach_daily_prepare_new.py").read_text(encoding="utf-8")
        self.assertIn("from outreach_agent_prepare_v2 import build_prepared_row", helper)
        self.assertIn("candidate_id in queued_ids", helper)

    def test_completion_requires_exact_target_and_readback_route(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        runtime = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('grep -q "drafts=${{ steps.command.outputs.target }}"', text)
        self.assertNotIn('grep -q "drafted=${{ steps.command.outputs.target }}"', text)
        self.assertIn('drafts={len(receipts)}', runtime)
        self.assertIn("Create idempotent IMAP drafts and verify readback", text)
        self.assertIn("Audit exact closure evidence", text)
        self.assertIn("assert len(set(lead_ids)) == target", text)
        self.assertIn("assert len(set(hosts)) == target", text)
        self.assertIn("assert all(x.get('readback_count') == 1 for x in receipts)", text)
        self.assertIn("13.6.0-refill-audit", text)

    def test_blocked_issue_stays_open_for_continuation(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('if [ "$JOB_STATUS" = success ]; then', text)
        self.assertIn("state_reason", text)
        close_block = text.split('if [ "$JOB_STATUS" = success ]; then', 1)[1]
        self.assertIn('"state":"closed"', close_block)

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
        self.assertRegex(text, r'\[ "\$target" -le 50 \]')
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("target must be between 1 and 50", script)


if __name__ == "__main__":
    unittest.main()
