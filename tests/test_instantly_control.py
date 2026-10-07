import json
import tempfile
import unittest
from pathlib import Path

from instantly_control import (
    _activate,
    _campaign_leads,
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

        for status in (-1, -2, -3, -4, 11, 12, None, True):
            with self.subTest(status=status):
                client = ActivationClient(status)
                with self.assertRaisesRegex(ValueError, "verified_leads_only"):
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

    def test_stage_confirmation_binds_preview_token_and_campaign(self):
        args = {
            "preview_run_id": 123,
            "approval_token": "growth-aaaaaaaaaaaaaaaaaaaa@1111111111111111",
            "campaign_id": "campaign-1",
        }
        expected = (
            "EXECUTE stage_approved_lead "
            "123|growth-aaaaaaaaaaaaaaaaaaaa@1111111111111111|campaign-1"
        )
        self.assertEqual(expected_confirmation("stage_approved_lead", args), expected)

        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "stage-approved-confirm-001",
            "action": "stage_approved_lead",
            "args": args,
            "confirm": "EXECUTE stage_approved_lead campaign-1",
            "requested_by": "chatgpt",
        }
        with self.assertRaisesRegex(ValueError, "exact_confirmation_required"):
            execute_command(command, config(), FakeClient())

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

    def test_interest_readback_rejects_boolean_schema_drift(self):
        class BoolInterestClient:
            def list_leads(self, **kwargs):
                return {
                    "items": [{
                        "email": "lead@example.com",
                        "lt_interest_status": True,
                    }]
                }

        result = _wait_interest_status(
            BoolInterestClient(),
            lead_email="lead@example.com",
            interest_value=1,
            max_polls=1,
            sleep_fn=lambda _: None,
        )
        self.assertEqual(result["state"], "pending")

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

    def test_activation_lead_scan_rejects_repeated_cursor(self):
        class RepeatingClient:
            def __init__(self):
                self.calls = 0

            def list_leads(self, **kwargs):
                self.calls += 1
                if self.calls > 2:
                    raise AssertionError("cursor loop was not detected")
                return {
                    "items": [{"id": f"l{self.calls}", "verification_status": 1}],
                    "next_starting_after": "cursor-repeat",
                }

        with self.assertRaisesRegex(RuntimeError, "cursor_loop"):
            _campaign_leads(RepeatingClient(), "c1")

    def test_activation_lead_scan_rejects_non_list_items(self):
        class BadShapeClient:
            def list_leads(self, **kwargs):
                return {
                    "items": {"id": "not-a-list"},
                    "next_starting_after": None,
                }

        with self.assertRaisesRegex(RuntimeError, "items_must_be_list"):
            _campaign_leads(BadShapeClient(), "c1")

    def test_activation_lead_scan_rejects_empty_page_with_cursor(self):
        class EmptyCursorClient:
            def list_leads(self, **kwargs):
                return {
                    "items": [],
                    "next_starting_after": "cursor-still-present",
                }

        with self.assertRaisesRegex(RuntimeError, "empty_page_with_cursor"):
            _campaign_leads(EmptyCursorClient(), "c1")

    def test_activation_lead_scan_rejects_non_object_item(self):
        class BadItemClient:
            def list_leads(self, **kwargs):
                return {
                    "items": [{"id": "ok", "verification_status": 1}, "bad-item"],
                    "next_starting_after": None,
                }

        with self.assertRaisesRegex(RuntimeError, "item_must_be_object"):
            _campaign_leads(BadItemClient(), "c1")

    def test_write_payload_must_be_object_before_api_call(self):
        class CampaignClient:
            def get_campaign(self, campaign_id):
                return {"id": campaign_id, "status": 0}

            def _request(self, *args, **kwargs):
                raise AssertionError("malformed payload must not reach API")

        args = {
            "campaign_id": "c1",
            "payload": [["name", "Changed"]],
        }
        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "payload-type-invalid-001",
            "action": "update_campaign",
            "args": args,
            "confirm": expected_confirmation("update_campaign", args),
            "requested_by": "chatgpt",
        }
        with self.assertRaisesRegex(ValueError, "payload_must_be_object"):
            execute_command(command, config(), CampaignClient())

    def test_warmup_email_targets_must_be_list(self):
        args = {"emails": "sender@example.com"}
        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "warmup-type-invalid-001",
            "action": "enable_warmup",
            "args": args,
            "confirm": expected_confirmation("enable_warmup", args),
            "requested_by": "chatgpt",
        }

        class NoCall:
            def _request(self, *args, **kwargs):
                raise AssertionError("malformed email targets must not reach API")

        with self.assertRaisesRegex(ValueError, "emails_must_be_list"):
            execute_command(command, config(), NoCall())

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

    def test_update_campaign_rejects_active_campaign_before_patch(self):
        class ActiveCampaignClient:
            def __init__(self):
                self.calls = 0

            def get_campaign(self, campaign_id):
                self.calls += 1
                return {"id": campaign_id, "status": 1}

            def _request(self, *args, **kwargs):
                raise AssertionError("active campaign must not be patched")

        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "campaign-update-active-001",
            "action": "update_campaign",
            "args": {"campaign_id": "c1", "payload": {"name": "Changed"}},
            "confirm": "EXECUTE update_campaign c1",
            "requested_by": "chatgpt",
        }
        with self.assertRaisesRegex(ValueError, "draft_or_paused_before_update"):
            execute_command(command, config(), ActiveCampaignClient())

    def test_activation_rejects_boolean_sender_status(self):
        class ActivationClient:
            def get_campaign(self, campaign_id):
                return {
                    "id": campaign_id,
                    "status": 0,
                    "allow_risky_contacts": False,
                    "email_list": ["sender@example.com"],
                }

            def list_leads(self, **kwargs):
                return {
                    "items": [{"email": "lead@example.com", "verification_status": 1}],
                    "next_starting_after": None,
                }

            def _request(self, method, path, **kwargs):
                if method == "GET" and path.endswith("/sending-status"):
                    return {"summary": {"status": "campaign_draft"}}
                if method == "GET" and path == "/accounts/sender%40example.com":
                    return {"status": True}
                if method == "POST" and path.endswith("/activate"):
                    raise AssertionError("boolean sender status must not authorize activation")
                raise AssertionError((method, path, kwargs))

        with self.assertRaisesRegex(ValueError, "sender_accounts_active"):
            _activate(ActivationClient(), "c1")

    def test_activation_allows_verified_status_and_blocks_unknown_status(self):
        class ActivationClient:
            def __init__(self, verification_status):
                self.verification_status = verification_status
                self.activated = False

            def get_campaign(self, campaign_id):
                return {
                    "id": campaign_id,
                    "status": 1 if self.activated else 0,
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
                    return {"status": 1}
                if method == "POST" and path.endswith("/activate"):
                    self.activated = True
                    return {"accepted": True}
                raise AssertionError((method, path, kwargs))

        good = ActivationClient(1)
        result = _activate(good, "c1")
        self.assertTrue(good.activated)
        self.assertEqual(result["readback"]["status"], 1)

        unknown = ActivationClient(99)
        with self.assertRaisesRegex(ValueError, "verified_leads_only"):
            _activate(unknown, "c1")
        self.assertFalse(unknown.activated)

    def test_update_campaign_only_allows_draft_or_paused(self):
        class CampaignClient:
            def __init__(self, status):
                self.status = status
                self.patches = 0

            def get_campaign(self, campaign_id):
                return {"id": campaign_id, "status": self.status}

            def _request(self, method, path, **kwargs):
                if method == "PATCH" and path == "/campaigns/c1":
                    self.patches += 1
                    return {"id": "c1"}
                raise AssertionError((method, path, kwargs))

        for status in (0, 2):
            with self.subTest(allowed_status=status):
                client = CampaignClient(status)
                command = {
                    "schema_version": "leadscanner-instantly-command/1.0",
                    "command_id": f"campaign-update-allowed-{status}",
                    "action": "update_campaign",
                    "args": {"campaign_id": "c1", "payload": {"name": "Changed"}},
                    "confirm": "EXECUTE update_campaign c1",
                    "requested_by": "chatgpt",
                }
                result = execute_command(command, config(), client)
                self.assertEqual(result["status"], "green")
                self.assertEqual(client.patches, 1)

        for status in (1, 3, 4, -1):
            with self.subTest(blocked_status=status):
                client = CampaignClient(status)
                command = {
                    "schema_version": "leadscanner-instantly-command/1.0",
                    "command_id": f"campaign-update-blocked-{str(status).replace('-', 'neg')}",
                    "action": "update_campaign",
                    "args": {"campaign_id": "c1", "payload": {"name": "Changed"}},
                    "confirm": "EXECUTE update_campaign c1",
                    "requested_by": "chatgpt",
                }
                with self.assertRaisesRegex(ValueError, "draft_or_paused_before_update"):
                    execute_command(command, config(), client)
                self.assertEqual(client.patches, 0)

    def test_forward_confirmation_binds_uuid_recipient_and_sender(self):
        args = {
            "payload": {
                "reply_to_uuid": "email-1",
                "to_address_email_list": "target@example.com",
                "eaccount": "sender@example.com",
                "subject": "Fwd: Test",
                "include_original_body": True,
            }
        }
        expected = "EXECUTE forward_email email-1|target@example.com|sender@example.com"
        self.assertEqual(expected_confirmation("forward_email", args), expected)

        class NoCall:
            def _request(self, *args, **kwargs):
                raise AssertionError("unexpected API call")

        for confirm in (
            "EXECUTE forward_email email-1|other@example.com|sender@example.com",
            "EXECUTE forward_email email-1|target@example.com|other-sender@example.com",
        ):
            with self.subTest(confirm=confirm):
                command = {
                    "schema_version": "leadscanner-instantly-command/1.0",
                    "command_id": "forward-confirmation-mismatch-001",
                    "action": "forward_email",
                    "args": args,
                    "confirm": confirm,
                    "requested_by": "chatgpt",
                }
                with self.assertRaisesRegex(ValueError, "exact_confirmation_required"):
                    execute_command(command, config(), NoCall())

    def test_update_interest_accepts_null_and_rejects_wrong_type(self):
        class NullInterestClient:
            def _request(self, method, path, **kwargs):
                if (method, path) == ("POST", "/leads/update-interest-status"):
                    return {"message": "accepted"}
                raise AssertionError((method, path, kwargs))

            def list_leads(self, **kwargs):
                return {
                    "items": [{
                        "id": "l1",
                        "email": "lead@example.com",
                        "lt_interest_status": None,
                    }]
                }

        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "interest-null-001",
            "action": "update_interest",
            "args": {"payload": {"lead_email": "lead@example.com", "interest_value": None}},
            "confirm": "EXECUTE update_interest lead@example.com|null",
            "requested_by": "chatgpt",
        }
        result = execute_command(command, config(), NullInterestClient())
        self.assertEqual(result["result"]["completion_state"], "completed")

        class NoCall:
            def _request(self, *args, **kwargs):
                raise AssertionError("unexpected API call")

        invalid = dict(command)
        invalid["command_id"] = "interest-type-invalid-001"
        invalid["args"] = {"payload": {"lead_email": "lead@example.com", "interest_value": "2"}}
        invalid["confirm"] = "EXECUTE update_interest lead@example.com|2"
        with self.assertRaisesRegex(ValueError, "interest_value_must_be_number_or_null"):
            execute_command(invalid, config(), NoCall())

    def test_forward_contract_blocks_missing_recipient_or_body_before_api(self):
        class NoCall:
            def _request(self, *args, **kwargs):
                raise AssertionError("unexpected API call")

        cases = [
            (
                {
                    "reply_to_uuid": "email-1",
                    "eaccount": "sender@example.com",
                    "subject": "Fwd: Test",
                    "include_original_body": True,
                },
                "EXECUTE forward_email email-1|sender@example.com",
                "forward_recipient_required",
            ),
            (
                {
                    "reply_to_uuid": "email-1",
                    "to_address_email_list": "target@example.com",
                    "eaccount": "sender@example.com",
                    "subject": "Fwd: Test",
                },
                "EXECUTE forward_email email-1|target@example.com|sender@example.com",
                "forward_body_or_original_required",
            ),
        ]
        for payload, confirm, error in cases:
            with self.subTest(error=error):
                command = {
                    "schema_version": "leadscanner-instantly-command/1.0",
                    "command_id": "forward-invalid-contract-001",
                    "action": "forward_email",
                    "args": {"payload": payload},
                    "confirm": confirm,
                    "requested_by": "chatgpt",
                }
                with self.assertRaisesRegex(ValueError, error):
                    execute_command(command, config(), NoCall())

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

    def test_command_args_wrong_type_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-args-001.json"
            path.write_text(
                json.dumps({
                    "schema_version": "leadscanner-instantly-command/1.0",
                    "command_id": "bad-args-001",
                    "action": "list_campaigns",
                    "args": [],
                }),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "command_args_must_be_object"):
                load_command(path)

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
