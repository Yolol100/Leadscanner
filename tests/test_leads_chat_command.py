"""No-network regression tests for ChatGPT on-demand Leadscanner commands."""
import copy
import json
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


REQUEST_ID = "r-" + "a" * 32
ALT_ID = "r-" + "b" * 32


def versioned_event(mode="HINTS_10", request_id=REQUEST_ID, *, comment_id=500):
    result = event(mode)
    result["comment"]["id"] = comment_id
    result["comment"]["body"] = f"LEADS_CHAT_V2:{mode}:{request_id}"
    return result


def history_row(event):
    return copy.deepcopy(event["comment"])


class ChatCommandTests(unittest.TestCase):
    def test_read_only_legacy_modes_accepted(self):
        for mode in sorted(command.MODES - command.REQUIRES_ID):
            with self.subTest(mode=mode):
                self.assertEqual(command.validate(event(mode)), mode)

    def test_write_modes_require_opaque_versioned_ids(self):
        for mode in sorted(command.REQUIRES_ID):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(ValueError, "request_id_required"):
                    command.validate(event(mode))
                current = event()
                current["comment"]["body"] = "LEADS_CHAT_V2:" + mode + ":" + REQUEST_ID
                self.assertEqual(command.validate(current), mode)

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
        with patch("registry_readonly.load_discovery_suppressions", return_value=[1, 2]) as read, \
             patch.object(command.subprocess, "run") as run:
            command.execute("CHECK")
        read.assert_called_once()
        run.assert_not_called()

    def test_preflight_fails_closed_on_incomplete_register(self):
        with patch("registry_readonly.load_discovery_suppressions", return_value=[1]):
            with self.assertRaises(RuntimeError):
                command.execute("CHECK")

    def test_check_fails_closed_if_any_discovery_suppression_source_is_missing(self):
        for reason in ("historical_v2_incomplete", "lead_history_headers_invalid",
                       "draft_queue_registry_headers_invalid"):
            with self.subTest(reason=reason):
                with patch("registry_readonly.load_discovery_suppressions",
                           side_effect=RuntimeError(reason)) as loader, \
                     patch.object(command.subprocess, "run") as run:
                    with self.assertRaises(RuntimeError):
                        command.execute("CHECK")
                loader.assert_called_once()
                run.assert_not_called()

    def test_read_only_mailbox_audit_is_only_existing_inventory(self):
        with patch.object(command.subprocess, "run") as run:
            command.execute("DRAFTS_AUDIT")
        self.assertEqual(run.call_args.args[0][1:],
                         ["scripts/live_450_draft_inventory.py"])
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertNotIn("--install", run.call_args.args[0])

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

    def test_versioned_command_schema_fails_closed(self):
        invalid = (
            "LEADS_CHAT_V2:HINTS_10",
            "LEADS_CHAT_V2:HINTS_10:r-" + "G" * 32,
            "LEADS_CHAT_V2:HINTS_10:r-" + "a" * 31,
            "LEADS_CHAT_V2:HINTS_10:" + REQUEST_ID + ":extra",
            "LEADS_CHAT_V2:CHECK:" + REQUEST_ID,
            "LEADS_CHAT_V2:HINTS_10:" + REQUEST_ID + "\\nsecret",
            "LEADS_CHAT_V2:SMTP:" + REQUEST_ID,
        )
        for raw in invalid:
            with self.subTest(raw=raw):
                test = versioned_event()
                test["comment"]["body"] = raw
                with self.assertRaises(ValueError):
                    command.validate(test)

    def test_identical_prior_request_is_noop(self):
        first = versioned_event(comment_id=100)
        retry = versioned_event(comment_id=101)
        self.assertFalse(command.authorize_once(retry, [
            history_row(first), history_row(retry)
        ]))

    def test_first_request_runs_and_later_independent_request_runs(self):
        first = versioned_event(comment_id=100)
        independent = versioned_event(request_id=ALT_ID, comment_id=101)
        data = [history_row(first), history_row(independent)]
        self.assertTrue(command.authorize_once(first, data))
        self.assertTrue(command.authorize_once(independent, data))

    def test_conflicting_reused_id_fails_closed(self):
        first = versioned_event("HINTS_10", comment_id=100)
        changed = versioned_event("HINTS_30", comment_id=101)
        with self.assertRaisesRegex(RuntimeError, "request_id_conflict"):
            command.authorize_once(changed, [history_row(first), history_row(changed)])

    def test_missing_comment_or_changed_immutable_history_blocks(self):
        current = versioned_event()
        with self.assertRaisesRegex(RuntimeError, "history_current_missing"):
            command.authorize_once(current, [])
        bad = history_row(current)
        bad["body"] = "LEADS_CHAT_V2:HINTS_30:" + REQUEST_ID
        with self.assertRaisesRegex(RuntimeError, "history_current_missing"):
            command.authorize_once(current, [bad])

    def test_github_rerun_never_discover_again(self):
        current = versioned_event()
        self.assertFalse(command.authorize_once(current, [history_row(current)], attempt=2))

    def test_missing_private_github_history_token_blocks(self):
        with patch.dict("os.environ", {"GITHUB_TOKEN": ""}):
            with self.assertRaisesRegex(RuntimeError, "history_token_missing"):
                command.list_issue_comments()

    def test_main_duplicate_and_rerun_skip_without_any_subprocess(self):
        current = versioned_event()
        previous = versioned_event(comment_id=100)
        with patch.dict("os.environ", {
                "GITHUB_EVENT_PATH": "/no-file-reads-in-test",
                "GITHUB_EVENT_NAME": "issue_comment",
                "GITHUB_RUN_ATTEMPT": "1",
            }), patch("pathlib.Path.read_text", return_value=json.dumps(current)), \
             patch.object(command, "list_issue_comments",
                          return_value=[history_row(previous), history_row(current)]), \
             patch.object(command, "execute") as executor:
            self.assertEqual(command.main(), 0)
            executor.assert_not_called()
        with patch.dict("os.environ", {
                "GITHUB_EVENT_PATH": "/no-file-reads-in-test",
                "GITHUB_EVENT_NAME": "issue_comment",
                "GITHUB_RUN_ATTEMPT": "2",
            }), patch("pathlib.Path.read_text", return_value=json.dumps(current)), \
             patch.object(command, "list_issue_comments") as history, \
             patch.object(command, "execute") as executor:
            self.assertEqual(command.main(), 0)
            executor.assert_not_called()
            history.assert_not_called()

    def test_list_history_only_reads_github_rest_without_writes(self):
        current = versioned_event()
        mock_response = unittest.mock.Mock(status_code=200)
        mock_response.json.return_value = [history_row(current)]
        client = unittest.mock.MagicMock()
        client.get.return_value = mock_response
        handle = unittest.mock.MagicMock()
        handle.__enter__.return_value = client
        with patch.dict("os.environ", {"GITHUB_TOKEN": "synthetic-test-token"}), \
             patch("requests.Session", return_value=handle):
            entries = command.list_issue_comments()
        self.assertEqual(len(entries), 1)
        client.get.assert_called_once()
        self.assertEqual(client.get.call_args.kwargs["timeout"], 20)
        self.assertFalse(client.post.called)
        self.assertFalse(client.patch.called)


if __name__ == "__main__":
    unittest.main()
