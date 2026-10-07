import json
import tempfile
import unittest
from pathlib import Path

from instantly_control import (
    _activate,
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
