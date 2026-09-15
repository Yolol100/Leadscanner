from __future__ import annotations

import unittest
from pathlib import Path

from instantly_bridge import InstantlyError
from instantly_write_selftest import run_write_selftest


class FakeClient:
    def __init__(self):
        self.marker = ""
        self.lead_deleted = False
        self.list_deleted = False
        self.calls = []

    def request(self, method, path, *, query=None, body=None):
        self.calls.append((method, path, body))
        if method == "POST" and path == "/lead-lists":
            return {"id": "list-12345678"}
        if method == "POST" and path == "/leads/add":
            lead = body["leads"][0]
            self.marker = lead["custom_variables"]["webactueel_test_marker"]
            self.assert_no_email(lead)
            return {
                "status": "success",
                "leads_uploaded": 1,
                "created_leads": [{"id": "lead-12345678", "email": None, "index": 0}],
            }
        if method == "GET" and path == "/leads/lead-12345678":
            if self.lead_deleted:
                raise InstantlyError("Instantly API HTTP 404")
            return {
                "id": "lead-12345678",
                "first_name": "Webactueel",
                "last_name": f"BridgeTest-{self.marker}",
                "custom_variables": {"webactueel_test_marker": self.marker},
            }
        if method == "DELETE" and path == "/leads/lead-12345678":
            self.lead_deleted = True
            return None
        if method == "DELETE" and path == "/lead-lists/list-12345678":
            self.list_deleted = True
            return None
        if method == "GET" and path == "/lead-lists/list-12345678":
            if self.list_deleted:
                raise InstantlyError("Instantly API HTTP 404")
            return {"id": "list-12345678"}
        raise AssertionError(f"unexpected request: {method} {path}")

    @staticmethod
    def assert_no_email(lead):
        if "email" in lead:
            raise AssertionError("self-test lead must not contain an email address")


class InstantlyWriteSelfTestTests(unittest.TestCase):
    def test_write_readback_and_cleanup_without_email_or_campaign(self):
        client = FakeClient()
        result = run_write_selftest(client)
        self.assertEqual(result["status"], "green")
        self.assertTrue(result["list_created"])
        self.assertTrue(result["lead_created"])
        self.assertTrue(result["readback_verified"])
        self.assertTrue(result["lead_cleanup"])
        self.assertTrue(result["list_cleanup"])
        self.assertFalse(result["email_used"])
        paths = [path for _, path, _ in client.calls]
        self.assertFalse(any("campaign" in path for path in paths))
        self.assertFalse(any("email" in path for path in paths))

    def test_workflow_is_owner_only_and_receives_only_instantly_secret(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "instantly-write-selftest-command.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("github.actor == 'Yolol100'", workflow)
        self.assertIn("INSTANTLY_API_KEY", workflow)
        self.assertNotIn("GOOGLE_SERVICE_ACCOUNT_JSON", workflow)
        self.assertNotIn("OUTREACH_MAIL_PASSWORD", workflow)
        self.assertNotIn("CAMPAIGN_ID", workflow)
        self.assertIn("SEND_PERMISSION=none", workflow)
        self.assertIn("ACTIVATION_INVOKED=false", workflow)


if __name__ == "__main__":
    unittest.main()
