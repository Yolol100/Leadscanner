#!/usr/bin/env python3
"""Normalize Instantly webhook events and safely update existing registry rows."""
from __future__ import annotations

from datetime import datetime, timezone

from update_dedupe_registry import HEADERS, normalize_domain, normalize_row, split_values

EVENT_ALIASES = {
    "reply_received": "reply",
    "email_bounced": "bounce",
    "lead_unsubscribed": "unsubscribe",
    "lead_interested": "interested",
    "lead_is_interested": "interested",
    "interested": "interested",
    "lead_not_interested": "not_interested",
    "lead_is_not_interested": "not_interested",
    "not_interested": "not_interested",
    "lead_meeting_booked": "meeting_booked",
    "lead_meeting_completed": "meeting_completed",
    "lead_closed": "closed",
    "lead_out_of_office": "out_of_office",
    "lead_wrong_person": "wrong_person",
    "lead_no_show": "no_show",
    "lead_lost": "lost",
    "lead_skipped": "skipped",
    "campaign_completed": "campaign_completed",
    "campaign_completed_for_lead_without_reply": "campaign_completed_no_reply",
}

STATUS_BY_KIND = {
    "reply": "replied",
    "bounce": "bounced",
    "unsubscribe": "unsubscribed",
    "interested": "interested",
    "not_interested": "not_interested",
    "meeting_booked": "meeting_booked",
    "meeting_completed": "meeting_completed",
    "closed": "closed",
    "out_of_office": "out_of_office",
    "wrong_person": "wrong_person",
    "no_show": "no_show",
    "lost": "lost",
    "skipped": "skipped",
    "campaign_completed": "campaign_completed",
    "campaign_completed_no_reply": "campaign_completed_no_reply",
}

TERMINAL_STATUSES = {"unsubscribed", "bounced"}


def _text(value) -> str:
    return str(value or "").strip()


def normalize_event(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("webhook_payload_must_be_object")
    raw_type = _text(payload.get("event_type")).casefold()
    kind = EVENT_ALIASES.get(raw_type)
    if not kind:
        raise ValueError(f"unsupported_instantly_event:{raw_type or 'missing'}")
    email = _text(payload.get("lead_email") or payload.get("email")).casefold()
    if not email or "@" not in email:
        raise ValueError("webhook_lead_email_required")
    timestamp = _text(payload.get("timestamp"))
    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "kind": kind,
        "event_type": raw_type,
        "lead_email": email,
        "campaign_id": _text(payload.get("campaign_id")),
        "campaign_name": _text(payload.get("campaign_name")),
        "workspace": _text(payload.get("workspace")),
        "email_id": _text(payload.get("email_id")),
        "timestamp": timestamp,
    }


def _merge_semicolon(existing: str, value: str) -> str:
    values = [part.strip() for part in existing.split(";") if part.strip()]
    if value and value not in values:
        values.append(value)
    return ";".join(values)


def plan_registry_event_update(
    payload: dict,
    current_values: list[list[object]],
    *,
    source_marker: str = "instantly:webhook",
) -> dict:
    if not _text(source_marker).startswith("instantly:"):
        raise ValueError("invalid_instantly_source_marker")
    event = normalize_event(payload)
    if not current_values or normalize_row(current_values[0]) != HEADERS:
        raise ValueError("live_registry_headers_mismatch")

    matches = []
    for sheet_row_index, raw in enumerate(current_values[1:], start=2):
        row = normalize_row(raw)
        if event["lead_email"] in split_values(row[3]):
            matches.append((sheet_row_index, row))

    if len(matches) != 1:
        reason = "registry_event_identity_not_found" if not matches else "registry_event_identity_ambiguous"
        raise ValueError(reason)

    row_index, before = matches[0]
    after = list(before)
    incoming = STATUS_BY_KIND[event["kind"]]
    current_status = after[4].casefold()
    if current_status not in TERMINAL_STATUSES or incoming in TERMINAL_STATUSES:
        after[4] = incoming

    event_marker = f"instantly:{event['event_type']}"
    after[5] = _merge_semicolon(after[5], event_marker)
    after[7] = event["timestamp"]
    after[8] = _merge_semicolon(after[8], _text(source_marker))
    after[9] = "TRUE"

    return {
        "schema_version": "leadscanner-instantly-registry-event/1.0",
        "status": "green",
        "sheet_row": row_index,
        "event": event,
        "before": before,
        "after": after,
        "identity": {
            "email": event["lead_email"],
            "domain": normalize_domain(before[2] or before[1]),
        },
        "safety": {
            "creates_new_registry_row": False,
            "preserves_suppression": True,
            "automatic_send": False,
        },
    }


def apply_registry_event(
    session,
    spreadsheet_id: str,
    sheet_name: str,
    payload: dict,
    current_values: list[list[object]],
    *,
    source_marker: str = "instantly:webhook",
):
    """Update exactly one existing A:J row and verify exact readback."""
    from urllib.parse import quote

    plan = plan_registry_event_update(payload, current_values, source_marker=source_marker)
    row_number = plan["sheet_row"]
    range_name = quote(f"{sheet_name}!A{row_number}:J{row_number}", safe="")
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range_name}"
        "?valueInputOption=RAW"
    )
    response = session.put(
        url,
        json={"majorDimension": "ROWS", "values": [plan["after"]]},
        timeout=20,
    )
    if response.status_code not in {200, 201}:
        raise RuntimeError(
            f"registry_event_write_failed status={response.status_code} body={response.text[:300]}"
        )

    readback = session.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range_name}",
        timeout=20,
    )
    if readback.status_code != 200:
        raise RuntimeError(f"registry_event_readback_failed status={readback.status_code}")
    values = readback.json().get("values") or []
    if len(values) != 1 or normalize_row(values[0]) != plan["after"]:
        raise RuntimeError("registry_event_exact_readback_mismatch")
    return plan
