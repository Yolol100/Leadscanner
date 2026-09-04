import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


class LeadsWorkflowSecurityTests(unittest.TestCase):
    def test_leads_remote_actions_are_sha_pinned(self):
        for filename in ("prospect-discovery.yml", "outreach-smtp.yml"):
            text = (WORKFLOWS / filename).read_text(encoding="utf-8")
            for raw in text.splitlines():
                stripped = raw.strip()
                if not stripped.startswith("uses:"):
                    continue
                target = stripped.split("uses:", 1)[1].strip().split()[0]
                if target.startswith("./"):
                    continue
                self.assertIn("@", target)
                self.assertRegex(target.rsplit("@", 1)[1], FULL_SHA)

    def test_outreach_order_is_fail_closed(self):
        text = (WORKFLOWS / "outreach-smtp.yml").read_text(encoding="utf-8")
        policy = text.index("- name: Resolve campaign pacing policy")
        push_guard = text.index("- name: Assert push validation cannot become live")
        sheet_auth = text.index("- name: Classify Sheet credential availability")
        push_block = text.index("- name: Report blocked Sheet runtime on push")
        manual_guard = text.index("- name: Require Sheet credential outside push validation")
        sender_preflight = text.index("- name: Run sender preflight")
        extended = text.index("- name: Run extended outreach contract preflight")
        compliance = text.index("- name: Run outreach compliance preflight")
        sender = text.index("- name: Process approved outreach queue")
        reporting = text.index("- name: Summarize outreach analytics")
        self.assertLess(policy, push_guard)
        self.assertLess(push_guard, sheet_auth)
        self.assertLess(sheet_auth, push_block)
        self.assertLess(push_block, manual_guard)
        self.assertLess(manual_guard, sender_preflight)
        self.assertLess(sender_preflight, extended)
        self.assertLess(extended, compliance)
        self.assertLess(compliance, sender)
        self.assertLess(sender, reporting)

    def test_manual_outreach_defaults_to_validate(self):
        text = (WORKFLOWS / "outreach-smtp.yml").read_text(encoding="utf-8")
        self.assertIn("type: choice", text)
        self.assertIn("- validate", text)
        self.assertIn("- live", text)
        self.assertIn("default: validate", text)
        self.assertIn("vars.OUTREACH_ENABLED == 'true'", text)

    def test_main_push_forces_validate_mode(self):
        text = (WORKFLOWS / "outreach-smtp.yml").read_text(encoding="utf-8")
        self.assertIn("push:", text)
        self.assertIn("github.event_name == 'push'", text)
        self.assertIn("github.event_name == 'push' && 'validate'", text)
        self.assertIn("Assert push validation cannot become live", text)
        self.assertIn('test "$OUTREACH_EFFECTIVE_MODE" = "validate"', text)

    def test_push_without_sheet_secret_is_blocked_not_failed_runtime(self):
        text = (WORKFLOWS / "outreach-smtp.yml").read_text(encoding="utf-8")
        self.assertIn("Classify Sheet credential availability", text)
        self.assertIn("Report blocked Sheet runtime on push", text)
        self.assertIn("RUNTIME_READINESS=blocked_missing_google_service_account", text)
        self.assertIn("github.event_name == 'push' && steps.sheet_auth.outputs.available != 'true'", text)
        self.assertIn("github.event_name != 'push' && steps.sheet_auth.outputs.available != 'true'", text)
        for step_name in (
            "Run sender preflight",
            "Run extended outreach contract preflight",
            "Run outreach compliance preflight",
            "Process approved outreach queue through mijn.host SMTP",
        ):
            section = text.split(f"- name: {step_name}", 1)[1]
            self.assertIn("if: steps.sheet_auth.outputs.available == 'true'", section.split("\n\n", 1)[0])

    def test_non_live_outreach_does_not_receive_mailbox_secrets(self):
        text = (WORKFLOWS / "outreach-smtp.yml").read_text(encoding="utf-8")
        expected_password = "OUTREACH_MAIL_PASSWORD: ${{ steps.policy.outputs.effective_mode == 'live' && secrets.OUTREACH_MAIL_PASSWORD || '' }}"
        expected_pool = "OUTREACH_MAILBOXES_JSON: ${{ steps.policy.outputs.effective_mode == 'live' && secrets.OUTREACH_MAILBOXES_JSON || '' }}"
        self.assertEqual(text.count(expected_password), 2)
        self.assertEqual(text.count(expected_pool), 2)
        self.assertNotIn("OUTREACH_MAIL_PASSWORD: ${{ secrets.OUTREACH_MAIL_PASSWORD }}", text)
        self.assertNotIn("OUTREACH_MAILBOXES_JSON: ${{ secrets.OUTREACH_MAILBOXES_JSON }}", text)

    def test_active_outreach_has_no_reoon_dependency(self):
        text = (WORKFLOWS / "outreach-smtp.yml").read_text(encoding="utf-8")
        self.assertNotIn("REOON_API_KEY", text)
        self.assertNotIn("outreach_verifier.py", text)
        self.assertIn("outreach_direct_smtp_runtime.py", text)

    def test_discovery_never_receives_mail_credentials(self):
        text = (WORKFLOWS / "prospect-discovery.yml").read_text(encoding="utf-8")
        self.assertIn("GOOGLE_SERVICE_ACCOUNT_JSON", text)
        for forbidden in ("OUTREACH_MAIL_PASSWORD", "OUTREACH_MAILBOXES_JSON", "REOON_API_KEY"):
            self.assertNotIn(forbidden, text)

    def test_reporting_never_receives_mail_credentials(self):
        text = (WORKFLOWS / "outreach-smtp.yml").read_text(encoding="utf-8")
        reporting = text.split("- name: Summarize outreach analytics", 1)[1]
        self.assertNotIn("OUTREACH_MAIL_PASSWORD", reporting)
        self.assertNotIn("OUTREACH_MAILBOXES_JSON", reporting)
        self.assertNotIn("REOON_API_KEY", reporting)

    def test_sheet_only_preflights_do_not_receive_mail_credentials(self):
        text = (WORKFLOWS / "outreach-smtp.yml").read_text(encoding="utf-8")
        extended = text.split("- name: Run extended outreach contract preflight", 1)[1].split("- name: Run outreach compliance preflight", 1)[0]
        compliance = text.split("- name: Run outreach compliance preflight", 1)[1].split("- name: Process approved outreach queue", 1)[0]
        for section in (extended, compliance):
            self.assertIn("GOOGLE_SERVICE_ACCOUNT_JSON", section)
            self.assertNotIn("OUTREACH_MAIL_PASSWORD", section)
            self.assertNotIn("OUTREACH_MAILBOXES_JSON", section)


if __name__ == "__main__":
    unittest.main()
