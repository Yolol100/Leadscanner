import asyncio
import os
import unittest
from unittest.mock import patch

from mcp import Client

import instantly_mcp


class InstantlyMcpTests(unittest.TestCase):
    def test_webhook_secret_is_constant_time_contract_and_fail_closed(self):
        self.assertFalse(instantly_mcp.verify_webhook_secret(None, "secret"))
        self.assertFalse(instantly_mcp.verify_webhook_secret("wrong", "secret"))
        self.assertFalse(instantly_mcp.verify_webhook_secret("secret", None))
        self.assertTrue(instantly_mcp.verify_webhook_secret("secret", "secret"))

    def test_tool_surface_contains_no_sending_or_activation(self):
        async def inspect():
            async with Client(instantly_mcp.server) as client:
                result = await client.list_tools()
                return {tool.name: tool for tool in result.tools}

        tools = asyncio.run(inspect())
        expected = {
            "list_campaigns",
            "get_campaign",
            "list_leads",
            "get_lead",
            "get_emails",
            "get_campaign_analytics",
            "add_approved_lead_to_campaign",
            "block_email",
            "block_domain",
        }
        self.assertEqual(set(tools), expected)
        for forbidden in {
            "send_email",
            "reply_to_email",
            "forward_email",
            "activate_campaign",
            "create_campaign",
            "pause_campaign",
        }:
            self.assertNotIn(forbidden, tools)

    def test_read_tools_are_annotated_read_only(self):
        async def inspect():
            async with Client(instantly_mcp.server) as client:
                result = await client.list_tools()
                return {tool.name: tool for tool in result.tools}

        tools = asyncio.run(inspect())
        self.assertTrue(tools["list_campaigns"].annotations.read_only_hint)
        self.assertTrue(tools["get_emails"].annotations.read_only_hint)
        self.assertFalse(tools["add_approved_lead_to_campaign"].annotations.read_only_hint)

    @patch("instantly_mcp.stage_exact_approved_lead")
    def test_add_tool_passes_only_preview_token_campaign_identifiers(self, stage_mock):
        stage_mock.return_value = {"status": "green", "automatic_send": False}
        with patch.dict(
            os.environ,
            {
                "INSTANTLY_API_KEY": "key",
                "GITHUB_TOKEN": "gh",
                "GITHUB_REPOSITORY": "Yolol100/Leadscanner",
            },
            clear=False,
        ):
            result = instantly_mcp.add_approved_lead_to_campaign(
                123,
                "growth-aaaaaaaaaaaaaaaaaaaa@1111111111111111",
                "campaign-1",
            )
        self.assertFalse(result["automatic_send"])
        kwargs = stage_mock.call_args.kwargs
        self.assertEqual(set(kwargs), {
            "preview_run_id",
            "approval_token",
            "campaign_id",
            "instantly_api_key",
            "github_token",
            "repository",
            "registry_url",
        })
        self.assertEqual(kwargs["preview_run_id"], 123)


if __name__ == "__main__":
    unittest.main()
