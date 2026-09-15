from __future__ import annotations

import unittest

from instantly_surface_audit import audit


SPEC = {
    "paths": {
        "/api/v2/campaigns": {
            "get": {"operationId": "listCampaigns", "tags": ["Campaign"]},
            "post": {"operationId": "createCampaign", "tags": ["Campaign"]},
        },
        "/api/v2/leads": {
            "get": {"operationId": "listLeads", "tags": ["Lead"]},
        },
        "/api/v2/emails/reply": {
            "post": {"operationId": "replyToEmail", "tags": ["Email"]},
        },
        "/api/v2/workspace-members": {
            "get": {"operationId": "listWorkspaceMember", "tags": ["WorkspaceMember"]},
            "post": {"operationId": "createWorkspaceMember", "tags": ["WorkspaceMember"]},
        },
        "/api/v2/supersearch-enrichment/saved-searches": {
            "get": {"operationId": "listSavedSearches", "tags": ["SuperSearchEnrichment"]},
            "post": {"operationId": "createSavedSearch", "tags": ["SuperSearchEnrichment"]},
        },
        "/api/v2/ai-agents/sales": {
            "get": {"operationId": "listSalesAgents", "tags": ["AISalesAgent"]},
            "post": {"operationId": "createSalesAgent", "tags": ["AISalesAgent"]},
        },
        "/api/v2/ai-agents/sales/{id}/guidance-rules": {
            "get": {"operationId": "listSalesAgentGuidanceRules", "tags": ["AISalesAgent"]},
            "post": {"operationId": "createSalesAgentGuidanceRule", "tags": ["AISalesAgent"]},
        },
        "/api/v2/campaigns/analytics/overview": {
            "get": {"operationId": "getCampaignAnalyticsOverview", "tags": ["Campaign", "Analytics"]},
        },
        "/api/v2/accounts/test/vitals": {
            "post": {"operationId": "testAccountVitals", "tags": ["Account", "Analytics"]},
        },
    }
}


class InstantlySurfaceAuditTests(unittest.TestCase):
    def test_api_supported_surfaces_are_detected(self):
        result = audit(SPEC)
        self.assertEqual(result["surfaces"]["campaigns"]["control"], "read_write")
        self.assertEqual(result["surfaces"]["leads"]["control"], "read_only")
        self.assertEqual(result["surfaces"]["workspace_members"]["control"], "read_write")
        self.assertEqual(result["surfaces"]["supersearch_saved_searches"]["control"], "read_write")
        self.assertEqual(result["surfaces"]["ai_sales_agent"]["control"], "read_write")
        self.assertEqual(result["surfaces"]["ai_sales_guidance"]["control"], "read_write")

    def test_ui_only_surfaces_remain_not_proven(self):
        result = audit(SPEC)
        self.assertEqual(result["surfaces"]["instantly_ai_business_details"]["control"], "not_proven")
        self.assertEqual(result["surfaces"]["instantly_ai_customer_profiles"]["control"], "not_proven")
        self.assertEqual(result["surfaces"]["instantly_ai_saved_memories"]["control"], "not_proven")
        self.assertEqual(result["surfaces"]["instantly_ai_tasks"]["control"], "not_proven")
        self.assertEqual(result["surfaces"]["crm_calls"]["control"], "not_proven")
        self.assertEqual(result["surfaces"]["automations"]["control"], "not_proven")

    def test_email_reply_counts_as_email_write(self):
        result = audit(SPEC)
        self.assertEqual(result["surfaces"]["emails_unibox"]["control"], "read_write")
        self.assertEqual(result["surfaces"]["emails_unibox"]["operation_count"], 1)

    def test_readish_post_does_not_claim_configuration_write(self):
        result = audit(SPEC)
        self.assertEqual(result["surfaces"]["analytics_reports"]["control"], "read_only")
        self.assertEqual(result["surfaces"]["analytics_reports"]["write_operation_count"], 0)


if __name__ == "__main__":
    unittest.main()
