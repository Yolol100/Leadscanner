import unittest

from instantly_client import FORBIDDEN_TOOL_NAMES, InstantlyClient, InstantlyError


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(self._payload)
        self.content = b"{}" if status_code != 204 else b""
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def approved_batch():
    return {
        "schema_version": "leadscanner-approved-revalidation/1.0",
        "rows": [{
            "lead_id": "growth-aaaaaaaaaaaaaaaaaaaa",
            "company": "Acme",
            "website": "https://acme.nl/",
            "official_domain": "acme.nl",
            "email": "info@acme.nl",
            "status": "review_draft",
            "contact_basis_status": "review_required",
            "automatic_send": False,
        }],
        "safety": {
            "automatic_send": False,
            "dedupe_rechecked_immediately_before_mutation": True,
        },
    }


class InstantlyClientTests(unittest.TestCase):
    def test_read_methods_use_v2_and_bearer(self):
        session = FakeSession([FakeResponse(payload={"items": []})])
        client = InstantlyClient("secret", session=session)
        client.list_campaigns(limit=10)
        method, url, kwargs = session.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://api.instantly.ai/api/v2/campaigns")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")

    def test_safe_read_retries_once_on_429_without_leaking_body(self):
        sleeps = []
        session = FakeSession([
            FakeResponse(status_code=429, payload={"message": "sensitive detail"}, headers={"Retry-After": "0"}),
            FakeResponse(payload={"items": []}),
        ])
        client = InstantlyClient("secret", session=session, sleep_fn=sleeps.append)
        result = client.list_campaigns(limit=10)
        self.assertEqual(result, {"items": []})
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(sleeps, [0.0])

    def test_write_does_not_retry_on_server_error(self):
        session = FakeSession([
            FakeResponse(payload={"id": "c1", "status": 2}),
            FakeResponse(status_code=503, payload={"message": "do not repeat this write"}),
        ])
        client = InstantlyClient("secret", session=session, sleep_fn=lambda _: None)
        with self.assertRaisesRegex(InstantlyError, "status=503"):
            client.add_approved_lead_to_campaign(
                approved_batch=approved_batch(),
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=[],
            )
        self.assertEqual(len(session.calls), 2)

    def test_api_error_does_not_include_response_body(self):
        session = FakeSession([
            FakeResponse(status_code=400, payload={"message": "private lead content"}),
        ])
        client = InstantlyClient("secret", session=session, sleep_fn=lambda _: None)
        with self.assertRaises(InstantlyError) as caught:
            client.list_campaigns(limit=10)
        self.assertIn("status=400", str(caught.exception))
        self.assertNotIn("private lead content", str(caught.exception))

    def test_email_reads_support_cursor_pagination(self):
        session = FakeSession([FakeResponse(payload={"items": [], "next_starting_after": None})])
        client = InstantlyClient("secret", session=session)
        client.get_emails(
            campaign_id="c1",
            received_only=True,
            limit=25,
            starting_after="cursor-1",
        )
        method, url, kwargs = session.calls[0]
        self.assertEqual((method, url), ("GET", "https://api.instantly.ai/api/v2/emails"))
        self.assertEqual(kwargs["params"]["campaign_id"], "c1")
        self.assertEqual(kwargs["params"]["email_type"], "received")
        self.assertEqual(kwargs["params"]["starting_after"], "cursor-1")

    def test_list_leads_supports_official_contact_and_list_filters(self):
        session = FakeSession([FakeResponse(payload={"items": []})])
        client = InstantlyClient("secret", session=session)
        client.list_leads(
            campaign="c1",
            list_id="list-1",
            contacts=["Lead@Example.com"],
            limit=25,
            starting_after="cursor-1",
        )
        method, url, kwargs = session.calls[0]
        self.assertEqual((method, url), ("POST", "https://api.instantly.ai/api/v2/leads/list"))
        self.assertEqual(kwargs["json"]["campaign"], "c1")
        self.assertEqual(kwargs["json"]["list_id"], "list-1")
        self.assertEqual(kwargs["json"]["contacts"], ["lead@example.com"])
        self.assertEqual(kwargs["json"]["starting_after"], "cursor-1")

    def test_add_requires_draft_or_paused_campaign(self):
        session = FakeSession([FakeResponse(payload={"id": "c1", "status": 1})])
        client = InstantlyClient("secret", session=session)
        with self.assertRaisesRegex(ValueError, "draft_or_paused"):
            client.add_approved_lead_to_campaign(
                approved_batch=approved_batch(),
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=[],
            )
        self.assertEqual(len(session.calls), 1)

    def test_add_approved_lead_uses_workspace_dedupe_flags(self):
        session = FakeSession([
            FakeResponse(payload={"id": "c1", "status": 2}),
            FakeResponse(payload={"id": "instantly-lead-1"}),
        ])
        client = InstantlyClient("secret", session=session)
        result = client.add_approved_lead_to_campaign(
            approved_batch=approved_batch(),
            lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
            campaign_id="c1",
            registry_rows=[],
        )
        self.assertEqual(result["id"], "instantly-lead-1")
        method, url, kwargs = session.calls[1]
        self.assertEqual((method, url), ("POST", "https://api.instantly.ai/api/v2/leads"))
        self.assertTrue(kwargs["json"]["skip_if_in_workspace"])
        self.assertTrue(kwargs["json"]["skip_if_in_campaign"])

    def test_live_registry_match_blocks_write(self):
        session = FakeSession([])
        client = InstantlyClient("secret", session=session)
        registry = [{
            "identity": {
                "company": "acme",
                "domains": {"acme.nl"},
                "emails": {"info@acme.nl"},
                "lead_ids": set(),
            },
            "status": "concept",
            "row_number": 2,
        }]
        with self.assertRaisesRegex(ValueError, "live_dedupe_match"):
            client.add_approved_lead_to_campaign(
                approved_batch=approved_batch(),
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=registry,
            )
        self.assertEqual(session.calls, [])

    def test_no_sending_tools_are_exposed(self):
        for name in FORBIDDEN_TOOL_NAMES:
            self.assertFalse(hasattr(InstantlyClient, name), name)


if __name__ == "__main__":
    unittest.main()
