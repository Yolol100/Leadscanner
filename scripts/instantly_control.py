#!/usr/bin/env python3
"""GitHub command control plane for ChatGPT web -> Leadscanner -> Instantly.

Commands are immutable JSON files added under ``instantly-commands/inbox``.
Only named, allowlisted Instantly API v2 actions exist here; there is no generic
method/path command.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

from instantly_client import InstantlyClient, InstantlyError, SAFE_CAMPAIGN_STATUSES
from instantly_service import DEFAULT_REGISTRY_URL, DEFAULT_REPOSITORY, stage_exact_approved_lead

SCHEMA_VERSION = "leadscanner-instantly-command/1.0"
RESULT_SCHEMA_VERSION = "leadscanner-instantly-command-result/1.0"
COMMAND_PREFIX = "instantly-commands/inbox/"
COMMAND_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{5,120}$")

READ_ACTIONS = {
    "list_campaigns", "get_campaign", "campaign_sending_status", "campaign_analytics",
    "list_leads", "get_lead", "list_emails", "get_email", "count_unread_emails",
    "list_accounts", "get_account", "test_account_vitals", "warmup_analytics", "daily_account_analytics",
    "list_blocklist", "get_blocklist_entry", "get_background_job",
}
WRITE_ACTIONS = {
    "create_campaign_draft", "update_campaign", "pause_campaign", "activate_campaign",
    "delete_campaign", "update_lead", "delete_lead", "update_interest", "reply_email",
    "forward_email", "send_test_email", "mark_thread_read", "update_account",
    "pause_account", "resume_account", "enable_warmup", "disable_warmup",
    "block_email", "block_domain", "delete_blocklist_entry", "stage_approved_lead",
}
SEND_ACTIONS = {"activate_campaign", "reply_email", "forward_email", "send_test_email"}
DESTRUCTIVE_ACTIONS = {"delete_campaign", "delete_lead", "delete_blocklist_entry"}
ALL_ACTIONS = READ_ACTIONS | WRITE_ACTIONS
SENSITIVE_ACCOUNT_KEYS = ("password", "secret", "token", "credential", "private_key", "api_key")
NON_SECRET_COMMAND_KEYS = {"approval_token"}


def _text(value: object) -> str:
    return str(value or "").strip()


def _env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name.lower()}_required")
    return value


def _id(value: object, name: str) -> str:
    text = _text(value)
    if not text:
        raise ValueError(f"{name}_required")
    return quote(text, safe="")


def _limit(args: dict, default: int = 50) -> int:
    return min(max(int(args.get("limit", default)), 1), 100)


def _payload(args: dict) -> dict:
    value = args.get("payload", {})
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("payload_must_be_object")
    return dict(value)


def _contains_sensitive_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key or "").casefold()
            if normalized not in NON_SECRET_COMMAND_KEYS and any(
                marker in normalized for marker in SENSITIVE_ACCOUNT_KEYS
            ):
                return True
            if _contains_sensitive_key(nested):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def load_config(path: str | Path) -> dict:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if config.get("schema_version") != "leadscanner-instantly-control/1.0":
        raise ValueError("instantly_control_config_version_mismatch")
    return config


def load_command(path: str | Path) -> dict:
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("command_schema_version_mismatch")
    command_id = _text(raw.get("command_id")).casefold()
    if not COMMAND_ID_RE.fullmatch(command_id):
        raise ValueError("invalid_command_id")
    if p.stem.casefold() != command_id:
        raise ValueError("command_id_must_match_filename")
    action = _text(raw.get("action")).casefold()
    if action not in ALL_ACTIONS:
        raise ValueError("unsupported_instantly_action")
    args = raw["args"] if "args" in raw else {}
    if not isinstance(args, dict):
        raise ValueError("command_args_must_be_object")
    if "payload" in args and args.get("payload") is not None and not isinstance(args.get("payload"), dict):
        raise ValueError("payload_must_be_object")
    if _contains_sensitive_key(args):
        raise ValueError("command_secret_material_forbidden")
    return {
        "schema_version": SCHEMA_VERSION,
        "command_id": command_id,
        "action": action,
        "args": args,
        "confirm": _text(raw.get("confirm")),
        "requested_by": _text(raw.get("requested_by")) or "chatgpt",
    }


def _confirmation_target(action: str, args: dict) -> str:
    direct = {
        "update_campaign": "campaign_id", "pause_campaign": "campaign_id",
        "activate_campaign": "campaign_id", "delete_campaign": "campaign_id",
        "update_lead": "lead_id", "delete_lead": "lead_id", "mark_thread_read": "thread_id",
        "update_account": "email", "pause_account": "email", "resume_account": "email",
        "block_email": "email", "block_domain": "domain", "delete_blocklist_entry": "entry_id",
        "stage_approved_lead": "campaign_id",
    }
    payload = args.get("payload") or {}
    if action == "create_campaign_draft":
        return _text(payload.get("name"))
    if action == "stage_approved_lead":
        return "|".join(
            part for part in (
                _text(args.get("preview_run_id")),
                _text(args.get("approval_token")).casefold(),
                _text(args.get("campaign_id")),
            ) if part
        )
    if action == "reply_email":
        return "|".join(
            part for part in (
                _text(payload.get("reply_to_uuid")),
                _text(payload.get("eaccount")),
            ) if part
        )
    if action == "forward_email":
        return "|".join(
            part for part in (
                _text(payload.get("reply_to_uuid")),
                _text(payload.get("to_address_email_list")),
                _text(payload.get("eaccount")),
            ) if part
        )
    if action == "send_test_email":
        return "|".join(
            part for part in (
                _text(payload.get("eaccount")),
                _text(payload.get("to_address_email_list")),
            ) if part
        )
    if action in {"enable_warmup", "disable_warmup"}:
        return ",".join(sorted({_text(email).casefold() for email in (args.get("emails") or []) if _text(email)}))
    if action == "update_interest":
        email = _text(payload.get("lead_email")).casefold()
        value = payload.get("interest_value") if "interest_value" in payload else ""
        value_text = "null" if value is None and "interest_value" in payload else _text(value)
        return "|".join(part for part in (email, value_text) if part)
    return _text(args.get(direct.get(action, ""))) if action in direct else ""


def expected_confirmation(action: str, args: dict) -> str:
    target = _confirmation_target(action, args)
    return f"EXECUTE {action}" + (f" {target}" if target else "")



def validate_write_gate(command: dict, config: dict, *, run_attempt: str) -> None:
    action = command["action"]
    if action not in WRITE_ACTIONS:
        return
    if str(run_attempt or "1") != "1":
        raise RuntimeError("write_commands_cannot_run_on_workflow_rerun")
    if config.get("write_actions_enabled") is not True:
        raise RuntimeError("instantly_write_actions_disabled")
    if action in SEND_ACTIONS and config.get("send_actions_enabled") is not True:
        raise RuntimeError("instantly_send_actions_disabled")
    if action in DESTRUCTIVE_ACTIONS and config.get("destructive_actions_enabled") is not True:
        raise RuntimeError("instantly_destructive_actions_disabled")
    if config.get("require_exact_confirmation") is not True:
        raise RuntimeError("exact_confirmation_gate_must_remain_enabled")
    expected = expected_confirmation(action, command["args"])
    if command.get("confirm") != expected:
        raise ValueError(f"exact_confirmation_required:{expected}")


def _api(
    client: InstantlyClient,
    method: str,
    path: str,
    *,
    params=None,
    payload=None,
    retry_safe: bool | None = None,
):
    safe = method.upper() == "GET" if retry_safe is None else bool(retry_safe)
    return client._request(method, path, params=params, json=payload, retry_safe=safe)


def _redact_sensitive(value):
    if isinstance(value, dict):
        redacted = {}
        for key, nested in value.items():
            normalized = str(key or "").casefold()
            if any(marker in normalized for marker in SENSITIVE_ACCOUNT_KEYS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_sensitive(nested)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_sensitive(item) for item in value]
    return value


def _wait_background_job(
    client: InstantlyClient,
    operation: dict,
    *,
    max_polls: int = 15,
    sleep_fn=time.sleep,
) -> dict:
    job_id = _text((operation or {}).get("id") or (operation or {}).get("job_id"))
    if not job_id:
        raise RuntimeError("instantly_background_job_missing_id")
    last = {}
    for index in range(max(int(max_polls), 1)):
        last = _api(client, "GET", f"/background-jobs/{_id(job_id, 'job_id')}") or {}
        status = _text(last.get("status")).casefold()
        if status in {"completed", "success"}:
            return {"state": "completed", "job": last}
        if status in {"failed", "error"}:
            raise RuntimeError(f"instantly_background_job_failed:{status}")
        if index + 1 < max_polls:
            sleep_fn(1.0)
    return {"state": "pending", "job": last}


def _wait_interest_status(
    client: InstantlyClient,
    *,
    lead_email: str,
    interest_value,
    campaign_id: str = "",
    list_id: str = "",
    max_polls: int = 10,
    sleep_fn=time.sleep,
) -> dict:
    email = _text(lead_email).casefold()
    last: list[dict] = []
    for index in range(max(int(max_polls), 1)):
        page = client.list_leads(
            campaign=_text(campaign_id) or None,
            list_id=_text(list_id) or None,
            contacts=[email],
            limit=100,
        ) or {}
        rows = [
            row for row in (page.get("items") or [])
            if isinstance(row, dict) and _text(row.get("email")).casefold() == email
        ]
        last = rows
        if rows and all(
            not isinstance(row.get("lt_interest_status"), bool)
            and row.get("lt_interest_status") == interest_value
            for row in rows
        ):
            return {"state": "completed", "leads": rows}
        if index + 1 < max_polls:
            sleep_fn(1.0)
    return {"state": "pending", "leads": last}


def _campaign_leads(client: InstantlyClient, campaign_id: str, max_leads: int = 2000) -> list[dict]:
    rows, cursor = [], None
    seen_cursors: set[str] = set()
    while len(rows) < max_leads:
        page = client.list_leads(campaign=campaign_id, limit=100, starting_after=cursor) or {}
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
    if len(rows) >= max_leads and cursor:
        raise RuntimeError("activation_preflight_lead_scan_limit_reached")
    return rows


def _activate(client: InstantlyClient, campaign_id: str) -> dict:
    campaign = client.get_campaign(campaign_id) or {}
    if int(campaign.get("status")) not in SAFE_CAMPAIGN_STATUSES:
        raise ValueError("campaign_must_be_draft_or_paused_before_activation")
    if campaign.get("allow_risky_contacts") is True:
        raise ValueError("activation_blocks_allow_risky_contacts_true")
    try:
        sending_status = _api(
            client,
            "GET",
            f"/campaigns/{_id(campaign_id, 'campaign_id')}/sending-status",
            params={"with_ai_summary": False},
        ) or {}
    except InstantlyError as exc:
        if "status=400" not in str(exc):
            raise
        sending_status = {
            "state": "unavailable_before_activation",
            "http_status": 400,
        }
    senders = [str(x).strip().casefold() for x in (campaign.get("email_list") or []) if str(x).strip()]
    if not senders:
        raise ValueError("activation_requires_sender_accounts")
    for email in senders:
        account = _api(client, "GET", f"/accounts/{quote(email, safe='')}") or {}
        account_status = account.get("status")
        if type(account_status) is not int or account_status != 1:
            raise ValueError("activation_requires_all_sender_accounts_active")
    leads = _campaign_leads(client, campaign_id)
    if not leads:
        raise ValueError("activation_requires_leads")
    if any(
        type(lead.get("verification_status")) is not int
        or lead.get("verification_status") != 1
        for lead in leads
    ):
        raise ValueError("activation_requires_verified_leads_only")
    diagnostics = sending_status.get("diagnostics") or {}
    summary = sending_status.get("summary") or {}
    reason = _text(diagnostics.get("status") or summary.get("status")).casefold()
    if reason == "all_accounts_unhealthy":
        raise ValueError("activation_sending_status_all_accounts_unhealthy")
    operation = _api(client, "POST", f"/campaigns/{_id(campaign_id, 'campaign_id')}/activate", payload={})
    observed = client.get_campaign(campaign_id) or {}
    if int(observed.get("status")) not in {1, 4}:
        raise RuntimeError("campaign_activation_readback_not_active")
    return {"operation": operation, "readback": observed, "preflight_lead_count": len(leads), "preflight_sending_status": sending_status}


def execute_command(command: dict, config: dict, client: InstantlyClient, *, run_attempt: str = "1") -> dict:
    validate_write_gate(command, config, run_attempt=run_attempt)
    action, args = command["action"], command["args"]

    if action == "list_campaigns":
        page = client.list_campaigns(
            limit=_limit(args),
            starting_after=_text(args.get("starting_after")) or None,
            status=args.get("status"),
        ) or {}
        data = {
            "items": [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "status": item.get("status"),
                    "timestamp_created": item.get("timestamp_created"),
                    "timestamp_updated": item.get("timestamp_updated"),
                }
                for item in (page.get("items") or [])
                if isinstance(item, dict)
            ],
            "next_starting_after": page.get("next_starting_after"),
        }
    elif action == "get_campaign":
        data = client.get_campaign(_text(args.get("campaign_id")))
    elif action == "campaign_sending_status":
        data = _api(client, "GET", f"/campaigns/{_id(args.get('campaign_id'), 'campaign_id')}/sending-status", params={"with_ai_summary": bool(args.get("with_ai_summary", False))})
    elif action == "campaign_analytics":
        data = client.get_campaign_analytics(campaign_id=_text(args.get("campaign_id")) or None)
    elif action == "list_leads":
        data = client.list_leads(campaign=_text(args.get("campaign_id")) or None, limit=_limit(args), starting_after=_text(args.get("starting_after")) or None)
    elif action == "get_lead":
        data = client.get_lead(_text(args.get("lead_id")))
    elif action == "list_emails":
        data = client.get_emails(campaign_id=_text(args.get("campaign_id")) or None, received_only=bool(args.get("received_only", True)), limit=_limit(args), starting_after=_text(args.get("starting_after")) or None)
    elif action == "get_email":
        data = _api(client, "GET", f"/emails/{_id(args.get('email_id'), 'email_id')}")
    elif action == "count_unread_emails":
        data = _api(client, "GET", "/emails/unread/count")
    elif action == "list_accounts":
        data = _api(client, "GET", "/accounts", params={"limit": _limit(args), **({"starting_after": args["starting_after"]} if args.get("starting_after") else {})})
    elif action == "get_account":
        data = _api(client, "GET", f"/accounts/{_id(args.get('email'), 'email')}")
    elif action == "test_account_vitals":
        raw_accounts = args.get("accounts")
        if not isinstance(raw_accounts, list):
            raise ValueError("accounts_must_be_list")
        accounts = sorted({_text(email).casefold() for email in raw_accounts if _text(email)})
        if not accounts:
            raise ValueError("accounts_required")
        data = _api(
            client,
            "POST",
            "/accounts/test/vitals",
            payload={"accounts": accounts},
            retry_safe=True,
        )
    elif action == "warmup_analytics":
        data = _api(client, "POST", "/accounts/warmup-analytics", payload={"emails": list(args.get("emails") or [])}, retry_safe=True)
    elif action == "daily_account_analytics":
        data = _api(client, "GET", "/accounts/analytics/daily", params={k: v for k, v in {"emails": args.get("emails"), "start_date": args.get("start_date"), "end_date": args.get("end_date")}.items() if v})
    elif action == "list_blocklist":
        data = _api(client, "GET", "/block-lists-entries", params={"limit": _limit(args), **({"starting_after": args["starting_after"]} if args.get("starting_after") else {})})
    elif action == "get_blocklist_entry":
        data = _api(client, "GET", f"/block-lists-entries/{_id(args.get('entry_id'), 'entry_id')}")
    elif action == "get_background_job":
        data = _api(client, "GET", f"/background-jobs/{_id(args.get('job_id'), 'job_id')}")
    elif action == "create_campaign_draft":
        payload = _payload(args)
        if not _text(payload.get("name")) or not isinstance(payload.get("campaign_schedule"), dict):
            raise ValueError("campaign_name_and_schedule_required")
        payload.setdefault("allow_risky_contacts", False)
        created = _api(client, "POST", "/campaigns", payload=payload) or {}
        observed = client.get_campaign(_text(created.get("id"))) or {}
        if int(observed.get("status")) != 0:
            raise RuntimeError("new_campaign_must_read_back_as_draft")
        data = {"operation": created, "readback": observed}
    elif action == "update_campaign":
        cid = _text(args.get("campaign_id"))
        current = client.get_campaign(cid) or {}
        if int(current.get("status")) not in SAFE_CAMPAIGN_STATUSES:
            raise ValueError("campaign_must_be_draft_or_paused_before_update")
        operation = _api(
            client,
            "PATCH",
            f"/campaigns/{_id(cid, 'campaign_id')}",
            payload=_payload(args),
        )
        data = {"operation": operation, "readback": client.get_campaign(cid)}
    elif action == "pause_campaign":
        cid = _text(args.get("campaign_id"))
        operation = _api(client, "POST", f"/campaigns/{_id(cid, 'campaign_id')}/pause", payload={})
        observed = client.get_campaign(cid) or {}
        if int(observed.get("status")) != 2:
            raise RuntimeError("campaign_pause_readback_not_paused")
        data = {"operation": operation, "readback": observed}
    elif action == "activate_campaign":
        data = _activate(client, _text(args.get("campaign_id")))
    elif action == "delete_campaign":
        data = _api(client, "DELETE", f"/campaigns/{_id(args.get('campaign_id'), 'campaign_id')}")
    elif action == "update_lead":
        lid = _text(args.get("lead_id"))
        data = {"operation": _api(client, "PATCH", f"/leads/{_id(lid, 'lead_id')}", payload=_payload(args)), "readback": client.get_lead(lid)}
    elif action == "delete_lead":
        data = _api(client, "DELETE", f"/leads/{_id(args.get('lead_id'), 'lead_id')}")
    elif action == "update_interest":
        payload = _payload(args)
        email = _text(payload.get("lead_email")).casefold()
        if not email or email.count("@") != 1:
            raise ValueError("interest_lead_email_required")
        if "interest_value" not in payload:
            raise ValueError("interest_value_required")
        interest_value = payload.get("interest_value")
        if interest_value is not None and (
            isinstance(interest_value, bool) or not isinstance(interest_value, (int, float))
        ):
            raise ValueError("interest_value_must_be_number_or_null")
        operation = _api(client, "POST", "/leads/update-interest-status", payload=payload)
        observed = _wait_interest_status(
            client,
            lead_email=email,
            interest_value=interest_value,
            campaign_id=_text(payload.get("campaign_id")),
            list_id=_text(payload.get("list_id")),
        )
        data = {
            "operation": operation,
            "completion_state": observed["state"],
            "readback": observed["leads"],
        }
    elif action in {"reply_email", "forward_email", "send_test_email"}:
        payload = _payload(args)
        if not _text(payload.get("eaccount")):
            raise ValueError("sending_account_required")
        if not _text(payload.get("subject")):
            raise ValueError("email_subject_required")
        if action in {"reply_email", "forward_email"} and not _text(payload.get("reply_to_uuid")):
            raise ValueError("reply_to_uuid_required")
        if action == "reply_email" and not isinstance(payload.get("body"), dict):
            raise ValueError("reply_body_required")
        if action == "forward_email":
            if not _text(payload.get("to_address_email_list")):
                raise ValueError("forward_recipient_required")
            if not isinstance(payload.get("body"), dict) and payload.get("include_original_body") is not True:
                raise ValueError("forward_body_or_original_required")
        if action == "send_test_email":
            if not _text(payload.get("to_address_email_list")):
                raise ValueError("test_recipient_required")
            if not isinstance(payload.get("body"), dict):
                raise ValueError("test_body_required")
        path = {"reply_email": "/emails/reply", "forward_email": "/emails/forward", "send_test_email": "/emails/test"}[action]
        data = _api(client, "POST", path, payload=payload)
        if action == "send_test_email" and isinstance(data, dict) and data.get("error"):
            code = re.sub(r"[^A-Za-z0-9_.:-]+", "_", _text(data.get("error")))[:80] or "unknown"
            raise RuntimeError(f"instantly_test_send_error:{code}")
    elif action == "mark_thread_read":
        data = _api(client, "POST", f"/emails/threads/{_id(args.get('thread_id'), 'thread_id')}/mark-as-read", payload={})
    elif action == "update_account":
        payload = _payload(args)
        if _contains_sensitive_key(payload):
            raise ValueError("account_secret_material_must_not_be_committed_to_command_file")
        email = _text(args.get("email"))
        data = {"operation": _api(client, "PATCH", f"/accounts/{_id(email, 'email')}", payload=payload), "readback": _api(client, "GET", f"/accounts/{_id(email, 'email')}")}
    elif action in {"pause_account", "resume_account"}:
        email = _text(args.get("email"))
        verb = "pause" if action == "pause_account" else "resume"
        operation = _api(client, "POST", f"/accounts/{_id(email, 'email')}/{verb}", payload={})
        readback = _api(client, "GET", f"/accounts/{_id(email, 'email')}") or {}
        expected_status = 2 if action == "pause_account" else 1
        if int(readback.get("status") or 0) != expected_status:
            raise RuntimeError(f"account_{verb}_readback_mismatch")
        data = {"operation": operation, "readback": readback}
    elif action in {"enable_warmup", "disable_warmup"}:
        verb = "enable" if action == "enable_warmup" else "disable"
        raw_emails = args.get("emails")
        if not isinstance(raw_emails, list):
            raise ValueError("emails_must_be_list")
        emails = sorted({_text(email).casefold() for email in raw_emails if _text(email)})
        if not emails:
            raise ValueError("warmup_accounts_required")
        operation = _api(client, "POST", f"/accounts/warmup/{verb}", payload={"emails": emails})
        job_result = _wait_background_job(client, operation or {})
        readback = []
        if job_result["state"] == "completed":
            expected_warmup = 1 if action == "enable_warmup" else 0
            for email in emails:
                observed = _api(client, "GET", f"/accounts/{_id(email, 'email')}") or {}
                if int(observed.get("warmup_status")) != expected_warmup:
                    raise RuntimeError(f"warmup_{verb}_readback_mismatch")
                readback.append(observed)
        data = {
            "operation": operation,
            "background_job": job_result["job"],
            "completion_state": job_result["state"],
            "readback": readback,
        }
    elif action == "block_email":
        data = client.block_email(_text(args.get("email")))
    elif action == "block_domain":
        data = client.block_domain(_text(args.get("domain")))
    elif action == "delete_blocklist_entry":
        data = _api(client, "DELETE", f"/block-lists-entries/{_id(args.get('entry_id'), 'entry_id')}")
    elif action == "stage_approved_lead":
        data = stage_exact_approved_lead(
            preview_run_id=int(args.get("preview_run_id")),
            approval_token=_text(args.get("approval_token")),
            campaign_id=_text(args.get("campaign_id")),
            instantly_api_key=_env("INSTANTLY_API_KEY"),
            github_token=_env("LEADSCANNER_GITHUB_TOKEN"),
            repository=os.getenv("GITHUB_REPOSITORY", DEFAULT_REPOSITORY).strip() or DEFAULT_REPOSITORY,
            registry_url=os.getenv("DEDUPE_REGISTRY_CSV_URL", DEFAULT_REGISTRY_URL).strip() or DEFAULT_REGISTRY_URL,
            instantly_client=client,
        )
    else:
        raise ValueError("unsupported_instantly_action")

    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": "green",
        "command_id": command["command_id"],
        "action": action,
        "mode": "write" if action in WRITE_ACTIONS else "read",
        "send_action": action in SEND_ACTIONS,
        "destructive_action": action in DESTRUCTIVE_ACTIONS,
        "result": data,
    }


def command_paths_from_lines(lines) -> list[Path]:
    paths = []
    for raw in lines:
        path = str(raw or "").strip()
        if path.startswith(COMMAND_PREFIX) and path.endswith(".json"):
            paths.append(path)
    return [Path(path) for path in dict.fromkeys(paths)]


def command_paths_from_push_event(event: dict) -> list[Path]:
    paths = []
    for commit in event.get("commits") or []:
        paths.extend(commit.get("added") or [])
    paths.extend((event.get("head_commit") or {}).get("added") or [])
    return command_paths_from_lines(paths)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_redact_sensitive(payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_paths(paths: list[Path], output_dir: str | Path, config_path: str | Path) -> int:
    config = load_config(config_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    if not paths:
        _write(out / "summary.json", {"schema_version": RESULT_SCHEMA_VERSION, "status": "green", "command_count": 0})
        return 0
    client = InstantlyClient(_env("INSTANTLY_API_KEY"))
    failures, summaries = 0, []
    for path in paths:
        try:
            command = load_command(path)
            result = execute_command(command, config, client, run_attempt=os.getenv("GITHUB_RUN_ATTEMPT", "1"))
        except Exception as exc:
            failures += 1
            result = {"schema_version": RESULT_SCHEMA_VERSION, "status": "red", "command_file": str(path), "error": str(exc)}
        _write(out / f"{path.stem.casefold()}.json", result)
        summaries.append({"command_id": path.stem.casefold(), "status": result.get("status"), "action": result.get("action"), "error": result.get("error")})
    _write(out / "summary.json", {"schema_version": RESULT_SCHEMA_VERSION, "status": "green" if not failures else "red", "command_count": len(paths), "failure_count": failures, "commands": summaries})
    return 1 if failures else 0


def run_event(event_path: str | Path, output_dir: str | Path, config_path: str | Path) -> int:
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    return run_paths(command_paths_from_push_event(event), output_dir, config_path)


def run_paths_file(paths_file: str | Path, output_dir: str | Path, config_path: str | Path) -> int:
    paths = command_paths_from_lines(Path(paths_file).read_text(encoding="utf-8").splitlines())
    return run_paths(paths, output_dir, config_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run-event")
    run.add_argument("--event", required=True)
    run.add_argument("--output-dir", required=True)
    run.add_argument("--config", default="config/instantly-control.json")
    paths = sub.add_parser("run-paths")
    paths.add_argument("--paths-file", required=True)
    paths.add_argument("--output-dir", required=True)
    paths.add_argument("--config", default="config/instantly-control.json")
    one = sub.add_parser("run-command")
    one.add_argument("--command", required=True)
    one.add_argument("--output", required=True)
    one.add_argument("--config", default="config/instantly-control.json")
    args = parser.parse_args()
    if args.cmd == "run-event":
        return run_event(args.event, args.output_dir, args.config)
    if args.cmd == "run-paths":
        return run_paths_file(args.paths_file, args.output_dir, args.config)
    result = execute_command(
        load_command(args.command),
        load_config(args.config),
        InstantlyClient(_env("INSTANTLY_API_KEY")),
        run_attempt=os.getenv("GITHUB_RUN_ATTEMPT", "1"),
    )
    _write(Path(args.output), result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
