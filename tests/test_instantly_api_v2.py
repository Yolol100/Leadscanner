from __future__ import annotations

import unittest

from instantly_api_v2 import (
    InstantlyApiError,
    _query_pairs,
    classify_risk,
    confirmation_token,
    execute_operation,
    match_operation,
    normalize_path,
)

SPEC = {
    "paths": {
        "/api/v2/campaigns": {
            "get": {"operationId": "listCampaigns", "tags": ["Campaign"]},
            "post": {"operationId": "createCampaign", "tags": ["Campaign"]},
        },
        "/api/v2/campaigns/{id}": {
            "get": {"operationId": "getCampaign", "tags": ["Campaign"]},
            "patch": {"operationId": "updateCampaign", "tags": ["Campaign"]},
            "delete": {"operationId": "deleteCampaign", "tags": ["Campaign"]},
        },
        "/api/v2/campaigns/{id}/activate": {
            "post": {"operationId": "activateCampaign", "tags": ["Campaign"]},
        },
        "/api/v2/emails/reply": {
            "post": {"operationId": "replyToEmail", "tags": ["Email"]},
        },
        "/api/v2/leads/list": {
            "post": {"operationId": "listLeads", "tags": ["Lead"]},
        },
        "/api/v2/leads/add": {
            "post": {"operationId": "bulkAddLeads", "tags": ["Lead"]},
        },
        "/api/v2/ai-agents/sales/{id}": {
            "patch": {"operationId": "patchSalesAgent", "tags": ["AISalesAgent"]},
        },
        "/api/v2/webhooks": {
            "post": {"operationId": "createWebhook", "tags": ["Webhook"]},
        },
        "/api/v2/workspace-members": {
            "post": {"operationId": "createWorkspaceMember", "tags": ["Workspace"]},
        },
        "/api/v2/block-lists-entries": {
            "post": {"operationId": "createBlockListEntry", "tags": ["BlockList"]},
        },
        "/api/v2/accounts/{id}": {
            "patch": {"operationId": "patchAccount", "tags": ["Account"]},
        },
        "/api/v2/supersearch-enrichment/saved-searches": {
            "post": {
                "operationId": "createSavedSearch",
                "tags": ["SuperSearchEnrichment"],
            },
        },
    }
}


class FakeClient:
    def __init__(self):
        self.calls = []

    def request(self, method, path, *, query=None, body=None):
        self.calls.append((method, path, query, body))
        return 200, {"items": [{"id": "x"}]}


class InstantlyApiV2Tests(unittest.TestCase):
    def test_normalize_path_forces_v2(self):
        self.assertEqual(normalize_path("/campaigns"), "/api/v2/campaigns")
        self.assertEqual(normalize_path("/api/v2/campaigns"), "/api/v2/campaigns")
        with self.assertRaises(ValueError):
            normalize_path("https://evil.example/api/v2/campaigns")

    def test_openapi_match_handles_path_parameters(self):
        match = match_operation(SPEC, "GET", "/campaigns/abc-123")
        self.assertEqual(match.template_path, "/api/v2/campaigns/{id}")
        self.assertEqual(match.operation_id, "getCampaign")
        self.assertEqual(match.risk, "read")

    def test_operation_must_exist_in_official_spec(self):
        with self.assertRaises(InstantlyApiError):
            match_operation(SPEC, "POST", "/made-up-endpoint")

    def test_risk_classification(self):
        self.assertEqual(classify_risk("GET", "/api/v2/emails"), "read")
        self.assertEqual(classify_risk("DELETE", "/api/v2/leads/{id}"), "destructive")
        self.assertEqual(
            classify_risk(
                "POST", "/api/v2/campaigns/{id}/activate", "activateCampaign"
            ),
            "high_impact",
        )
        self.assertEqual(
            classify_risk("POST", "/api/v2/emails/reply", "replyToEmail"),
            "high_impact",
        )
        self.assertEqual(
            classify_risk("PATCH", "/api/v2/campaigns/{id}", "updateCampaign"),
            "high_impact",
        )
        self.assertEqual(
            classify_risk("POST", "/api/v2/webhooks", "createWebhook"),
            "high_impact",
        )
        self.assertEqual(
            classify_risk("POST", "/api/v2/campaigns", "createCampaign"),
            "write",
        )
        self.assertEqual(
            classify_risk(
                "POST",
                "/api/v2/supersearch-enrichment/saved-searches",
                "createSavedSearch",
            ),
            "write",
        )

    def test_query_pairs_preserve_repeated_values(self):
        pairs = _query_pairs({"tag_ids": ["a", "b"], "active": True})
        self.assertEqual(pairs, [("tag_ids", "a"), ("tag_ids", "b"), ("active", "true")])

    def test_write_defaults_to_plan_only(self):
        client = FakeClient()
        result, response, verification = execute_operation(
            client=client,
            spec=SPEC,
            method="POST",
            path="/campaigns",
            body={"name": "test"},
            apply=False,
        )
        self.assertEqual(result.status, "planned")
        self.assertFalse(result.applied)
        self.assertEqual(client.calls, [])
        self.assertIsNone(response)
        self.assertIsNone(verification)

    def test_high_impact_requires_confirmation(self):
        client = FakeClient()
        with self.assertRaises(InstantlyApiError):
            execute_operation(
                client=client,
                spec=SPEC,
                method="POST",
                path="/campaigns/abc-123/activate",
                apply=True,
            )
        self.assertEqual(client.calls, [])

    def test_direct_executor_blocks_all_shared_high_impact_surfaces(self):
        cases = (
            ("PATCH", "/campaigns/abc-123"),
            ("PATCH", "/ai-agents/sales/agent-1"),
            ("POST", "/leads/add"),
            ("POST", "/webhooks"),
            ("POST", "/workspace-members"),
            ("POST", "/block-lists-entries"),
            ("PATCH", "/accounts/account-1"),
        )
        for method, path in cases:
            with self.subTest(method=method, path=path):
                client = FakeClient()
                with self.assertRaises(InstantlyApiError):
                    execute_operation(
                        client=client,
                        spec=SPEC,
                        method=method,
                        path=path,
                        apply=True,
                    )
                self.assertEqual(client.calls, [])

    def test_supersearch_saved_search_is_not_false_positive_high_impact(self):
        client = FakeClient()
        result, _, _ = execute_operation(
            client=client,
            spec=SPEC,
            method="POST",
            path="/supersearch-enrichment/saved-searches",
            body={"name": "Dutch SMEs"},
            apply=True,
        )
        self.assertEqual(result.risk, "write")
        self.assertTrue(result.applied)
        self.assertEqual(len(client.calls), 1)

    def test_high_impact_executes_with_exact_confirmation(self):
        client = FakeClient()
        path = "/api/v2/campaigns/abc-123/activate"
        token = confirmation_token("POST", path, {}, {})
        result, _, _ = execute_operation(
            client=client,
            spec=SPEC,
            method="POST",
            path=path,
            apply=True,
            confirmation=token,
        )
        self.assertEqual(result.status, "green")
        self.assertEqual(len(client.calls), 1)

    def test_verify_must_be_read_only(self):
        client = FakeClient()
        with self.assertRaises(InstantlyApiError):
            execute_operation(
                client=client,
                spec=SPEC,
                method="POST",
                path="/campaigns",
                body={"name": "test"},
                apply=True,
                verify={"method": "PATCH", "path": "/campaigns/abc-123"},
            )


if __name__ == "__main__":
    unittest.main()
