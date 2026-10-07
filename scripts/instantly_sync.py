#!/usr/bin/env python3
"""Scheduled Instantly -> canonical Dedupe Registry reconciliation.

This is the no-hosting replacement for inbound webhooks. It polls Instantly and
updates only already-existing registry rows. It never creates leads, sends mail,
activates campaigns, or creates registry identities.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from instantly_client import InstantlyClient
from instantly_webhook import apply_registry_event, plan_registry_event_update
from update_dedupe_registry import (
    DEFAULT_SHEET_NAME,
    DEFAULT_SPREADSHEET_ID,
    _authorized_session,
    read_live_values,
)

EVENT_PRIORITY = {
    "lead_unsubscribed": 100,
    "email_bounced": 95,
    "lead_closed": 90,
    "lead_meeting_completed": 85,
    "lead_lost": 83,
    "lead_no_show": 82,
    "lead_meeting_booked": 80,
    "lead_wrong_person": 75,
    "lead_not_interested": 70,
    "lead_interested": 65,
    "lead_out_of_office": 60,
    "reply_received": 50,
    "lead_skipped": 30,
    "campaign_completed_for_lead_without_reply": 10,
}
INTEREST_EVENTS = {
    4: "lead_closed",
    3: "lead_meeting_completed",
    2: "lead_meeting_booked",
    1: "lead_interested",
    0: "lead_out_of_office",
    -1: "lead_not_interested",
    -2: "lead_wrong_person",
    -3: "lead_lost",
    -4: "lead_no_show",
}


def _text(value: object) -> str:
    return str(value or "").strip()


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _stable_timestamp(lead: dict, *preferred: str) -> str:
    for key in (*preferred, "timestamp_updated", "timestamp_last_touch", "timestamp_created"):
        value = _text(lead.get(key))
        if value:
            return value
    return ""


def event_from_lead(lead: dict) -> dict | None:
    """Map current Instantly lead state to one highest-value registry event."""
    if not isinstance(lead, dict):
        return None
    email = _text(lead.get("email")).casefold()
    if not email or "@" not in email:
        return None

    status = _int(lead.get("status"), 0)
    interest = _int(lead.get("lt_interest_status"), 999)
    event_type = ""
    timestamp = ""

    if status == -2:
        event_type = "lead_unsubscribed"
        timestamp = _stable_timestamp(lead)
    elif status == -1:
        event_type = "email_bounced"
        timestamp = _stable_timestamp(lead)
    elif interest in INTEREST_EVENTS:
        event_type = INTEREST_EVENTS[interest]
        timestamp = _stable_timestamp(lead, "timestamp_last_interest_change")
    elif status == -3:
        event_type = "lead_skipped"
        timestamp = _stable_timestamp(lead)
    elif _int(lead.get("email_reply_count"), 0) > 0 or _text(lead.get("timestamp_last_reply")):
        event_type = "reply_received"
        timestamp = _stable_timestamp(lead, "timestamp_last_reply")
    elif status == 3:
        event_type = "campaign_completed_for_lead_without_reply"
        timestamp = _stable_timestamp(lead)
    else:
        return None

    if not timestamp:
        return None
    return {
        "event_type": event_type,
        "lead_email": email,
        "campaign_id": _text(lead.get("campaign") or lead.get("campaign_id")),
        "timestamp": timestamp,
        "instantly_lead_id": _text(lead.get("id")),
    }


def _timestamp_rank(value: object) -> str:
    text = _text(value)
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError as exc:
        raise ValueError("instantly_lead_timestamp_invalid") from exc


def select_events(leads: list[dict]) -> list[dict]:
    """Choose one deterministic current event per email."""
    selected: dict[str, dict] = {}
    for lead in leads:
        event = event_from_lead(lead)
        if not event:
            continue
        email = event["lead_email"]
        candidate = (
            EVENT_PRIORITY[event["event_type"]],
            _timestamp_rank(event["timestamp"]),
            event["event_type"],
            event.get("instantly_lead_id", ""),
        )
        current = selected.get(email)
        if current is None:
            selected[email] = event
            continue
        existing = (
            EVENT_PRIORITY[current["event_type"]],
            _timestamp_rank(current["timestamp"]),
            current["event_type"],
            current.get("instantly_lead_id", ""),
        )
        if candidate > existing:
            selected[email] = event
    return [selected[email] for email in sorted(selected)]


def fetch_all_leads(client: InstantlyClient, *, max_leads: int = 10000) -> list[dict]:
    """Fetch a bounded complete lead view before any registry mutation."""
    maximum = min(max(int(max_leads), 1), 50000)
    rows: list[dict] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while len(rows) < maximum:
        limit = min(100, maximum - len(rows))
        page = client.list_leads(limit=limit, starting_after=cursor) or {}
        batch = page.get("items")
        if not isinstance(batch, list):
            raise RuntimeError("instantly_lead_page_items_must_be_list")
        next_cursor = _text(page.get("next_starting_after")) or None
        if not batch:
            if next_cursor:
                raise RuntimeError("instantly_lead_page_empty_with_cursor")
            break
        if any(not isinstance(item, dict) for item in batch):
            raise RuntimeError("instantly_lead_page_item_must_be_object")
        rows.extend(batch)
        if next_cursor:
            if next_cursor == cursor or next_cursor in seen_cursors:
                raise RuntimeError("instantly_lead_pagination_cursor_loop")
            seen_cursors.add(next_cursor)
        cursor = next_cursor
        if not cursor:
            break
    if len(rows) >= maximum and cursor:
        raise RuntimeError("instantly_sync_lead_limit_reached_before_complete_snapshot")
    return rows


def sync_registry(*, api_key: str, max_leads: int = 10000) -> dict:
    client = InstantlyClient(api_key)
    leads = fetch_all_leads(client, max_leads=max_leads)
    events = select_events(leads)

    session, service_account = _authorized_session()
    spreadsheet_id = os.getenv("LEAD_REGISTRY_SPREADSHEET_ID", DEFAULT_SPREADSHEET_ID).strip()
    sheet_name = os.getenv("LEAD_REGISTRY_SHEET_NAME", DEFAULT_SHEET_NAME).strip()
    current = read_live_values(session, spreadsheet_id, sheet_name)

    updated = 0
    unchanged = 0
    missing = 0
    ambiguous = 0
    errors: list[dict] = []

    for event in events:
        try:
            plan = plan_registry_event_update(event, current, source_marker="instantly:poll")
        except ValueError as exc:
            message = str(exc)
            if message == "registry_event_identity_not_found":
                missing += 1
                continue
            if message == "registry_event_identity_ambiguous":
                ambiguous += 1
                errors.append({"email": event["lead_email"], "error": message})
                continue
            raise

        if plan["after"] == plan["before"]:
            unchanged += 1
            continue

        applied = apply_registry_event(
            session,
            spreadsheet_id,
            sheet_name,
            event,
            current,
            source_marker="instantly:poll",
        )
        current[applied["sheet_row"] - 1] = applied["after"]
        updated += 1

    return {
        "schema_version": "leadscanner-instantly-sync/1.0",
        "status": "green" if not errors else "yellow",
        "lead_count": len(leads),
        "event_candidate_count": len(events),
        "registry_updated_count": updated,
        "registry_unchanged_count": unchanged,
        "registry_identity_missing_count": missing,
        "registry_identity_ambiguous_count": ambiguous,
        "errors": errors,
        "registry_authenticated": bool(service_account),
        "automatic_send": False,
        "instantly_mutation": False,
        "creates_registry_identity": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-leads", type=int, default=10000)
    args = parser.parse_args()
    api_key = os.getenv("INSTANTLY_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("INSTANTLY_API_KEY is required")
    result = sync_registry(api_key=api_key, max_leads=args.max_leads)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "INSTANTLY_SYNC="
        + result["status"]
        + f" leads={result['lead_count']} updated={result['registry_updated_count']}"
        + f" missing={result['registry_identity_missing_count']}"
    )
    return 0 if result["status"] == "green" else 2


if __name__ == "__main__":
    raise SystemExit(main())
