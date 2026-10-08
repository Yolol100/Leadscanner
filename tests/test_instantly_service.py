import os
import unittest
from unittest.mock import patch

from instantly_client import approved_custom_variables
from instantly_service import (
    _verify_instantly_readback,
    require_instantly_writes_enabled,
    stage_approved_batch,
    stage_exact_approved_lead,
)


class FakeInstantlyClient:
    def __init__(self):
        self.calls = []
        self.last_row = None

    def add_approved_lead_to_campaign(self, **kwargs):
        self.calls.append(("add", kwargs))
        self.last_row = kwargs["approved_batch"]["rows"][0]
        return {"id": "instantly-1"}

    def get_lead(self, lead_id):
        self.calls.append(("get", lead_id))
        return {
            "id": lead_id,
            "email": "info@acme.nl",
            "campaign": "campaign-1",
            "payload": approved_custom_variables(self.last_row),
        }


def resolved():
    row = {
        "lead_id": "growth-aaaaaaaaaaaaaaaaaaaa",
        "company": "Acme",
        "website": "https://acme.nl/",
        "official_domain": "acme.nl",
        "email": "info@acme.nl",
        "status": "review_draft",
        "contact_basis_status": "review_required",
        "automatic_send": False,
        "subject": "idee voor afspraakroute",
        "body": "Hallo, ik zag jullie afspraakroute.",
        "verified_observation": "Klanten kunnen online een afspraak aanvragen voor onderhoud of reparatie.",
        "verified_observation_source_url": "https://acme.nl/afspraak",
        "verified_observation_source_type": "official_site",
        "signal_type": "appointment",
        "value_first_action": "een korte voorbeeldvariant voor de afspraakroute",
    }
    return {
        "snapshot": {"preview_id": "preview-abc"},
        "approved_current": {
            "schema_version": "leadscanner-approved-revalidation/1.0",
            "remaining_count": 1,
            "rows": [row],
            "safety": {
                "automatic_send": False,
                "dedupe_rechecked_immediately_before_mutation": True,
            },
        },
        "row": row,
        "registry_rows": [],
    }


class InstantlyServiceTests(unittest.TestCase):
    def test_sequence_facts_never_stage_without_campaign_level_approval(self):
        row = {**resolved()["row"], "review_mode": "instantly_sequence", "status": "sequence_facts_review", "subject": "", "body": ""}
        selected = {
            "schema_version": "leadscanner-approved-review-draft-batch/1.0",
            "rows": [row],
            "approval": {"approved_count": 1, "automatic_send": False},
        }
        client = FakeInstantlyClient()
        with patch.dict(os.environ, {"LEADSCANNER_INSTANTLY_WRITES_ENABLED": "true"}, clear=False):
            with self.assertRaisesRegex(ValueError, "instantly_sequence_staging_not_yet_enabled"):
                stage_approved_batch(
                    approved_batch=selected,
                    campaign_id="campaign-1",
                    instantly_api_key="key",
                    instantly_client=client,
                )
        self.assertEqual(client.calls, [])

    def test_writes_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "writes_disabled"):
                require_instantly_writes_enabled()

    def test_readback_requires_exact_email_and_campaign(self):
        row = resolved()["row"]
        with self.assertRaisesRegex(RuntimeError, "email_mismatch"):
            _verify_instantly_readback(
                {"email": "other@acme.nl", "campaign": "campaign-1"},
                row=row,
                campaign_id="campaign-1",
            )
        with self.assertRaisesRegex(RuntimeError, "campaign_mismatch"):
            _verify_instantly_readback(
                {"email": "info@acme.nl", "campaign": "campaign-2"},
                row=row,
                campaign_id="campaign-1",
            )

    def test_readback_rejects_missing_or_changed_custom_variables(self):
        row = resolved()["row"]
        observed = {"email": row["email"], "campaign": "campaign-1"}
        with self.assertRaisesRegex(RuntimeError, "readback_variables_missing"):
            _verify_instantly_readback(observed, row=row, campaign_id="campaign-1")
        observed["payload"] = approved_custom_variables(row)
        observed["payload"]["leadscanner_body"] = "changed after approval"
        with self.assertRaisesRegex(RuntimeError, "readback_variable_mismatch:leadscanner_body"):
            _verify_instantly_readback(observed, row=row, campaign_id="campaign-1")

    @patch("instantly_service.update_registry")
    @patch("instantly_service.revalidate_approved")
    @patch("instantly_service.fetch_live_registry")
    @patch("instantly_service.check_registry_access")
    @patch("instantly_service.resolve_exact_approval")
    def test_variable_readback_mismatch_blocks_registry_closure(
        self, resolve_mock, preflight_mock, fetch_registry_mock, revalidate_mock, update_mock
    ):
        resolve_mock.return_value = resolved()
        fetch_registry_mock.return_value = []
        revalidate_mock.return_value = resolved()["approved_current"]

        class TamperedClient(FakeInstantlyClient):
            def get_lead(self, lead_id):
                observed = super().get_lead(lead_id)
                observed["payload"]["leadscanner_body"] = "not approved"
                return observed

        with patch.dict(os.environ, {"LEADSCANNER_INSTANTLY_WRITES_ENABLED": "true"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "readback_variable_mismatch"):
                stage_exact_approved_lead(
                    preview_run_id=123,
                    approval_token="growth-aaaaaaaaaaaaaaaaaaaa@1111111111111111",
                    campaign_id="campaign-1",
                    instantly_api_key="key",
                    github_token="gh",
                    instantly_client=TamperedClient(),
                )
        update_mock.assert_not_called()

    @patch("instantly_service.update_registry")
    @patch("instantly_service.check_registry_access", side_effect=RuntimeError("registry_preflight_failed"), create=True)
    @patch("instantly_service.resolve_exact_approval")
    def test_stage_preflights_registry_before_instantly_mutation(
        self, resolve_mock, preflight_mock, update_mock
    ):
        resolve_mock.return_value = resolved()
        preflight_mock.return_value = {"status": "green"}
        update_mock.return_value = {"exact_readback": True}
        client = FakeInstantlyClient()

        with patch.dict(os.environ, {"LEADSCANNER_INSTANTLY_WRITES_ENABLED": "true"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "registry_preflight_failed"):
                stage_exact_approved_lead(
                    preview_run_id=123,
                    approval_token="growth-aaaaaaaaaaaaaaaaaaaa@1111111111111111",
                    campaign_id="campaign-1",
                    instantly_api_key="key",
                    github_token="gh",
                    instantly_client=client,
                )

        self.assertEqual(client.calls, [])
        preflight_mock.assert_called_once()
        update_mock.assert_not_called()

    @patch("instantly_service.update_registry")
    @patch("instantly_service.revalidate_approved")
    @patch("instantly_service.fetch_live_registry")
    @patch("instantly_service.check_registry_access")
    @patch("instantly_service.resolve_exact_approval")
    def test_registry_access_preflight_is_followed_by_fresh_dedupe_revalidation(
        self, resolve_mock, preflight_mock, fetch_registry_mock, revalidate_mock, update_mock
    ):
        events = []
        resolve_mock.side_effect = lambda **kwargs: events.append("resolve") or resolved()
        preflight_mock.side_effect = lambda **kwargs: events.append("preflight") or {"status": "green"}
        fetch_registry_mock.side_effect = lambda **kwargs: events.append("refresh") or []
        revalidate_mock.side_effect = (
            lambda approved, registry: events.append("revalidate") or resolved()["approved_current"]
        )
        update_mock.return_value = {"exact_readback": True}

        class OrderedClient(FakeInstantlyClient):
            def add_approved_lead_to_campaign(self, **kwargs):
                events.append("add")
                return super().add_approved_lead_to_campaign(**kwargs)

        with patch.dict(os.environ, {"LEADSCANNER_INSTANTLY_WRITES_ENABLED": "true"}, clear=False):
            stage_exact_approved_lead(
                preview_run_id=123,
                approval_token="growth-aaaaaaaaaaaaaaaaaaaa@1111111111111111",
                campaign_id="campaign-1",
                instantly_api_key="key",
                github_token="gh",
                instantly_client=OrderedClient(),
            )

        self.assertEqual(events[:5], ["resolve", "preflight", "refresh", "revalidate", "add"])

    @patch("instantly_service.update_registry")
    @patch("instantly_service.revalidate_approved")
    @patch("instantly_service.fetch_live_registry")
    @patch("instantly_service.check_registry_access")
    def test_stage_batch_uses_fresh_dedupe_and_never_activates(
        self, preflight_mock, fetch_registry_mock, revalidate_mock, update_mock
    ):
        selected = {
            "schema_version": "leadscanner-approved-review-draft-batch/1.0",
            "draft_candidate_count": 1,
            "review_draft_count": 1,
            "rows": [resolved()["row"]],
            "approval": {
                "requested_count": 1,
                "approved_count": 1,
                "rejected_by_operator_count": 0,
                "automatic_send": False,
            },
            "safety": {"automatic_send": False},
        }
        fetch_registry_mock.return_value = []
        revalidate_mock.return_value = resolved()["approved_current"]
        update_mock.return_value = {"status": "green", "exact_readback": True}
        client = FakeInstantlyClient()

        with patch.dict(os.environ, {"LEADSCANNER_INSTANTLY_WRITES_ENABLED": "true"}, clear=False):
            result = stage_approved_batch(
                approved_batch=selected,
                campaign_id="campaign-1",
                instantly_api_key="key",
                instantly_client=client,
            )

        self.assertEqual(result["requested_count"], 1)
        self.assertEqual(result["staged_count"], 1)
        self.assertEqual(result["suppressed_count"], 0)
        self.assertFalse(result["automatic_send"])
        self.assertTrue(result["campaign_activation_required"])
        self.assertEqual([call[0] for call in client.calls], ["add", "get"])
        preflight_mock.assert_called_once()
        fetch_registry_mock.assert_called()
        update_mock.assert_called_once()

    @patch("instantly_service.update_registry")
    @patch("instantly_service.revalidate_approved")
    @patch("instantly_service.fetch_live_registry")
    @patch("instantly_service.check_registry_access")
    def test_stage_batch_skips_lead_that_became_suppressed(
        self, preflight_mock, fetch_registry_mock, revalidate_mock, update_mock
    ):
        selected = {
            "schema_version": "leadscanner-approved-review-draft-batch/1.0",
            "draft_candidate_count": 1,
            "review_draft_count": 1,
            "rows": [resolved()["row"]],
            "approval": {
                "requested_count": 1,
                "approved_count": 1,
                "rejected_by_operator_count": 0,
                "automatic_send": False,
            },
            "safety": {"automatic_send": False},
        }
        fetch_registry_mock.return_value = []
        suppressed = {
            **resolved()["approved_current"],
            "remaining_count": 0,
            "suppressed_after_preview_count": 1,
            "rows": [],
        }
        revalidate_mock.return_value = suppressed
        client = FakeInstantlyClient()

        with patch.dict(os.environ, {"LEADSCANNER_INSTANTLY_WRITES_ENABLED": "true"}, clear=False):
            result = stage_approved_batch(
                approved_batch=selected,
                campaign_id="campaign-1",
                instantly_api_key="key",
                instantly_client=client,
            )

        self.assertEqual(result["staged_count"], 0)
        self.assertEqual(result["suppressed_count"], 1)
        self.assertEqual(client.calls, [])
        update_mock.assert_not_called()

    @patch("instantly_service.update_registry")
    @patch("instantly_service.revalidate_approved")
    @patch("instantly_service.fetch_live_registry")
    @patch("instantly_service.check_registry_access")
    @patch("instantly_service.resolve_exact_approval")
    def test_stage_requires_readback_then_registry_exact_write(
        self, resolve_mock, preflight_mock, fetch_registry_mock, revalidate_mock, update_mock
    ):
        resolve_mock.return_value = resolved()
        fetch_registry_mock.return_value = []
        revalidate_mock.return_value = resolved()["approved_current"]
        update_mock.return_value = {"exact_readback": True}
        client = FakeInstantlyClient()

        with patch.dict(os.environ, {"LEADSCANNER_INSTANTLY_WRITES_ENABLED": "true"}, clear=False):
            result = stage_exact_approved_lead(
                preview_run_id=123,
                approval_token="growth-aaaaaaaaaaaaaaaaaaaa@1111111111111111",
                campaign_id="campaign-1",
                instantly_api_key="key",
                github_token="gh",
                instantly_client=client,
            )

        self.assertEqual([call[0] for call in client.calls], ["add", "get"])
        self.assertTrue(result["instantly_readback"])
        self.assertTrue(result["registry_exact_readback"])
        self.assertFalse(result["automatic_send"])
        self.assertFalse(result["campaign_activation_available"])
        preflight_mock.assert_called_once()
        update_mock.assert_called_once()

    @patch("instantly_service.update_registry")
    @patch("instantly_service.revalidate_approved")
    @patch("instantly_service.fetch_live_registry")
    @patch("instantly_service.check_registry_access")
    @patch("instantly_service.resolve_exact_approval")
    def test_stage_never_reports_green_without_exact_registry_readback(
        self, resolve_mock, preflight_mock, fetch_registry_mock, revalidate_mock, update_mock
    ):
        resolve_mock.return_value = resolved()
        fetch_registry_mock.return_value = []
        revalidate_mock.return_value = resolved()["approved_current"]
        client = FakeInstantlyClient()
        with patch.dict(os.environ, {"LEADSCANNER_INSTANTLY_WRITES_ENABLED": "true"}, clear=False):
            for invalid_readback in (False, None, "true"):
                with self.subTest(invalid_readback=invalid_readback):
                    update_mock.return_value = {"exact_readback": invalid_readback}
                    with self.assertRaisesRegex(RuntimeError, "instantly_stage_registry_readback_failed"):
                        stage_exact_approved_lead(
                            preview_run_id=123,
                            approval_token="growth-aaaaaaaaaaaaaaaaaaaa@1111111111111111",
                            campaign_id="campaign-1",
                            instantly_api_key="key",
                            github_token="gh",
                            instantly_client=client,
                        )
        self.assertEqual(len(client.calls), 6)
        self.assertEqual(update_mock.call_count, 3)


if __name__ == "__main__":
    unittest.main()
