import json
import tempfile
import unittest
from pathlib import Path

from instantly_control import (
    _activate,
    _wait_background_job,
    _wait_interest_status,
    _write,
    command_paths_from_push_event,
    execute_command,
    expected_confirmation,
    load_command,
)


def config(**overrides):
    value = {
        "schema_version": "leadscanner-instantly-control/1.0",
        "write_actions_enabled": True,
        "send_actions_enabled": True,
        "destructive_actions_enabled": True,
        "require_exact_confirmation": True,
    }
    value.update(overrides)
    return value


class FakeClient:
    def __init__(self):
        self.calls = []

    def list_campaigns(self, **kwargs):
        self.calls.append(("list_campaigns", kwargs))
        return {
            "items": [{
                "id": "c1",
                "name": "Draft",
                "status": 0,
                "sequences": [{"steps": [{"body": "must-not-leak"}]}],
            }],
            "next_starting_after": None,
        }


class InstantlyControlTests(unittest.TestCase):
    def test_read_command_does_not_require_confirmation(self):
        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "read-campaigns-001",
            "action": "list_campaigns",
            "args": {"limit": 10},
            "confirm": "",
            "requested_by": "chatgpt",
        }
        client = FakeClient()
        result = execute_command(command, config(), client)
        self.assertEqual(result["status"], "green")
        self.assertEqual(result["mode"], "read")
        self.assertEqual(client.calls[0][1]["limit"], 10)
        self.assertEqual(result["result"]["items"][0]["id"], "c1")
        self.assertNotIn("sequences", result["result"]["items"][0])

    def test_write_requires_exact_target_bound_confirmation(self):
        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "pause-campaign-001",
            "action": "pause_campaign",
            "args": {"campaign_id": "c1"},
            "confirm": "yes",
            "requested_by": "chatgpt",
        }
        with self.assertRaisesRegex(ValueError, "exact_confirmation_required:EXECUTE pause_campaign c1"):
            execute_command(command, config(), FakeClient())

    def test_workflow_rerun_blocks_every_write(self):
        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "pause-campaign-002",
            "action": "pause_campaign",
            "args": {"campaign_id": "c1"},
            "confirm": "EXECUTE pause_campaign c1",
            "requested_by": "chatgpt",
        }
        with self.assertRaisesRegex(RuntimeError, "cannot_run_on_workflow_rerun"):
            execute_command(command, config(), FakeClient(), run_attempt="2")

    def test_account_secret_material_is_rejected_from_committed_command(self):
        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "account-update-001",
            "action": "update_account",
            "args": {
                "email": "sender@example.com",
                "payload": {"smtp_password": "must-not-be-committed"},
            },
            "confirm": "EXECUTE update_account sender@example.com",
            "requested_by": "chatgpt",
        }
        with self.assertRaisesRegex(ValueError, "secret_material"):
            execute_command(command, config(), FakeClient())

    def test_send_and_warmup_confirmations_are_bound_to_targets(self):
        self.assertEqual(
            expected_confirmation(
                "send_test_email",
                {"payload": {
                    "eaccount": "sender@example.com",
                    "to_address_email_list": "target@example.com",
                }},
            ),
            "EXECUTE send_test_email sender@example.com|target@example.com",
        )
        self.assertEqual(
            expected_confirmation(
                "enable_warmup",
                {"emails": ["B@example.com", "a@example.com"]},
            ),
            "EXECUTE enable_warmup a@example.com,b@example.com",
        )

    def test_nested_account_secret_material_is_rejected(self):
        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "account-update-002",
            "action": "update_account",
            "args": {
                "email": "sender@example.com",
                "payload": {"advanced": {"smtp_password": "must-not-be-committed"}},
            },
            "confirm": "EXECUTE update_account sender@example.com",
            "requested_by": "chatgpt",
        }
        with self.assertRaisesRegex(ValueError, "secret_material"):
            execute_command(command, config(), FakeClient())

    def test_activation_blocks_documented_nonverified_statuses(self):
        class ActivationClient:
            def __init__(self, verification_status):
                self.verification_status = verification_status
                self.activated = False

            def get_campaign(self, campaign_id):
                return {
                    "id": campaign_id,
                    "status": 0,
                    "allow_risky_contacts": False,
                    "email_list": ["sender@example.com"],
                }

            def list_leads(self, **kwargs):
                return {
                    "items": [{
                        "id": "l1",
                        "email": "lead@example.com",
                        "verification_status": self.verification_status,
                    }],
                    "next_starting_after": None,
                }

            def _request(self, method, path, **kwargs):
                if method == "GET" and path.endswith("/sending-status"):
                    return {"summary": {"status": "campaign_draft"}}
                if method == "GET" and path == "/accounts/sender%40example.com":
                    return {"email": "sender@example.com", "status": 1}
                if method == "POST" and path.endswith("/activate"):
                    self.activated = True
                    return {}
                raise AssertionError((method, path, kwargs))

        for status in (-1, -2, -3, -4, 11, 12):
            with self.subTest(status=status):
                client = ActivationClient(status)
                with self.assertRaisesRegex(ValueError, "requires_non_pending_non_risky_verification"):
                    _activate(client, "c1")
                self.assertFalse(client.activated)

    def test_load_command_rejects_secret_shaped_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secret-command-001.json"
            path.write_text(
                json.dumps({
                    "schema_version": "leadscanner-instantly-command/1.0",
                    "command_id": "secret-command-001",
                    "action": "update_account",
                    "args": {
                        "email": "sender@example.com",
                        "payload": {"nested": {"api_key": "do-not-store"}},
                    },
                    "confirm": "EXECUTE update_account sender@example.com",
                }),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "command_secret_material_forbidden"):
                load_command(path)

    def test_leadscanner_approval_token_is_allowed_in_command_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stage-approved-001.json"
            path.write_text(
                json.dumps({
                    "schema_version": "leadscanner-instantly-command/1.0",
                    "command_id": "stage-approved-001",
                    "action": "stage_approved_lead",
                    "args": {
                        "preview_run_id": 123,
                        "approval_token": "growth-aaaaaaaaaaaaaaaaaaaa@1111111111111111",
                        "campaign_id": "campaign-1",
                    },
                    "confirm": "EXECUTE stage_approved_lead campaign-1",
                }),
                encoding="utf-8",
            )
            loaded = load_command(path)
            self.assertEqual(
                loaded["args"]["approval_token"],
                "growth-aaaaaaaaaaaaaaaaaaaa@1111111111111111",
            )

    def test_result_writer_redacts_nested_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.json"
            _write(path, {
                "status": "green",
                "result": {
                    "email": "sender@example.com",
                    "advanced": {"smtp_password": "private", "access_token": "private-2"},
                },
            })
            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(written["result"]["advanced"]["smtp_password"], "[REDACTED]")
            self.assertEqual(written["result"]["advanced"]["access_token"], "[REDACTED]")
            self.assertEqual(written["result"]["email"], "sender@example.com")

    def test_test_send_200_error_body_fails_closed(self):
        class ActionClient:
            def _request(self, method, path, **kwargs):
                self.last = (method, path, kwargs)
                return {"error": "ACC_AUTH_ERROR"}

        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "test-send-error-001",
            "action": "send_test_email",
            "args": {
                "payload": {
                    "eaccount": "sender@example.com",
                    "to_address_email_list": "target@example.com",
                    "subject": "Test",
                    "body": {"html": "<p>Test</p>"},
                }
            },
            "confirm": "EXECUTE send_test_email sender@example.com|target@example.com",
            "requested_by": "chatgpt",
        }
        with self.assertRaisesRegex(RuntimeError, "instantly_test_send_error:ACC_AUTH_ERROR"):
            execute_command(command, config(), ActionClient())

    def test_background_job_waits_until_success(self):
        class JobClient:
            def __init__(self):
                self.states = ["processing", "success"]

            def _request(self, method, path, **kwargs):
                return {"id": "job-1", "status": self.states.pop(0)}

        sleeps = []
        result = _wait_background_job(
            JobClient(),
            {"id": "job-1"},
            max_polls=3,
            sleep_fn=sleeps.append,
        )
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["job"]["status"], "success")
        self.assertEqual(sleeps, [1.0])

    def test_background_job_can_remain_pending_after_bounded_poll(self):
        class JobClient:
            def _request(self, method, path, **kwargs):
                return {"id": "job-2", "status": "processing"}

        result = _wait_background_job(
            JobClient(),
            {"id": "job-2"},
            max_polls=2,
            sleep_fn=lambda _: None,
        )
        self.assertEqual(result["state"], "pending")
        self.assertEqual(result["job"]["status"], "processing")

    def test_update_interest_confirmation_binds_email_and_value(self):
        self.assertEqual(
            expected_confirmation(
                "update_interest",
                {"payload": {"lead_email": "Lead@Example.com", "interest_value": 2}},
            ),
            "EXECUTE update_interest lead@example.com|2",
        )

    def test_update_interest_async_readback_can_complete(self):
        class InterestClient:
            def __init__(self):
                self.reads = 0

            def _request(self, method, path, **kwargs):
                if (method, path) == ("POST", "/leads/update-interest-status"):
                    return {"message": "accepted"}
                raise AssertionError((method, path, kwargs))

            def list_leads(self, **kwargs):
                self.reads += 1
                return {
                    "items": [{
                        "id": "l1",
                        "email": "lead@example.com",
                        "lt_interest_status": 0 if self.reads == 1 else 2,
                    }]
                }

        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "interest-update-001",
            "action": "update_interest",
            "args": {"payload": {"lead_email": "lead@example.com", "interest_value": 2}},
            "confirm": "EXECUTE update_interest lead@example.com|2",
            "requested_by": "chatgpt",
        }
        result = execute_command(command, config(), InterestClient())
        self.assertEqual(result["result"]["completion_state"], "completed")
        self.assertEqual(result["result"]["readback"][0]["lt_interest_status"], 2)

    def test_interest_readback_is_bounded_and_can_remain_pending(self):
        class PendingClient:
            def list_leads(self, **kwargs):
                return {"items": [{"email": "lead@example.com", "lt_interest_status": 0}]}

        result = _wait_interest_status(
            PendingClient(),
            lead_email="lead@example.com",
            interest_value=1,
            max_polls=2,
            sleep_fn=lambda _: None,
        )
        self.assertEqual(result["state"], "pending")

    def test_update_interest_rejects_invalid_payload_before_api_call(self):
        class NoCall:
            def _request(self, *args, **kwargs):
                raise AssertionError("unexpected API call")

        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "interest-invalid-001",
            "action": "update_interest",
            "args": {"payload": {"lead_email": "lead@example.com"}},
            "confirm": "EXECUTE update_interest lead@example.com",
            "requested_by": "chatgpt",
        }
        with self.assertRaisesRegex(ValueError, "interest_value_required"):
            execute_command(command, config(), NoCall())

    def test_email_write_contracts_fail_closed_on_missing_required_fields(self):
        class NoCall:
            def _request(self, *args, **kwargs):
                raise AssertionError("unexpected API call")

        reply = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "reply-invalid-001",
            "action": "reply_email",
            "args": {"payload": {
                "reply_to_uuid": "email-1",
                "eaccount": "sender@example.com",
                "subject": "Re: hi",
            }},
            "confirm": "EXECUTE reply_email email-1|sender@example.com",
            "requested_by": "chatgpt",
        }
        with self.assertRaisesRegex(ValueError, "reply_body_required"):
            execute_command(reply, config(), NoCall())

        test_send = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "test-invalid-001",
            "action": "send_test_email",
            "args": {"payload": {
                "eaccount": "sender@example.com",
                "to_address_email_list": "target@example.com",
                "subject": "Test",
            }},
            "confirm": "EXECUTE send_test_email sender@example.com|target@example.com",
            "requested_by": "chatgpt",
        }
        with self.assertRaisesRegex(ValueError, "test_body_required"):
            execute_command(test_send, config(), NoCall())

    def test_activation_blocks_all_accounts_unhealthy_reason(self):
        class ActivationClient:
            def get_campaign(self, campaign_id):
                return {
                    "id": campaign_id,
                    "status": 0,
                    "allow_risky_contacts": False,
                    "email_list": ["sender@example.com"],
                }

            def list_leads(self, **kwargs):
                return {"items": [{"email": "lead@example.com", "verification_status": 1}]}

            def _request(self, method, path, **kwargs):
                if method == "GET" and path.endswith("/sending-status"):
                    return {"diagnostics": {"status": "all_accounts_unhealthy"}}
                if method == "GET" and path == "/accounts/sender%40example.com":
                    return {"status": 1}
                if method == "POST" and path.endswith("/activate"):
                    raise AssertionError("activation must be blocked")
                raise AssertionError((method, path, kwargs))

        with self.assertRaisesRegex(ValueError, "all_accounts_unhealthy"):
            _activate(ActivationClient(), "c1")

    def test_push_event_executes_only_new_inbox_json_files(self):
        event = {
            "commits": [
                {
                    "added": [
                        "instantly-commands/inbox/one-command.json",
                        "scripts/instantly_control.py",
                    ],
                    "modified": ["instantly-commands/inbox/old-command.json"],
                },
                {
                    "added": [
                        "instantly-commands/inbox/one-command.json",
                        "instantly-commands/inbox/two-command.json",
                    ]
                },
            ]
        }
        paths = command_paths_from_push_event(event)
        self.assertEqual(
            [str(path) for path in paths],
            [
                "instantly-commands/inbox/one-command.json",
                "instantly-commands/inbox/two-command.json",
            ],
        )

    def test_command_id_must_match_file_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "right-name-001.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "leadscanner-instantly-command/1.0",
                        "command_id": "wrong-name-001",
                        "action": "list_campaigns",
                        "args": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "must_match_filename"):
                load_command(path)


if __name__ == "__main__":
    unittest.main()
