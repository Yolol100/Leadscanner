import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from instantly_client import InstantlyError, inspect_campaign_sequence
from instantly_control import (
    _activate,
    _activation_leadset_fingerprint,
    _campaign_leads,
    _verify_email,
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



class ActivationGuardClient:
    """Provider double: never sends or touches a real Instantly campaign."""
    def __init__(self, *, basis=None, reference=None, mutate=False, status=0, campaign_id="c1"):
        self.activated = False
        self.get_count = 0
        self.mutate = mutate
        self.status = status
        self.campaign_id = campaign_id
        self.posts = 0
        self.variables = {
            "leadscanner_lead_id": "growth-aaaaaaaaaaaaaaaaaaaa",
            "leadscanner_observation": "Verified website fact",
            "leadscanner_value_action": "Small example",
        }
        if basis is not None:
            self.variables["leadscanner_contact_basis"] = basis
        if reference is not None:
            self.variables["leadscanner_contact_basis_ref"] = reference

    def get_campaign(self, campaign_id):
        self.get_count += 1
        steps = [
            {"type": "email", "variants": [{
                "subject": "Step 1", "body": "Seen {{leadscanner_observation}}",
            }]},
            {"type": "email", "variants": [{
                "subject": "Step 2", "body": "Propose {{leadscanner_value_action}}",
            }]},
            {"type": "email", "variants": [{
                "subject": "Step 3", "body": "Thanks for considering this",
            }]},
        ]
        if self.mutate and self.get_count > 2 and not self.activated:
            steps[1]["variants"][0]["body"] += " CHANGED"
        return {
            "id": self.campaign_id,
            "status": 1 if self.activated else self.status,
            "allow_risky_contacts": False,
            "email_list": ["sender@example.com"],
            "sequences": [{"steps": steps}],
        }

    def list_leads(self, **kwargs):
        return {
            "items": [{
                "id": "l1", "email": "lead@example.com",
                "verification_status": 1,
                "payload": dict(self.variables),
            }],
            "next_starting_after": None,
        }

    def _request(self, method, path, **kwargs):
        if method == "GET" and path.endswith("/sending-status"):
            return {"summary": {"status": "campaign_draft"}}
        if method == "GET" and path == "/accounts/sender%40example.com":
            return {"status": 1}
        if method == "POST" and path == "/campaigns/c1/activate":
            self.posts += 1
            self.activated = True
            return {"accepted": True}
        raise AssertionError((method, path, kwargs))


def activation_registry_rows(status="instantly_staged"):
    return [{
        "identity": {
            "emails": {"lead@example.com"},
            "lead_ids": {"growth-aaaaaaaaaaaaaaaaaaaa"},
        },
        "status": status,
        "row_number": 2,
    }]


def activation_approval_for(client):
    campaign = client.get_campaign("c1")
    report = inspect_campaign_sequence(campaign)
    return (
        "APPROVE_INSTANTLY_ACTIVATION c1 " + report["sequence_fingerprint"]
        + " " + _activation_leadset_fingerprint(client.list_leads()["items"])
    )


class InstantlyControlTests(unittest.TestCase):

    def test_activation_of_leadscanner_campaign_requires_fresh_sequence_approval(self):
        client = ActivationGuardClient(
            basis="consent_verified", reference="crm:consent-2026-123",
        )
        with self.assertRaisesRegex(ValueError, "activation_sequence_approval_required_or_stale"):
            _activate(client, "c1")
        self.assertEqual(client.posts, 0)

    def test_activation_rejects_unverified_public_contact_basis(self):
        for basis, reference in (
            (None, None),
            ("public_business_email", "crm:public-website-123"),
            ("consent_verified", None),
            ("consent_verified", "x"),
            ("existing_customer_related_verified", ""),
        ):
            with self.subTest(basis=basis, reference=reference):
                client = ActivationGuardClient(basis=basis, reference=reference)
                approval = activation_approval_for(client)
                with self.assertRaisesRegex(ValueError, "activation_requires_documented_contact_permission"):
                    _activate(client, "c1", activation_approval=approval)
                self.assertEqual(client.posts, 0)

    @patch("instantly_control.fetch_live_registry")
    def test_activation_with_documented_basis_and_exact_fingerprint(self, registry_mock):
        registry_mock.return_value = activation_registry_rows()
        for basis in ("consent_verified", "existing_customer_related_verified"):
            with self.subTest(basis=basis):
                client = ActivationGuardClient(basis=basis, reference="crm:permission-2026-123")
                approval = activation_approval_for(client)
                with patch("instantly_control.blocked_values", return_value=set()):
                    result = _activate(client, "c1", activation_approval=approval)
                self.assertEqual(client.posts, 1)
                self.assertEqual(result["readback"]["status"], 1)

    @patch("instantly_control.fetch_live_registry")
    def test_activation_blocks_provider_suppressed_address(self, registry_mock):
        registry_mock.return_value = activation_registry_rows()
        client = ActivationGuardClient(
            basis="consent_verified", reference="crm:permission-2026-123",
        )
        approval = activation_approval_for(client)
        with patch("instantly_control.blocked_values", return_value={"lead@example.com"}):
            with self.assertRaisesRegex(ValueError, "activation_provider_blocklist_match"):
                _activate(client, "c1", activation_approval=approval)
        self.assertEqual(client.posts, 0)

    @patch("instantly_control.fetch_live_registry")
    def test_activation_blocks_provider_domain_and_subdomain_suppression(self, registry_mock):
        registry_mock.return_value = activation_registry_rows()
        client = ActivationGuardClient(
            basis="consent_verified", reference="crm:permission-2026-123",
        )
        approval = activation_approval_for(client)
        with patch("instantly_control.blocked_values", return_value={"example.com"}):
            with self.assertRaisesRegex(ValueError, "activation_provider_blocklist_match"):
                _activate(client, "c1", activation_approval=approval)
        self.assertEqual(client.posts, 0)

    @patch("instantly_control.fetch_live_registry")
    def test_activation_fails_closed_when_provider_blocklist_unavailable(self, registry_mock):
        registry_mock.return_value = activation_registry_rows()
        client = ActivationGuardClient(
            basis="consent_verified", reference="crm:permission-2026-123",
        )
        approval = activation_approval_for(client)
        with patch("instantly_control.blocked_values", side_effect=InstantlyError("instantly_network_error")):
            with self.assertRaisesRegex(RuntimeError, "activation_blocklist_unavailable"):
                _activate(client, "c1", activation_approval=approval)
        self.assertEqual(client.posts, 0)

    @patch("instantly_control.fetch_live_registry")
    def test_activation_rejects_sequence_mutation_during_preflight(self, registry_mock):
        registry_mock.return_value = activation_registry_rows()
        client = ActivationGuardClient(
            basis="consent_verified", reference="crm:consent-2026-123", mutate=True,
        )
        approval = activation_approval_for(client)
        with self.assertRaisesRegex(ValueError, "campaign_changed_during_activation_preflight"):
            _activate(client, "c1", activation_approval=approval)
        self.assertEqual(client.posts, 0)

    def test_activation_rejects_stale_fingerprint_before_any_send(self):
        client = ActivationGuardClient(
            basis="consent_verified", reference="crm:consent-2026-123",
        )
        with self.assertRaisesRegex(ValueError, "activation_sequence_approval_required_or_stale"):
            _activate(client, "c1", activation_approval="APPROVE_INSTANTLY_ACTIVATION c1 " + "a" * 64)
        self.assertEqual(client.posts, 0)

    def test_activation_rejects_boolean_status_and_campaign_id_mismatch(self):
        bad_status = ActivationGuardClient(status=False)
        with self.assertRaisesRegex(ValueError, "campaign_must_be_draft_or_paused_before_activation"):
            _activate(bad_status, "c1")
        self.assertEqual(bad_status.posts, 0)
        wrong_id = ActivationGuardClient(campaign_id="other")
        with self.assertRaisesRegex(RuntimeError, "campaign_readback_id_mismatch"):
            _activate(wrong_id, "c1")
        self.assertEqual(wrong_id.posts, 0)


    @patch("instantly_control.fetch_live_registry")
    def test_activation_rejects_leadset_change_during_preflight(self, registry_mock):
        registry_mock.return_value = activation_registry_rows()
        class ChangingLeads(ActivationGuardClient):
            def __init__(self):
                super().__init__(
                    basis="consent_verified", reference="crm:consent-2026-123",
                )
                self.read_count = 0

            def list_leads(self, **kwargs):
                self.read_count += 1
                result = super().list_leads(**kwargs)
                if self.read_count >= 3:
                    result["items"][0]["payload"]["leadscanner_observation"] = "Unreviewed replacement"
                return result
        client = ChangingLeads()
        approval = activation_approval_for(client)
        with self.assertRaisesRegex(ValueError, "activation_leadset_changed_during_preflight"):
            _activate(client, "c1", activation_approval=approval)
        self.assertEqual(client.posts, 0)

    def test_activation_approval_is_bound_to_exact_lead_payload(self):
        client = ActivationGuardClient(
            basis="consent_verified", reference="crm:consent-2026-123",
        )
        approval = activation_approval_for(client)
        client.variables["leadscanner_observation"] = "Different fact after review"
        with self.assertRaisesRegex(ValueError, "activation_sequence_approval_required_or_stale"):
            _activate(client, "c1", activation_approval=approval)
        self.assertEqual(client.posts, 0)

    def test_activation_leadset_rejects_duplicate_identity(self):
        client = ActivationGuardClient()
        lead = client.list_leads()["items"][0]
        with self.assertRaisesRegex(ValueError, "activation_leadset_duplicate_or_invalid_identity"):
            _activation_leadset_fingerprint([lead, dict(lead)])

    def test_read_only_activation_audit_exposes_hashes_not_lead_emails(self):
        client = ActivationGuardClient(
            basis="consent_verified", reference="crm:consent-2026-123",
        )
        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "activation-readiness-001",
            "action": "audit_activation_readiness",
            "args": {"campaign_id": "c1"},
            "confirm": "",
            "requested_by": "chatgpt",
        }
        result = execute_command(command, config(), client)
        report = result["result"]
        self.assertEqual(result["mode"], "read")
        self.assertFalse(result["send_action"])
        self.assertEqual(report["lead_count"], 1)
        self.assertEqual(report["documented_contact_basis_count"], 1)
        self.assertEqual(len(report["leadset_fingerprint"]), 64)
        self.assertNotIn("lead@example.com", str(report))
        self.assertEqual(client.posts, 0)

    def test_activation_blocks_unreviewed_lead_in_leadscanner_campaign(self):
        client = ActivationGuardClient(
            basis="consent_verified", reference="crm:consent-2026-123",
        )
        approval = activation_approval_for(client)
        del client.variables["leadscanner_lead_id"]
        # The leadset changed, so even a previously valid approval must fail.
        with self.assertRaisesRegex(ValueError, "activation_sequence_approval_required_or_stale"):
            _activate(client, "c1", activation_approval=approval)
        self.assertEqual(client.posts, 0)

    def test_activation_blocks_legacy_template_without_contact_basis(self):
        class LegacyClient(ActivationGuardClient):
            def get_campaign(self, campaign_id):
                target = super().get_campaign(campaign_id)
                target["sequences"] = [{"steps": [{
                    "type": "email",
                    "variants": [{
                        "subject": "{{leadscanner_subject}}",
                        "body": "{{leadscanner_body}}",
                    }],
                }]}]
                return target
        client = LegacyClient()
        approval = activation_approval_for(client)
        with self.assertRaisesRegex(ValueError, "activation_requires_documented_contact_permission"):
            _activate(client, "c1", activation_approval=approval)
        self.assertEqual(client.posts, 0)

    @patch("instantly_control.fetch_live_registry")
    def test_activation_blocks_campaign_status_change_during_preflight(self, registry_mock):
        registry_mock.return_value = activation_registry_rows()
        class ChangingStatus(ActivationGuardClient):
            def get_campaign(self, campaign_id):
                target = super().get_campaign(campaign_id)
                if self.get_count >= 3 and not self.activated:
                    target["status"] = 1
                return target
        client = ChangingStatus(
            basis="consent_verified", reference="crm:consent-2026-123",
        )
        approval = activation_approval_for(client)
        with self.assertRaisesRegex(ValueError, "campaign_changed_during_activation_preflight"):
            _activate(client, "c1", activation_approval=approval)
        self.assertEqual(client.posts, 0)


    @patch("instantly_control.fetch_live_registry")
    def test_activation_blocks_missing_or_suppressed_registry_identity(self, registry_mock):
        for rows in ([], activation_registry_rows("unsubscribed"), activation_registry_rows("replied")):
            with self.subTest(rows=rows):
                registry_mock.return_value = rows
                client = ActivationGuardClient(
                    basis="consent_verified", reference="crm:consent-2026-123",
                )
                approval = activation_approval_for(client)
                with self.assertRaisesRegex(ValueError, "activation_registry_identity_missing_or_ambiguous|activation_registry_suppression_or_identity_mismatch"):
                    _activate(client, "c1", activation_approval=approval)
                self.assertEqual(client.posts, 0)

    @patch("instantly_control.fetch_live_registry")
    def test_activation_blocks_registry_suppression_during_preflight(self, registry_mock):
        registry_mock.side_effect = [
            activation_registry_rows("instantly_staged"),
            activation_registry_rows("unsubscribed"),
        ]
        client = ActivationGuardClient(
            basis="consent_verified", reference="crm:consent-2026-123",
        )
        approval = activation_approval_for(client)
        with self.assertRaisesRegex(ValueError, "activation_registry_suppression_or_identity_mismatch"):
            _activate(client, "c1", activation_approval=approval)
        self.assertEqual(client.posts, 0)
        self.assertEqual(registry_mock.call_count, 2)

    def test_activation_blocks_suppressed_provider_status_even_when_verified(self):
        class SuppressedClient(ActivationGuardClient):
            def __init__(self, status=None, interest=None):
                super().__init__()
                self.lead_status = status
                self.interest = interest

            def list_leads(self, **kwargs):
                page = super().list_leads(**kwargs)
                if self.lead_status is not None:
                    page["items"][0]["status"] = self.lead_status
                if self.interest is not None:
                    page["items"][0]["lt_interest_status"] = self.interest
                return page
        for status, interest in ((-1, None), (-2, None), (-3, None), (None, -1), (None, -2), (None, -3), (None, -4)):
            with self.subTest(status=status, interest=interest):
                client = SuppressedClient(status, interest)
                with self.assertRaisesRegex(ValueError, "activation_blocks_suppressed_lead_status"):
                    _activate(client, "c1")
                self.assertEqual(client.posts, 0)

    def test_update_campaign_rejects_silent_sequence_mutation_failure(self):
        class IgnoringPatch:
            def get_campaign(self, campaign_id):
                return {
                    "id": campaign_id, "status": 0,
                    "sequences": [{"steps": [{
                        "type": "email",
                        "variants": [{"subject": "Old", "body": "Old body"}],
                    }]}],
                }

            def _request(self, method, path, **kwargs):
                if method == "PATCH" and path == "/campaigns/c1":
                    return {"id": "c1"}
                raise AssertionError("unexpected call")
        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "campaign-ignored-sequence-001",
            "action": "update_campaign",
            "args": {"campaign_id": "c1", "payload": {"sequences": [{
                "steps": [{"type": "email", "variants": [{
                    "subject": "New", "body": "New body",
                }]}],
            }]}},
            "confirm": "EXECUTE update_campaign c1",
            "requested_by": "chatgpt",
        }
        with self.assertRaisesRegex(RuntimeError, "campaign_update_sequence_readback_mismatch"):
            execute_command(command, config(), IgnoringPatch())

    def test_update_campaign_rejects_silent_sender_change_failure(self):
        class IgnoringPatch:
            def get_campaign(self, campaign_id):
                return {"id": campaign_id, "status": 0, "email_list": ["old@example.com"]}

            def _request(self, method, path, **kwargs):
                return {"id": "c1"}
        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "campaign-ignored-sender-001",
            "action": "update_campaign",
            "args": {"campaign_id": "c1", "payload": {"email_list": ["new@example.com"]}},
            "confirm": "EXECUTE update_campaign c1",
            "requested_by": "chatgpt",
        }
        with self.assertRaisesRegex(RuntimeError, "campaign_update_sender_readback_mismatch"):
            execute_command(command, config(), IgnoringPatch())

    def test_update_campaign_accepts_verified_sequence_readback(self):
        class EchoPatch:
            def __init__(self):
                self.sequences = [{"steps": [{
                    "type": "email", "variants": [{
                        "subject": "Old", "body": "Old body",
                    }],
                }]}]

            def get_campaign(self, campaign_id):
                return {"id": campaign_id, "status": 0, "sequences": self.sequences}

            def _request(self, method, path, **kwargs):
                self.sequences = kwargs["json"]["sequences"]
                return {"id": "c1"}
        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "campaign-verified-sequence-001",
            "action": "update_campaign",
            "args": {"campaign_id": "c1", "payload": {"sequences": [{
                "steps": [{"type": "email", "variants": [{
                    "subject": "New", "body": "New body",
                }]}],
            }]}},
            "confirm": "EXECUTE update_campaign c1",
            "requested_by": "chatgpt",
        }
        result = execute_command(command, config(), EchoPatch())
        self.assertEqual(result["status"], "green")
        self.assertEqual(result["result"]["readback"]["sequences"], command["args"]["payload"]["sequences"])

    def test_update_campaign_readback_ignores_provider_ids_not_email_copy(self):
        class NormalizingClient:
            def __init__(self):
                self.steps = [{"type": "email", "variants": [{"subject": "Old", "body": "Old"}]}]

            def get_campaign(self, campaign_id):
                return {"id": campaign_id, "status": 0, "sequences": [{
                    "id": "provider-sequence-id",
                    "steps": [
                        {**step, "id": "provider-step-id"}
                        for step in self.steps
                    ],
                }]}

            def _request(self, method, path, **kwargs):
                self.steps = kwargs["json"]["sequences"][0]["steps"]
                return {"id": "c1"}
        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "campaign-normalized-sequence-001",
            "action": "update_campaign",
            "args": {"campaign_id": "c1", "payload": {"sequences": [{
                "steps": [
                    {"type": "delay", "delay": 2},
                    {"type": "email", "variants": [{"subject": "New", "body": "New body"}]},
                ],
            }]}},
            "confirm": "EXECUTE update_campaign c1",
            "requested_by": "chatgpt",
        }
        result = execute_command(command, config(), NormalizingClient())
        self.assertEqual(result["status"], "green")

    def test_update_campaign_rejects_ignored_reply_stop_or_daily_limit(self):
        class IgnoringSafety:
            def get_campaign(self, campaign_id):
                return {
                    "id": campaign_id, "status": 0,
                    "stop_on_reply": False, "daily_limit": 100,
                }

            def _request(self, method, path, **kwargs):
                return {"id": "c1"}
        for payload, expected in (
            ({"stop_on_reply": True}, "campaign_update_safety_field_readback_mismatch"),
            ({"daily_limit": 15}, "campaign_update_limit_readback_mismatch"),
        ):
            with self.subTest(payload=payload):
                command = {
                    "schema_version": "leadscanner-instantly-command/1.0",
                    "command_id": "campaign-ignored-safety-001",
                    "action": "update_campaign",
                    "args": {"campaign_id": "c1", "payload": payload},
                    "confirm": "EXECUTE update_campaign c1",
                    "requested_by": "chatgpt",
                }
                with self.assertRaisesRegex(RuntimeError, expected):
                    execute_command(command, config(), IgnoringSafety())

    def test_update_campaign_rejects_boolean_status_before_patch(self):
        class BooleanStatusClient:
            def get_campaign(self, campaign_id):
                return {"id": campaign_id, "status": False}

            def _request(self, *args, **kwargs):
                raise AssertionError("must not patch")
        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "campaign-bool-status-001",
            "action": "update_campaign",
            "args": {"campaign_id": "c1", "payload": {"name": "Bad"}},
            "confirm": "EXECUTE update_campaign c1",
            "requested_by": "chatgpt",
        }
        with self.assertRaisesRegex(ValueError, "campaign_must_be_draft_or_paused_before_update"):
            execute_command(command, config(), BooleanStatusClient())

    def test_create_campaign_rejects_boolean_draft_readback(self):
        class BooleanDraftClient:
            def _request(self, method, path, **kwargs):
                if method == "POST" and path == "/campaigns":
                    return {"id": "c1"}
                raise AssertionError("unexpected API call")

            def get_campaign(self, campaign_id):
                return {"id": campaign_id, "status": False}
        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "create-bool-draft-001",
            "action": "create_campaign_draft",
            "args": {"payload": {"name": "Draft", "campaign_schedule": {}}},
            "confirm": "EXECUTE create_campaign_draft Draft",
            "requested_by": "chatgpt",
        }
        with self.assertRaisesRegex(RuntimeError, "new_campaign_must_read_back_as_draft"):
            execute_command(command, config(), BooleanDraftClient())

    def test_safe_obsolete_draft_delete_only_if_empty_and_inactive(self):
        cid = "59c01c6e-86a6-4417-acab-76f114dca9c5"
        class Draft:
            def __init__(self, count=0, status=0):
                self.count=count
                self.status=status
                self.deleted=False
            def get_campaign(self, target):
                if self.deleted:
                    raise InstantlyError("instantly_api_error status=404")
                return {"id":cid,"name":"Leadscanner 3-Step Concept","status":self.status}
            def list_leads(self,**kwargs):
                return {"items":[{"id":"existing"}] if self.count else []}
            def _request(self, method, path, **kwargs):
                if method=="DELETE" and path.endswith(cid):
                    self.deleted=True
                    return {}
                raise AssertionError("unsafe provider call")
        cmd={"schema_version":"leadscanner-instantly-command/1.0","command_id":"test-delete-empty",
             "action":"delete_unused_draft_campaign","args":{"campaign_id":cid},
             "confirm":"EXECUTE delete_unused_draft_campaign "+cid}
        for kwargs in ({"count":1},{"status":1}):
            api=Draft(**kwargs)
            with self.assertRaisesRegex(ValueError,"has_leads|must_be_inactive"):
                execute_command(cmd,config(),api)
            self.assertFalse(api.deleted)
        api=Draft()
        result=execute_command(cmd,config(),api)
        self.assertTrue(result["result"]["deleted"])
        self.assertTrue(api.deleted)

    def test_safe_obsolete_draft_delete_blocks_other_campaigns(self):
        cmd={"schema_version":"leadscanner-instantly-command/1.0","command_id":"test-delete-target",
             "action":"delete_unused_draft_campaign","args":{"campaign_id":"5c720281-fd07-4c47-8155-c88d7d3c09b8"},
             "confirm":"EXECUTE delete_unused_draft_campaign 5c720281-fd07-4c47-8155-c88d7d3c09b8"}
        class NoApi:
            def get_campaign(self,*a): raise AssertionError("should fail before provider")
        with self.assertRaisesRegex(ValueError,"obsolete_draft_exact_id_required"):
            execute_command(cmd,config(),NoApi())

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

    def test_read_only_sequence_audit_reports_counts_without_email_copy(self):
        class SequenceClient:
            def __init__(self):
                self.calls = []

            def get_campaign(self, campaign_id):
                self.calls.append(("get_campaign", campaign_id))
                return {
                    "id": campaign_id,
                    "status": 2,
                    "sequences": [{"steps": [
                        {"type": "email", "variants": [
                            {"subject": "PRIVATE SUBJECT", "body": "PRIVATE BODY {{aiIdeas}}"}
                        ]} for _ in range(3)
                    ]}],
                }

        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "audit-sequence-001",
            "action": "audit_campaign_sequence",
            "args": {"campaign_id": "c1"},
            "confirm": "",
            "requested_by": "chatgpt",
        }
        client = SequenceClient()
        result = execute_command(command, config(), client)
        self.assertEqual(client.calls, [("get_campaign", "c1")])
        self.assertEqual(result["mode"], "read")
        self.assertFalse(result["send_action"])
        self.assertEqual(result["result"]["email_step_count"], 3)
        self.assertEqual(result["result"]["decision"], "not_linked_to_leadscanner")
        self.assertNotIn("PRIVATE SUBJECT", str(result))
        self.assertNotIn("PRIVATE BODY", str(result))

    def test_sequence_audit_fails_closed_on_mismatched_campaign(self):
        class WrongCampaignClient:
            def get_campaign(self, campaign_id):
                return {"id": "other-campaign", "status": 0, "sequences": []}

        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "audit-sequence-002",
            "action": "audit_campaign_sequence",
            "args": {"campaign_id": "c1"},
            "confirm": "",
            "requested_by": "chatgpt",
        }
        with self.assertRaisesRegex(RuntimeError, "campaign_readback_id_mismatch"):
            execute_command(command, config(), WrongCampaignClient())

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
                if method == "GET" and path == "/email-verification/lead%40example.com":
                    return {"verification_status": "invalid", "catch_all": False}
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

    @patch("instantly_control.stage_exact_approved_lead")
    @patch("instantly_control._env")
    def test_stage_command_passes_exact_sequence_approval(self, env_mock, stage_mock):
        env_mock.side_effect = lambda key: {"INSTANTLY_API_KEY": "key", "LEADSCANNER_GITHUB_TOKEN": "gh"}[key]
        stage_mock.return_value = {"status": "green", "automatic_send": False}
        args = {
            "preview_run_id": 123,
            "approval_token": "growth-aaaaaaaaaaaaaaaaaaaa@1111111111111111",
            "campaign_id": "campaign-1",
            "sequence_approval": "APPROVE_INSTANTLY_SEQUENCE campaign-1 " + "a" * 64,
        }
        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "stage-approved-confirm-002",
            "action": "stage_approved_lead",
            "args": args,
            "confirm": expected_confirmation("stage_approved_lead", args),
            "requested_by": "chatgpt",
        }
        result = execute_command(command, config(), FakeClient())
        self.assertEqual(result["status"], "green")
        self.assertEqual(stage_mock.call_args.kwargs["sequence_approval"], args["sequence_approval"])

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

        with self.assertRaisesRegex(RuntimeError, "lead_page_empty_with_cursor"):
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

    def test_account_vitals_is_read_only_diagnostic(self):
        class VitalsClient:
            def _request(self, method, path, **kwargs):
                self.method = method
                self.path = path
                self.kwargs = kwargs
                return {
                    "status": "success",
                    "success_list": [{"domain": "andrewbaeten.nl", "allPass": True}],
                    "failure_list": [],
                }

        client = VitalsClient()
        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "account-vitals-read-001",
            "action": "test_account_vitals",
            "args": {"accounts": ["info@andrewbaeten.nl"]},
            "requested_by": "chatgpt",
        }
        result = execute_command(command, config(), client)
        self.assertEqual(result["mode"], "read")
        self.assertFalse(result["send_action"])
        self.assertEqual(client.method, "POST")
        self.assertEqual(client.path, "/accounts/test/vitals")
        self.assertEqual(
            client.kwargs["json"],
            {"accounts": ["info@andrewbaeten.nl"]},
        )

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

    def test_activation_tolerates_draft_sending_status_400_and_keeps_other_gates(self):
        class ActivationClient:
            def __init__(self):
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
                    "items": [{"id": "l1", "email": "lead@example.com", "verification_status": 1}],
                    "next_starting_after": None,
                }

            def _request(self, method, path, **kwargs):
                if method == "GET" and path.endswith("/sending-status"):
                    raise InstantlyError("instantly_api_error status=400")
                if method == "GET" and path == "/accounts/sender%40example.com":
                    return {"status": 1}
                if method == "POST" and path.endswith("/activate"):
                    self.activated = True
                    return {"accepted": True}
                raise AssertionError((method, path, kwargs))

        result = _activate(ActivationClient(), "c1")
        self.assertEqual(result["readback"]["status"], 1)
        self.assertEqual(
            result["preflight_sending_status"],
            {"state": "unavailable_before_activation", "http_status": 400},
        )

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

    def test_mark_account_fixed_requires_active_readback(self):
        class AccountClient:
            def __init__(self, readback_status):
                self.readback_status = readback_status
                self.calls = []

            def _request(self, method, path, **kwargs):
                self.calls.append((method, path, kwargs))
                if method == "POST" and path.endswith("/mark-fixed"):
                    return {"status": "success"}
                if method == "GET" and path == "/accounts/sender%40example.com":
                    return {"email": "sender@example.com", "status": self.readback_status}
                raise AssertionError((method, path, kwargs))

        args = {"email": "sender@example.com"}
        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "mark-account-fixed-001",
            "action": "mark_account_fixed",
            "args": args,
            "confirm": "EXECUTE mark_account_fixed sender@example.com",
            "requested_by": "chatgpt",
        }
        result = execute_command(command, config(), AccountClient(1))
        self.assertEqual(result["mode"], "write")
        self.assertFalse(result["send_action"])
        self.assertEqual(result["result"]["readback"]["status"], 1)

        with self.assertRaisesRegex(RuntimeError, "account_mark_fixed_readback_not_active"):
            execute_command(command, config(), AccountClient(-1))

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

    def test_email_verification_polls_pending_to_verified(self):
        class VerificationClient:
            def __init__(self):
                self.gets = 0

            def _request(self, method, path, **kwargs):
                if method == "POST" and path == "/email-verification":
                    self.assert_payload = kwargs["json"]
                    return {"verification_status": "pending", "catch_all": "pending"}
                if method == "GET" and path == "/email-verification/lead%40example.com":
                    self.gets += 1
                    if self.gets == 1:
                        return {"verification_status": "pending", "catch_all": "pending"}
                    return {"verification_status": "verified", "catch_all": False}
                raise AssertionError((method, path, kwargs))

        client = VerificationClient()
        result = _verify_email(
            client,
            "lead@example.com",
            max_polls=3,
            sleep_fn=lambda _: None,
        )
        self.assertEqual(client.assert_payload, {"email": "lead@example.com"})
        self.assertEqual(result["verification_status"], "verified")
        self.assertFalse(result["catch_all"])

    def test_activation_uses_direct_verification_when_lead_status_missing(self):
        class ActivationClient:
            def __init__(self, verification):
                self.verification = verification
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
                    "items": [{"id": "l1", "email": "lead@example.com"}],
                    "next_starting_after": None,
                }

            def _request(self, method, path, **kwargs):
                if method == "GET" and path.endswith("/sending-status"):
                    raise InstantlyError("instantly_api_error status=400")
                if method == "GET" and path == "/accounts/sender%40example.com":
                    return {"status": 1}
                if method == "GET" and path == "/email-verification/lead%40example.com":
                    return self.verification
                if method == "POST" and path.endswith("/activate"):
                    self.activated = True
                    return {"accepted": True}
                raise AssertionError((method, path, kwargs))

        good = ActivationClient({"verification_status": "verified", "catch_all": False})
        result = _activate(good, "c1")
        self.assertTrue(good.activated)
        self.assertEqual(result["preflight_lead_count"], 1)

        risky = ActivationClient({"verification_status": "verified", "catch_all": True})
        with self.assertRaisesRegex(ValueError, "verified_leads_only"):
            _activate(risky, "c1")
        self.assertFalse(risky.activated)

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
