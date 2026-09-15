import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


class ParitySecurityTests(unittest.TestCase):
    def read(self, name):
        return (WF / name).read_text(encoding="utf-8")

    def test_new_workflows_pin_remote_actions(self):
        for name in (
            "contact-enrichment.yml",
            "sender-readiness.yml",
            "inbox-placement.yml",
            "instantly-bridge-command.yml",
        ):
            for line in self.read(name).splitlines():
                line = line.strip()
                if line.startswith("uses:") and not line.split("uses:", 1)[1].strip().startswith("./"):
                    target = line.split("uses:", 1)[1].strip().split()[0]
                    self.assertRegex(target.rsplit("@", 1)[1], FULL_SHA)

    def test_contact_enrichment_has_no_mail_or_seed_secret(self):
        text = self.read("contact-enrichment.yml")
        self.assertIn("GOOGLE_SERVICE_ACCOUNT_JSON", text)
        for forbidden in ("OUTREACH_MAIL_PASSWORD", "OUTREACH_MAILBOXES_JSON", "OUTREACH_SEED_INBOXES_JSON", "REOON_API_KEY"):
            self.assertNotIn(forbidden, text)
        self.assertNotIn("schedule:", text)

    def test_sender_readiness_does_not_send_messages(self):
        text = self.read("sender-readiness.yml")
        self.assertIn("outreach_sender_readiness.py", text)
        self.assertNotIn("outreach_direct_smtp_runtime.py", text)
        self.assertNotIn("smtp_send", text)
        self.assertNotIn("OUTREACH_SEED_INBOXES_JSON", text)

    def test_inbox_placement_is_manual_seed_only(self):
        text = self.read("inbox-placement.yml")
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("schedule:", text)
        self.assertNotIn("push:", text)
        self.assertIn("default: validate", text)
        self.assertIn("inputs.mode == 'test'", text)
        self.assertIn("confirm_test_send", text)
        self.assertIn("OUTREACH_SEED_INBOXES_JSON", text)
        self.assertNotIn("OutreachQueue", text)

    def test_instantly_bridge_is_owner_only_and_never_sends(self):
        text = self.read("instantly-bridge-command.yml")
        self.assertIn("github.actor == 'Yolol100'", text)
        self.assertIn("INSTANTLY_API_KEY", text)
        self.assertIn("SEND_PERMISSION=none", text)
        self.assertIn("ACTIVATION_INVOKED=false", text)
        for forbidden in (
            "OUTREACH_MAIL_PASSWORD",
            "OUTREACH_MAILBOXES_JSON",
            "outreach_direct_smtp_runtime.py",
            "activate-campaign",
            "resume-campaign",
        ):
            self.assertNotIn(forbidden, text)

    def test_instantly_read_only_path_does_not_receive_google_secret(self):
        text = self.read("instantly-bridge-command.yml")
        read_start = text.index("- name: Execute read-only Instantly bridge")
        sync_start = text.index("- name: Execute selected-lead Instantly sync")
        report_start = text.index("- name: Report safe result")
        read_section = text[read_start:sync_start]
        sync_section = text[sync_start:report_start]
        self.assertNotIn("GOOGLE_SERVICE_ACCOUNT_JSON", read_section)
        self.assertNotIn("OUTREACH_SPREADSHEET_ID", read_section)
        self.assertIn("GOOGLE_SERVICE_ACCOUNT_JSON", sync_section)
        self.assertIn("OUTREACH_SPREADSHEET_ID", sync_section)

    def test_instantly_command_parser_rejects_ambiguous_destinations(self):
        text = self.read("instantly-bridge-command.yml")
        self.assertIn("SYNC_SELECTED_TO_LIST requires LIST_ID only.", text)
        self.assertIn("SYNC_SELECTED_TO_CAMPAIGN requires CAMPAIGN_ID only.", text)
        self.assertIn("CAMPAIGN_STATUS requires exactly one CAMPAIGN_ID and no write fields.", text)
        self.assertIn("Duplicate scalar command fields are not allowed.", text)


if __name__ == "__main__":
    unittest.main()
