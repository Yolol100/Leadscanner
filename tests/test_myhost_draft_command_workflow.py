import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "myhost-draft-command.yml"
SCRIPT = ROOT / "scripts" / "outreach_queue_imap_draft.py"


class MyhostDraftCommandWorkflowTests(unittest.TestCase):
    def test_command_is_owner_only_issue_trigger(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        trigger = text.split("permissions:", 1)[0]
        self.assertIn("issues:", trigger)
        self.assertIn("types: [opened]", trigger)
        self.assertNotIn("push:", trigger)
        self.assertNotIn("schedule:", trigger)
        self.assertNotIn("workflow_dispatch:", trigger)
        self.assertIn("github.actor == 'Yolol100'", text)
        self.assertIn("CREATE MYHOST DRAFT", text)
        self.assertIn("COMMAND=CREATE_MYHOST_DRAFT", text)

    def test_command_is_draft_only(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("scripts/outreach_queue_imap_draft.py", workflow)
        self.assertNotIn("outreach_direct_smtp_runtime.py", workflow)
        self.assertNotIn("outreach-smtp.yml", workflow)
        self.assertNotIn("actions: write", workflow)
        self.assertNotIn("smtplib", script)
        self.assertIn("append_verified_draft", script)
        self.assertIn("self_only=False", script)
        self.assertIn("compliance_status is not approved", script)
        self.assertIn("recipient is suppressed", script)

    def test_command_does_not_put_message_content_in_issue(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("LEAD_ID=", text)
        self.assertNotIn("SUBJECT=", text)
        self.assertNotIn("BODY=", text)
        self.assertNotIn("RECIPIENT=", text)
        self.assertIn("SMTP_SEND=not_invoked", text)

    def test_remote_actions_are_sha_pinned(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        for raw in text.splitlines():
            stripped = raw.strip()
            if stripped.startswith("uses:") and not stripped.split("uses:", 1)[1].strip().startswith("./"):
                target = stripped.split("uses:", 1)[1].strip().split()[0]
                self.assertRegex(target.rsplit("@", 1)[1], r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
