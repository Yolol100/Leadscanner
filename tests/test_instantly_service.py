import os
import unittest
from unittest.mock import patch

from instantly_service import (
    _verify_instantly_readback,
    require_instantly_writes_enabled,
    stage_exact_approved_lead,
)


class FakeInstantlyClient:
    def __init__(self):
        self.calls = []

    def add_approved_lead_to_campaign(self, **kwargs):
        self.calls.append(("add", kwargs))
        return {"id": "instantly-1"}

    def get_lead(self, lead_id):
        self.calls.append(("get", lead_id))
        return {
            "id": lead_id,
            "email": "info@acme.nl",
            "campaign": "campaign-1",
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
    }
    return {
        "snapshot": {"preview_id": "preview-abc"},
        "approved_current": {
            "schema_version": "leadscanner-approved-revalidation/1.0",
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
    @patch("instantly_service.check_registry_access")
    @patch("instantly_service.resolve_exact_approval")
    def test_stage_requires_readback_then_registry_exact_write(
        self, resolve_mock, preflight_mock, update_mock
    ):
        resolve_mock.return_value = resolved()
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


if __name__ == "__main__":
    unittest.main()
