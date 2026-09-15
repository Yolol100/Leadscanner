from __future__ import annotations

import unittest

from instantly_api_v2 import confirmation_token, normalize_path
from instantly_command_guard import guard_request


SPEC = {
    "paths": {
        "/api/v2/campaigns": {
            "post": {"operationId": "createCampaign", "tags": ["Campaign"]},
        },
        "/api/v2/campaigns/{id}": {
            "patch": {"operationId": "patchCampaign", "tags": ["Campaign"]},
        },
        "/api/v2/ai-agents/sales/{id}": {
            "patch": {"operationId": "patchSalesAgent", "tags": ["AISalesAgent"]},
        },
        "/api/v2/leads/add": {
            "post": {"operationId": "bulkAddLeads", "tags": ["Lead"]},
        },
        "/api/v2/supersearch-enrichment/saved-searches": {
            "post": {"operationId": "createSavedSearch", "tags": ["SuperSearchEnrichment"]},
        },
    }
}


def token(method: str, path: str, body=None) -> str:
    return confirmation_token(
        method,
        normalize_path(path),
        {},
        {} if body is None else body,
    )


class InstantlyCommandGuardTests(unittest.TestCase):
    def test_plan_only_sensitive_write_does_not_require_confirmation(self):
        request = {
            "method": "PATCH",
            "path": "/ai-agents/sales/agent-1",
            "body": {"name": "Webactueel"},
            "apply": False,
        }
        result = guard_request(request, spec=SPEC)
        self.assertTrue(result["high_impact_guard"])
        self.assertFalse(result["apply"])

    def test_ai_agent_apply_requires_exact_confirmation(self):
        request = {
            "method": "PATCH",
            "path": "/ai-agents/sales/agent-1",
            "body": {"name": "Webactueel"},
            "apply": True,
        }
        with self.assertRaises(ValueError):
            guard_request(request, spec=SPEC)
        request["confirmation"] = token(
            "PATCH", "/ai-agents/sales/agent-1", {"name": "Webactueel"}
        )
        self.assertTrue(guard_request(request, spec=SPEC)["high_impact_guard"])

    def test_campaign_patch_apply_requires_confirmation(self):
        request = {
            "method": "PATCH",
            "path": "/campaigns/campaign-1",
            "body": {"stop_on_reply": True},
            "apply": True,
        }
        with self.assertRaises(ValueError):
            guard_request(request, spec=SPEC)

    def test_lead_add_apply_requires_confirmation(self):
        request = {
            "method": "POST",
            "path": "/leads/add",
            "body": {"campaign_id": "c", "leads": [{"email": "test@example.com"}]},
            "apply": True,
        }
        with self.assertRaises(ValueError):
            guard_request(request, spec=SPEC)

    def test_safe_configuration_write_can_apply_without_extra_guard(self):
        request = {
            "method": "POST",
            "path": "/supersearch-enrichment/saved-searches",
            "body": {"name": "Dutch SMEs"},
            "apply": True,
        }
        result = guard_request(request, spec=SPEC)
        self.assertFalse(result["high_impact_guard"])

    def test_create_campaign_is_plan_first_but_not_extra_guarded(self):
        request = {
            "method": "POST",
            "path": "/campaigns",
            "body": {"name": "Draft campaign"},
            "apply": True,
        }
        result = guard_request(request, spec=SPEC)
        self.assertFalse(result["high_impact_guard"])


if __name__ == "__main__":
    unittest.main()
