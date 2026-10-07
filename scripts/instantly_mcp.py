#!/usr/bin/env python3
"""Private ChatGPT MCP boundary for Leadscanner + Instantly.

No send, reply, forward, campaign activation, sequence mutation, or warmup
mutation tool is registered here.
"""
from __future__ import annotations

import hmac
import json
import os

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from instantly_client import InstantlyClient
from instantly_service import (
    DEFAULT_REGISTRY_URL,
    DEFAULT_REPOSITORY,
    stage_exact_approved_lead,
)
from instantly_webhook import apply_registry_event
from update_dedupe_registry import (
    DEFAULT_SHEET_NAME,
    DEFAULT_SPREADSHEET_ID,
    _authorized_session,
    read_live_values,
)

WEBHOOK_HEADER = "x-leadscanner-webhook-secret"
MAX_WEBHOOK_BODY_BYTES = 256_000

server = MCPServer(
    "leadscanner-instantly",
    version="0.1.0",
    instructions=(
        "Instantly is execution infrastructure only. Read before writing. "
        "Never infer approval. add_approved_lead_to_campaign requires an exact "
        "Leadscanner preview run and approval token. No sending or campaign "
        "activation capability exists on this server."
    ),
)


def _env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name.lower()}_required")
    return value


def _client() -> InstantlyClient:
    return InstantlyClient(_env("INSTANTLY_API_KEY"))


READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)


@server.tool(annotations=READ)
def list_campaigns(limit: int = 50, starting_after: str | None = None, status: int | None = None) -> dict:
    """List Instantly campaigns in the connected workspace."""
    return _client().list_campaigns(limit=limit, starting_after=starting_after, status=status)


@server.tool(annotations=READ)
def get_campaign(campaign_id: str) -> dict:
    """Read one Instantly campaign, including its non-sending/sending status."""
    return _client().get_campaign(campaign_id)


@server.tool(annotations=READ)
def list_leads(campaign_id: str | None = None, limit: int = 50, starting_after: str | None = None) -> dict:
    """List Instantly leads, optionally filtered to a campaign."""
    return _client().list_leads(campaign=campaign_id, limit=limit, starting_after=starting_after)


@server.tool(annotations=READ)
def get_lead(instantly_lead_id: str) -> dict:
    """Read one Instantly lead by its Instantly ID."""
    return _client().get_lead(instantly_lead_id)


@server.tool(annotations=READ)
def get_emails(campaign_id: str | None = None, limit: int = 50) -> dict:
    """Read received Instantly emails/replies only. This tool cannot reply."""
    return _client().get_emails(campaign_id=campaign_id, received_only=True, limit=limit)


@server.tool(annotations=READ)
def get_campaign_analytics(campaign_id: str | None = None) -> dict:
    """Read Instantly campaign analytics."""
    return _client().get_campaign_analytics(campaign_id=campaign_id)


@server.tool(annotations=WRITE)
def add_approved_lead_to_campaign(
    preview_run_id: int,
    approval_token: str,
    campaign_id: str,
) -> dict:
    """Stage one exact approved Leadscanner lead into a Draft/Paused campaign.

    The server fetches the immutable preview itself, validates the exact approval
    token, rechecks the live canonical dedupe registry, verifies Instantly
    readback, and then records the staged identity in the canonical registry.
    It cannot activate or send the campaign.
    """
    return stage_exact_approved_lead(
        preview_run_id=preview_run_id,
        approval_token=approval_token,
        campaign_id=campaign_id,
        instantly_api_key=_env("INSTANTLY_API_KEY"),
        github_token=_env("GITHUB_TOKEN"),
        repository=os.getenv("GITHUB_REPOSITORY", DEFAULT_REPOSITORY).strip() or DEFAULT_REPOSITORY,
        registry_url=os.getenv("DEDUPE_REGISTRY_CSV_URL", DEFAULT_REGISTRY_URL).strip() or DEFAULT_REGISTRY_URL,
    )


@server.tool(annotations=WRITE)
def block_email(email: str) -> dict:
    """Add one exact email address to the Instantly block list."""
    return _client().block_email(email)


@server.tool(annotations=WRITE)
def block_domain(domain: str) -> dict:
    """Add one exact domain to the Instantly block list."""
    return _client().block_domain(domain)


def verify_webhook_secret(provided: str | None, expected: str | None) -> bool:
    left = str(provided or "").encode("utf-8")
    right = str(expected or "").encode("utf-8")
    return bool(left and right and hmac.compare_digest(left, right))


def process_webhook_payload(payload: dict) -> dict:
    session, _ = _authorized_session()
    spreadsheet_id = os.getenv("LEAD_REGISTRY_SPREADSHEET_ID", DEFAULT_SPREADSHEET_ID).strip()
    sheet_name = os.getenv("LEAD_REGISTRY_SHEET_NAME", DEFAULT_SHEET_NAME).strip()
    current = read_live_values(session, spreadsheet_id, sheet_name)
    plan = apply_registry_event(session, spreadsheet_id, sheet_name, payload, current)
    return {
        "status": "green",
        "event_type": plan["event"]["event_type"],
        "registry_row": plan["sheet_row"],
        "registry_status": plan["after"][4],
        "automatic_send": False,
    }


@server.custom_route("/health", methods=["GET"])
async def health(_: Request) -> Response:
    return JSONResponse({
        "status": "ok",
        "service": "leadscanner-instantly",
        "automatic_send": False,
    })


@server.custom_route("/webhooks/instantly", methods=["POST"])
async def instantly_webhook(request: Request) -> Response:
    expected = os.getenv("INSTANTLY_WEBHOOK_SECRET", "")
    if not expected:
        return JSONResponse({"error": "webhook_not_configured"}, status_code=503)
    if not verify_webhook_secret(request.headers.get(WEBHOOK_HEADER), expected):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    body = await request.body()
    if len(body) > MAX_WEBHOOK_BODY_BYTES:
        return JSONResponse({"error": "payload_too_large"}, status_code=413)
    try:
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload_must_be_object")
        result = process_webhook_payload(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception:
        return JSONResponse({"error": "webhook_processing_failed"}, status_code=500)
    return JSONResponse(result, status_code=200)


app = server.streamable_http_app(
    stateless_http=True,
    json_response=True,
    max_request_body_size=1_000_000,
)


if __name__ == "__main__":
    server.run(
        transport="streamable-http",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        stateless_http=True,
        json_response=True,
        max_request_body_size=1_000_000,
    )
