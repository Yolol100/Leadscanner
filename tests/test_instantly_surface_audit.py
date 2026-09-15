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
        "/api/v2/workspaces/{id}/members": {
            "get": {"operationId": "listWorkspaceMembers", "tags": ["Workspace"]},
            "post": {"operationId": "inviteWorkspaceMember", "tags": ["Workspace"]},
        },
        "/api/v2/supersearch/preview": {
            "post": {"operationId": "previewSuperSearch", "tags": ["SuperSearch"]},
        },
    }
}


class InstantlySurfaceAuditTests(unittest.TestCase):
    def test_api_supported_surfaces_are_detected(self):
        result = audit(SPEC)
        self.assertEqual(result["surfaces"]["campaigns"]["control"], "read_write")
        self.assertEqual(result["surfaces"]["leads"]["control"], "read_only")
        self.assertEqual(result["surfaces"]["workspace_members"]["control"], "read_write")
        self.assertEqual(result["surfaces"]["supersearch"]["control"], "read_write")

    def test_ui_only_surfaces_remain_not_proven(self):
        result = audit(SPEC)
        self.assertEqual(result["surfaces"]["instantly_ai_memory"]["control"], "not_proven")
        self.assertEqual(result["surfaces"]["crm_calls"]["control"], "not_proven")
        self.assertEqual(result["surfaces"]["automations"]["control"], "not_proven")

    def test_email_reply_counts_as_email_write(self):
        result = audit(SPEC)
        self.assertEqual(result["surfaces"]["emails"]["control"], "read_write")
        self.assertGreaterEqual(result["surfaces"]["emails"]["operation_count"], 1)


if __name__ == "__main__":
    unittest.main()
