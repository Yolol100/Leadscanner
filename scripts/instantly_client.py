#!/usr/bin/env python3
"""Minimal fail-closed Instantly API v2 adapter for Leadscanner.

This module deliberately exposes no campaign activation, email send, reply,
forward, test-send, warmup mutation, or sequence mutation operation.
"""
from __future__ import annotations

import re
from urllib.parse import quote

import requests

from dedupe_preflight import match_candidate

BASE_URL = "https://api.instantly.ai/api/v2"
SAFE_CAMPAIGN_STATUSES = {0, 2}  # Draft, Paused
LEAD_ID_RE = re.compile(r"^growth-[0-9a-f]{20}$")


class InstantlyError(RuntimeError):
    pass


class InstantlyClient:
    def __init__(self, api_key: str, *, session=None, timeout: int = 20, base_url: str = BASE_URL):
        key = str(api_key or "").strip()
        if not key:
            raise ValueError("instantly_api_key_required")
        self.api_key = key
        self.session = session or requests.Session()
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")

    def _request(self, method: str, path: str, *, params=None, json=None):
        response = self.session.request(
            method,
            self.base_url + path,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            params=params,
            json=json,
            timeout=self.timeout,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise InstantlyError(
                f"instantly_api_error status={response.status_code} body={response.text[:500]}"
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def list_campaigns(self, *, limit: int = 50, starting_after: str | None = None, status: int | None = None):
        params = {"limit": min(max(int(limit), 1), 100)}
        if starting_after:
            params["starting_after"] = starting_after
        if status is not None:
            params["status"] = int(status)
        return self._request("GET", "/campaigns", params=params)

    def get_campaign(self, campaign_id: str):
        return self._request("GET", f"/campaigns/{quote(str(campaign_id), safe='')}")

    def list_leads(self, *, campaign: str | None = None, limit: int = 50, starting_after: str | None = None):
        body = {"limit": min(max(int(limit), 1), 100)}
        if campaign:
            body["campaign"] = campaign
        if starting_after:
            body["starting_after"] = starting_after
        return self._request("POST", "/leads/list", json=body)

    def get_lead(self, lead_id: str):
        return self._request("GET", f"/leads/{quote(str(lead_id), safe='')}")

    def get_emails(self, *, campaign_id: str | None = None, received_only: bool = True, limit: int = 50):
        params = {"limit": min(max(int(limit), 1), 100)}
        if campaign_id:
            params["campaign_id"] = campaign_id
        if received_only:
            params["email_type"] = "received"
        return self._request("GET", "/emails", params=params)

    def get_campaign_analytics(self, *, campaign_id: str | None = None):
        params = {}
        if campaign_id:
            params["id"] = campaign_id
        return self._request("GET", "/campaigns/analytics", params=params)

    def add_approved_lead_to_campaign(
        self,
        *,
        approved_batch: dict,
        lead_id: str,
        campaign_id: str,
        registry_rows: list[dict],
    ):
        """Add one exact approved lead, but only to a non-sending campaign state."""
        if approved_batch.get("schema_version") != "leadscanner-approved-revalidation/1.0":
            raise ValueError("approved_revalidation_batch_required")
        safety = approved_batch.get("safety") or {}
        if safety.get("automatic_send") is not False:
            raise ValueError("automatic_send_must_be_false")
        if safety.get("dedupe_rechecked_immediately_before_mutation") is not True:
            raise ValueError("live_dedupe_revalidation_required")

        rows = [row for row in (approved_batch.get("rows") or []) if row.get("lead_id") == lead_id]
        if len(rows) != 1:
            raise ValueError("exact_approved_lead_required")
        row = rows[0]
        if not LEAD_ID_RE.fullmatch(str(lead_id or "")):
            raise ValueError("invalid_leadscanner_lead_id")
        if row.get("status") != "review_draft" or row.get("contact_basis_status") != "review_required":
            raise ValueError("review_approval_contract_required")
        if row.get("automatic_send") is not False:
            raise ValueError("automatic_send_must_be_false")

        candidate = {
            "company": row.get("company"),
            "official_domain": row.get("official_domain"),
            "website": row.get("website"),
            "email": row.get("email"),
            "lead_id": row.get("lead_id"),
        }
        if match_candidate(candidate, registry_rows):
            raise ValueError("live_dedupe_match_blocks_instantly_mutation")

        campaign = self.get_campaign(campaign_id)
        campaign_status = int(campaign.get("status"))
        if campaign_status not in SAFE_CAMPAIGN_STATUSES:
            raise ValueError("campaign_must_be_draft_or_paused")

        payload = {
            "campaign": campaign_id,
            "email": str(row.get("email") or "").strip(),
            "company_name": str(row.get("company") or "").strip(),
            "website": str(row.get("website") or "").strip(),
            "skip_if_in_workspace": True,
            "skip_if_in_campaign": True,
            "custom_variables": {
                "leadscanner_lead_id": lead_id,
                "leadscanner_review_status": "approved",
            },
        }
        if not payload["email"]:
            raise ValueError("approved_email_required")
        return self._request("POST", "/leads", json=payload)

    def block_email(self, email: str):
        value = str(email or "").strip().casefold()
        if "@" not in value:
            raise ValueError("valid_email_required")
        return self._request("POST", "/block-lists-entries", json={"bl_value": value})

    def block_domain(self, domain: str):
        value = str(domain or "").strip().casefold().removeprefix("www.")
        if not value or "@" in value or "." not in value:
            raise ValueError("valid_domain_required")
        return self._request("POST", "/block-lists-entries", json={"bl_value": value})


EXPOSED_TOOLS = (
    "list_campaigns",
    "get_campaign",
    "list_leads",
    "get_lead",
    "get_emails",
    "get_campaign_analytics",
    "add_approved_lead_to_campaign",
    "block_email",
    "block_domain",
)

FORBIDDEN_TOOL_NAMES = (
    "activate_campaign",
    "send_email",
    "send_test_email",
    "reply_to_email",
    "forward_email",
    "create_campaign",
    "patch_campaign_sequence",
)
