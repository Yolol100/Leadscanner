"""No-network regression tests for ChatGPT on-demand Leadscanner commands."""
import copy
import unittest
from unittest.mock import patch

import leads_chat_command as command


def event(mode="CHECK"):
    return {
        "action": "created",
        "repository": {"full_name": "Yolol100/Leadscanner"},
        "issue": {"number": 1720},
        "comment": {"user": {"login": "Yolol100"},
                    "body": "LEADS_CHAT_V1:" + mode},
    }


class ChatCommandTests(unittest.TestCase):
    def test_all_explicit_modes_accepted(self):
        for mode in sorted(command.MODES):
            with self.subTest(mode=mode):
                self.assertEqual(command.validate(event(mode)), mode)

    def test_reject_foreign_actor_issue_repo_and_pr(self):
        cases = [
            ("comment", "user", {"login": "untrusted"}),
            ("issue", "number", 1659),
            ("issue", "pull_request", {"url": "some-pr"}),
            ("repository", "full_name", "other/repository"),
        ]
        for top, field, value in cases:
            with self.subTest(case=field):
                changed = copy.deepcopy(event())
                changed[top][field] = value
                with self.assertRaises(ValueError):
                    command.validate(changed)

    def test_reject_non_create_and_wrong_event(self):
        changed = event()
        changed["action"] = "edited"
        with self.assertRaises(ValueError):
            command.validate(changed)
        with self.assertRaises(ValueError):
            command.validate(event(), event_name="push")

    def test_reject_malformed_untrusted_command(self):
        for value in [
            "LEADS_CHAT_V1:EVIDENCE\nrun: malicious",
            "LEADS_CHAT_V1:EVIDENCE;echo malicious",
            "LEADS_CHAT_V1:EVIDENCE ",
            "LEADS_CHAT_V1:SMTP",
            "LEADS_CHAT_V1:FILL_999",
            "LEADS_DRAFT_ONLY:fake",
        ]:
            with self.subTest(value=value):
                changed = event()
                changed["comment"]["body"] = value
                with self.assertRaises(ValueError):
                    command.validate(changed)

    def test_preflight_only_reads_private_suppression(self):
        with patch("registry_readonly.load_suppressions", return_value=[1, 2]) as read, \
             patch.object(command.subprocess, "run") as run:
            command.execute("CHECK")
        read.assert_called_once()
        run.assert_not_called()

    def test_preflight_fails_closed_on_incomplete_register(self):
        with patch("registry_readonly.load_suppressions", return_value=[1]):
            with self.assertRaises(RuntimeError):
                command.execute("CHECK")

    def test_evidence_always_forces_approved_no_mail(self):
        with patch.object(command.subprocess, "run") as run:
            command.execute("EVIDENCE")
        args = run.call_args.args[0]
        self.assertEqual(args[1:],
            ["scripts/fast_website_evidence.py",
             "--source", "Approved", "--batch", "1", "--force"])
        self.assertTrue(run.call_args.kwargs["check"])

    def test_discovery_is_bounded_private_handoff_only(self):
        for mode, max_count in [("HINTS_10", "10"), ("HINTS_30", "30"),
                                ("HINTS_50", "50"), ("HINTS_100", "100")]:
            with self.subTest(mode=mode), patch.object(command.subprocess, "run") as run:
                command.execute(mode)
                args = run.call_args.args[0]
                self.assertEqual(args[1], "scripts/new_leads.py")
                self.assertIn(max_count, args)
                self.assertIn("--private-handoff", args)
                self.assertIn("--summary-only", args)
                self.assertNotIn("--send", args)

    def test_verified_discovery_has_no_mail_sender(self):
        with patch.object(command.subprocess, "run") as run:
            command.execute("VERIFIED_100")
        self.assertEqual(run.call_args.args[0][1:], ["scripts/verified_fill.py"])

    def test_execute_invalid_mode_fails_before_subprocess(self):
        with patch.object(command.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                command.execute("SEND")
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
