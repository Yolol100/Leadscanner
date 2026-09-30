from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from run_mailbox_bridge import load_request, validate_request


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "mailbox-execute.yml"


class MailboxBridgeRuntimeTests(unittest.TestCase):
    def test_read_action_allowed(self):
        self.assertEqual(validate_request({"action": "list_folders"}), "list_folders")

    def test_send_requires_explicit_confirmation(self):
        with self.assertRaises(ValueError):
            validate_request({"action": "send"})
        self.assertEqual(
            validate_request({"action": "send", "confirm_send": True}),
            "send",
        )

    def test_destructive_action_requires_confirmation(self):
        with self.assertRaises(ValueError):
            validate_request({"action": "delete", "folder": "INBOX", "uid": "7"})
        self.assertEqual(
            validate_request(
                {"action": "delete", "folder": "INBOX", "uid": "7", "confirm": True}
            ),
            "delete",
        )

    def test_unknown_action_rejected(self):
        with self.assertRaises(ValueError):
            validate_request({"action": "shell"})

    def test_request_size_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "request.json"
            path.write_text(json.dumps({"action": "list_folders"}), encoding="utf-8")
            self.assertEqual(load_request(path)["action"], "list_folders")
            path.write_bytes(b"x" * 262_145)
            with self.assertRaises(ValueError):
                load_request(path)

    def test_public_workflow_keeps_mail_payload_private(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        required = (
            "github.event.issue.user.login == github.repository_owner",
            "startsWith(github.event.issue.title, '[mailbox-execute]')",
            "id-token: write",
            "repository: Yolol100/myhost-mailbox",
            "ref: 9a02f94191fb19c5bbc42f6acecd806e411d2603",
            "https://andrewbaeten.nl",
            "secrets.OUTREACH_MAIL_PASSWORD",
            "vars.OUTREACH_SMTP_SEND_ENABLED || 'false'",
            "MAILBOX_PRIVATE_REQUEST=green",
            "MAILBOX_PRIVATE_RESULT=green",
            'set(request) != {"request_id"}',
            'json.dumps(request, ensure_ascii=True, separators=(",", ":"))',
            'rm -rf "$RUNNER_TEMP/mailbox"',
        )
        for needle in required:
            self.assertIn(needle, text)

        forbidden = (
            "actions/upload-artifact",
            "cat $RUNNER_TEMP/mailbox/request.json",
            "cat $RUNNER_TEMP/mailbox/result.json",
            "tee $RUNNER_TEMP/mailbox",
            "OUTREACH_SMTP_SEND_ENABLED: true",
        )
        for needle in forbidden:
            self.assertNotIn(needle, text)

        self.assertGreaterEqual(text.count("ACTIONS_ID_TOKEN_REQUEST_URL"), 2)


if __name__ == "__main__":
    unittest.main()
