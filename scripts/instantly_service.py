#!/usr/bin/env python3
"""Fail-closed orchestration for the Leadscanner -> Instantly boundary."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests

from approval_revalidation import revalidate_approved
from dedupe_preflight import load_registry
from instantly_client import InstantlyClient, approved_custom_variables
from preview_snapshot import fetch_snapshot
from review_selection import select_approved
from update_dedupe_registry import (
    DEFAULT_SHEET_NAME,
    DEFAULT_SPREADSHEET_ID,
    HEADERS,
    check_registry_access,
    update_registry,
)

DEFAULT_REPOSITORY = "Yolol100/Leadscanner"
DEFAULT_REGISTRY_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1p4vZnCdcex9zpTAV-ssebXqZcBS2TU6KfXwS-4d2iSI/export?format=csv&gid=1354777664"
)


def _text(value: object) -> str:
    return str(value or "").strip()


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().casefold() in {"1", "true", "yes", "on"}


def require_instantly_writes_enabled() -> None:
    if not _enabled("LEADSCANNER_INSTANTLY_WRITES_ENABLED"):
        raise RuntimeError("instantly_writes_disabled")


def fetch_live_registry(
    *,
    registry_url: str,
    session=requests,
) -> list[dict]:
    url = _text(registry_url)
    if not url.startswith("https://docs.google.com/spreadsheets/"):
        raise ValueError("registry_url_must_be_canonical_google_sheets_export")
    response = session.get(url, timeout=30)
    if response.status_code != 200 or not response.content:
        raise RuntimeError(f"registry_fetch_failed status={response.status_code}")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "dedupe-registry.csv"
        path.write_bytes(response.content)
        return load_registry(path)


def resolve_exact_approval(
    *,
    preview_run_id: int,
    approval_token: str,
    github_token: str,
    repository: str = DEFAULT_REPOSITORY,
    registry_url: str = DEFAULT_REGISTRY_URL,
    github_session=requests,
    registry_session=requests,
) -> dict:
    token = _text(approval_token).casefold()
    if not token:
        raise ValueError("approval_token_required")
    snapshot = fetch_snapshot(
        repository=repository,
        run_id=int(preview_run_id),
        token=_text(github_token),
        session=github_session,
    )
    selected = select_approved(snapshot["review_draft_batch"], token)
    registry_rows = fetch_live_registry(
        registry_url=registry_url,
        session=registry_session,
    )
    current = revalidate_approved(selected, registry_rows)
    if current.get("remaining_count") != 1:
        raise ValueError("approved_lead_no_longer_eligible")
    row = current["rows"][0]
    return {
        "snapshot": snapshot,
        "approved_current": current,
        "row": row,
        "registry_rows": registry_rows,
    }


def _registry_readback_for_staged(row: dict, campaign_id: str) -> dict:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    registry_row = [
        _text(row.get("company")),
        _text(row.get("website")),
        _text(row.get("official_domain")),
        _text(row.get("email")).casefold(),
        "instantly_staged",
        "instantly_staged",
        _text(row.get("lead_id")),
        now,
        f"instantly:campaign:{_text(campaign_id)}",
        "TRUE",
    ]
    return {
        "status": "green",
        "automatic_send": False,
        "draft_count": 1,
        "registry_headers": HEADERS,
        "registry_rows": [registry_row],
    }


def _verify_instantly_readback(observed: dict, *, row: dict, campaign_id: str) -> None:
    if not isinstance(observed, dict):
        raise RuntimeError("instantly_lead_readback_must_be_object")
    expected_email = _text(row.get("email")).casefold()
    observed_email = _text(observed.get("email")).casefold()
    if observed_email != expected_email:
        raise RuntimeError("instantly_lead_readback_email_mismatch")
    observed_campaign = _text(observed.get("campaign") or observed.get("campaign_id"))
    if observed_campaign != _text(campaign_id):
        raise RuntimeError("instantly_lead_readback_campaign_mismatch")
    observed_variables = observed.get("payload")
    if not isinstance(observed_variables, dict):
        observed_variables = observed.get("custom_variables")
    if not isinstance(observed_variables, dict):
        raise RuntimeError("instantly_lead_readback_variables_missing")
    for name, expected in approved_custom_variables(row).items():
        if observed_variables.get(name) != expected:
            raise RuntimeError(f"instantly_lead_readback_variable_mismatch:{name}")


def stage_approved_batch(
    *,
    approved_batch: dict,
    campaign_id: str,
    instantly_api_key: str,
    registry_url: str = DEFAULT_REGISTRY_URL,
    instantly_client: InstantlyClient | None = None,
    registry_session=requests,
    spreadsheet_id: str | None = None,
    sheet_name: str | None = None,
) -> dict:
    require_instantly_writes_enabled()
    campaign = _text(campaign_id)
    if not campaign:
        raise ValueError("campaign_id_required")
    if approved_batch.get("schema_version") != "leadscanner-approved-review-draft-batch/1.0":
        raise ValueError("approved_review_batch_required")

    rows = approved_batch.get("rows")
    approval = approved_batch.get("approval") or {}
    if not isinstance(rows, list):
        raise ValueError("approved_rows_must_be_list")
    if approval.get("automatic_send") is not False:
        raise ValueError("automatic_send_must_be_false")
    if isinstance(approval.get("approved_count"), bool) or approval.get("approved_count") != len(rows):
        raise ValueError("approved_count_mismatch")

    resolved_spreadsheet_id = (
        spreadsheet_id
        or os.getenv("LEAD_REGISTRY_SPREADSHEET_ID", "").strip()
        or DEFAULT_SPREADSHEET_ID
    )
    resolved_sheet_name = (
        sheet_name
        or os.getenv("LEAD_REGISTRY_SHEET_NAME", "").strip()
        or DEFAULT_SHEET_NAME
    )
    check_registry_access(
        spreadsheet_id=resolved_spreadsheet_id,
        sheet_name=resolved_sheet_name,
    )

    client = instantly_client or InstantlyClient(instantly_api_key)
    staged: list[dict] = []
    suppressed = 0

    for row in rows:
        one_batch = {
            "schema_version": approved_batch["schema_version"],
            "rows": [row],
            "approval": {
                **approval,
                "requested_count": 1,
                "approved_count": 1,
                "rejected_by_operator_count": 0,
                "automatic_send": False,
            },
            "safety": {
                **(approved_batch.get("safety") or {}),
                "automatic_send": False,
            },
        }
        fresh_registry_rows = fetch_live_registry(
            registry_url=registry_url,
            session=registry_session,
        )
        refreshed = revalidate_approved(one_batch, fresh_registry_rows)
        if refreshed.get("remaining_count") != 1:
            suppressed += 1
            continue

        current_row = refreshed["rows"][0]
        created = client.add_approved_lead_to_campaign(
            approved_batch=refreshed,
            lead_id=_text(current_row.get("lead_id")),
            campaign_id=campaign,
            registry_rows=fresh_registry_rows,
        )
        instantly_id = _text((created or {}).get("id"))
        if not instantly_id:
            raise RuntimeError("instantly_create_lead_missing_id")
        observed = client.get_lead(instantly_id)
        _verify_instantly_readback(observed, row=current_row, campaign_id=campaign)

        registry_result = update_registry(
            _registry_readback_for_staged(current_row, campaign),
            spreadsheet_id=resolved_spreadsheet_id,
            sheet_name=resolved_sheet_name,
        )
        if not registry_result.get("exact_readback"):
            raise RuntimeError("instantly_stage_registry_readback_failed")
        staged.append({
            "lead_id": _text(current_row.get("lead_id")),
            "instantly_lead_id": instantly_id,
            "email": _text(current_row.get("email")).casefold(),
            "registry_exact_readback": True,
        })

    return {
        "schema_version": "leadscanner-instantly-stage-batch/1.0",
        "status": "green",
        "campaign_id": campaign,
        "requested_count": len(rows),
        "staged_count": len(staged),
        "suppressed_count": suppressed,
        "staged": staged,
        "automatic_send": False,
        "campaign_activation_required": True,
    }


def stage_exact_approved_lead(
    *,
    preview_run_id: int,
    approval_token: str,
    campaign_id: str,
    instantly_api_key: str,
    github_token: str,
    repository: str = DEFAULT_REPOSITORY,
    registry_url: str = DEFAULT_REGISTRY_URL,
    instantly_client: InstantlyClient | None = None,
    github_session=requests,
    registry_session=requests,
    spreadsheet_id: str | None = None,
    sheet_name: str | None = None,
) -> dict:
    require_instantly_writes_enabled()
    resolved = resolve_exact_approval(
        preview_run_id=preview_run_id,
        approval_token=approval_token,
        github_token=github_token,
        repository=repository,
        registry_url=registry_url,
        github_session=github_session,
        registry_session=registry_session,
    )
    row = resolved["row"]
    resolved_spreadsheet_id = (
        spreadsheet_id
        or os.getenv("LEAD_REGISTRY_SPREADSHEET_ID", "").strip()
        or DEFAULT_SPREADSHEET_ID
    )
    resolved_sheet_name = (
        sheet_name
        or os.getenv("LEAD_REGISTRY_SHEET_NAME", "").strip()
        or DEFAULT_SHEET_NAME
    )
    check_registry_access(
        spreadsheet_id=resolved_spreadsheet_id,
        sheet_name=resolved_sheet_name,
    )

    fresh_registry_rows = fetch_live_registry(
        registry_url=registry_url,
        session=registry_session,
    )
    refreshed = revalidate_approved(resolved["approved_current"], fresh_registry_rows)
    if refreshed.get("remaining_count") != 1:
        raise ValueError("approved_lead_no_longer_eligible_after_registry_preflight")
    row = refreshed["rows"][0]

    client = instantly_client or InstantlyClient(instantly_api_key)
    created = client.add_approved_lead_to_campaign(
        approved_batch=refreshed,
        lead_id=_text(row.get("lead_id")),
        campaign_id=_text(campaign_id),
        registry_rows=fresh_registry_rows,
    )
    instantly_id = _text((created or {}).get("id"))
    if not instantly_id:
        raise RuntimeError("instantly_create_lead_missing_id")
    observed = client.get_lead(instantly_id)
    _verify_instantly_readback(observed, row=row, campaign_id=campaign_id)

    registry_result = update_registry(
        _registry_readback_for_staged(row, campaign_id),
        spreadsheet_id=resolved_spreadsheet_id,
        sheet_name=resolved_sheet_name,
    )
    if not isinstance(registry_result, dict) or registry_result.get("exact_readback") is not True:
        raise RuntimeError("instantly_stage_registry_readback_failed")

    return {
        "schema_version": "leadscanner-instantly-stage/1.0",
        "status": "green",
        "preview_run_id": int(preview_run_id),
        "preview_id": resolved["snapshot"]["preview_id"],
        "lead_id": _text(row.get("lead_id")),
        "campaign_id": _text(campaign_id),
        "instantly_lead_id": instantly_id,
        "instantly_readback": True,
        "registry_exact_readback": True,
        "automatic_send": False,
        "campaign_activation_available": False,
    }
