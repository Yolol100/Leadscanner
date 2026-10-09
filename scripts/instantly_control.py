#!/usr/bin/env python3
"""GitHub command control plane for ChatGPT web -> Leadscanner -> Instantly.

Commands are immutable JSON files added under ``instantly-commands/inbox``.
Only named, allowlisted Instantly API v2 actions exist here; there is no generic
method/path command.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

from instantly_client import InstantlyClient, InstantlyError, SAFE_CAMPAIGN_STATUSES, inspect_campaign_sequence
from instantly_service import DEFAULT_REGISTRY_URL, DEFAULT_REPOSITORY, fetch_live_registry, stage_exact_approved_lead
from myhost_instantly_import import execute_migration
from instantly_language_campaigns import audit_language_split
from instantly_language_route import route_exact_language

SCHEMA_VERSION = "leadscanner-instantly-command/1.0"
RESULT_SCHEMA_VERSION = "leadscanner-instantly-command-result/1.0"
COMMAND_PREFIX = "instantly-commands/inbox/"
COMMAND_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{5,120}$")

READ_ACTIONS = {
    "audit_myhost_drafts", "audit_language_split", "audit_campaign_schedule", "list_campaigns", "get_campaign", "audit_campaign_sequence", "audit_activation_readiness", "campaign_sending_status", "campaign_analytics",
    "list_leads", "get_lead", "list_emails", "get_email", "count_unread_emails",
    "list_accounts", "get_account", "test_account_vitals", "warmup_analytics", "daily_account_analytics",
    "list_blocklist", "get_blocklist_entry", "get_background_job",
}
WRITE_ACTIONS = {
    "create_campaign_draft", "update_campaign", "pause_campaign", "activate_campaign",
    "delete_campaign", "update_lead", "delete_lead", "update_interest", "reply_email",
    "forward_email", "send_test_email", "mark_thread_read", "update_account",
    "mark_account_fixed", "pause_account", "resume_account", "enable_warmup", "disable_warmup",
    "verify_email",
    "block_email", "block_domain", "delete_blocklist_entry", "stage_approved_lead", "import_myhost_drafts", "route_language_drafts",
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


def _import_limit(args: dict) -> int:
    value = args.get("max_imports", 25)
    if type(value) is not int or not 1 <= value <= 250:
        raise ValueError("max_imports_out_of_bounds")
    return value


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
        "update_account": "email", "mark_account_fixed": "email", "pause_account": "email", "resume_account": "email",
        "verify_email": "email",
        "block_email": "email", "block_domain": "domain", "delete_blocklist_entry": "entry_id",
        "stage_approved_lead": "campaign_id",
    }
    payload = args.get("payload") or {}
    if action == "route_language_drafts":
        return "|".join((_text(args.get("language")), _text(args.get("campaign_id")), str(args.get("max_leads"))))
    if action == "import_myhost_drafts":
        return f"isolated-list-no-send:{_import_limit(args)}"
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


def _verify_email(
    client: InstantlyClient,
    email: str,
    *,
    max_polls: int = 12,
    sleep_fn=time.sleep,
) -> dict:
    address = _text(email).casefold()
    if "@" not in address:
        raise ValueError("valid_email_required")
    observed = _api(
        client,
        "POST",
        "/email-verification",
        payload={"email": address},
    ) or {}
    for index in range(max(int(max_polls), 1) + 1):
        status = _text(observed.get("verification_status")).casefold()
        catch_all = observed.get("catch_all")
        if status == "verified":
            if catch_all is True or catch_all == "pending":
                raise ValueError("email_verification_catch_all_blocked")
            return observed
        if status == "invalid":
            raise ValueError("email_verification_invalid")
        if status not in {"pending", ""}:
            raise RuntimeError("email_verification_unknown_status")
        if index >= max(int(max_polls), 1):
            break
        sleep_fn(1.0)
        observed = _api(
            client,
            "GET",
            f"/email-verification/{_id(address, 'email')}",
        ) or {}
    raise RuntimeError("email_verification_pending")


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


def _sequence_copy_signature(sequences: object) -> tuple:
    """Compare actual subject/body variants without relying on provider IDs."""
    if not isinstance(sequences, list):
        raise ValueError("campaign_sequence_readback_invalid")
    result = []
    for sequence in sequences:
        if not isinstance(sequence, dict) or not isinstance(sequence.get("steps"), list):
            raise ValueError("campaign_sequence_readback_invalid")
        steps = []
        for step in sequence["steps"]:
            if not isinstance(step, dict):
                raise ValueError("campaign_sequence_readback_invalid")
            if step.get("type") != "email":
                steps.append((_text(step.get("type")), tuple()))
                continue
            variants = step.get("variants")
            if not isinstance(variants, list):
                raise ValueError("campaign_sequence_readback_invalid")
            copies = []
            for variant in variants:
                if not isinstance(variant, dict):
                    raise ValueError("campaign_sequence_readback_invalid")
                copies.append((_text(variant.get("subject")), _text(variant.get("body"))))
            steps.append((_text(step.get("type")), tuple(copies)))
        result.append(tuple(steps))
    return tuple(result)


def _activation_leadset_fingerprint(leads: list[dict]) -> str:
    """Bind activation to the exact Instantly lead identities and payloads."""
    normalized = []
    seen_ids, seen_emails = set(), set()
    for lead in leads:
        if not isinstance(lead, dict):
            raise ValueError("activation_leadset_invalid")
        lead_id = _text(lead.get("id"))
        email = _text(lead.get("email")).casefold()
        if not lead_id or email.count("@") != 1 or lead_id in seen_ids or email in seen_emails:
            raise ValueError("activation_leadset_duplicate_or_invalid_identity")
        seen_ids.add(lead_id)
        seen_emails.add(email)
        variables = lead.get("payload")
        if not isinstance(variables, dict):
            variables = lead.get("custom_variables")
        if variables is None:
            variables = {}
        if not isinstance(variables, dict):
            raise ValueError("activation_leadset_payload_invalid")
        normalized.append({
            "id": lead_id, "email": email,
            "campaign": _text(lead.get("campaign") or lead.get("campaign_id")),
            "payload": variables,
            "status": lead.get("status"),
            "verification_status": lead.get("verification_status"),
            "interest_status": lead.get("lt_interest_status"),
        })
    normalized.sort(key=lambda row: (row["email"], row["id"]))
    try:
        raw = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("activation_leadset_payload_invalid") from exc
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _require_leadscanner_activation_approval(
    campaign: dict, leads: list[dict], approval: str,
) -> bool:
    """Do not turn reviewed Leadscanner facts into sends without a fresh gate."""
    sequences = campaign.get("sequences")
    report = inspect_campaign_sequence(campaign) if sequences else None
    linked_template = bool(report and report["leadscanner_variables"])
    linked_leads = any(
        isinstance(lead.get("payload"), dict)
        and lead["payload"].get("leadscanner_lead_id")
        or isinstance(lead.get("custom_variables"), dict)
        and lead["custom_variables"].get("leadscanner_lead_id")
        for lead in leads
    )
    if not linked_template and not linked_leads:
        if approval:
            raise ValueError("activation_approval_not_applicable")
        return False
    if not report or report["decision"] not in {
        "reviewed_mail_copy_still_required", "evidence_only_template_candidate",
    } or report["unresolved_template_variables"] or report["unsupported_leadscanner_variables"]:
        raise ValueError("activation_requires_reviewed_leadscanner_sequence")
    if report["decision"] == "evidence_only_template_candidate" and (
        report["sequence_count"] != 1
        or report["email_step_count"] != 3
        or not {"leadscanner_observation", "leadscanner_value_action"} <= set(report["leadscanner_variables"])
    ):
        raise ValueError("activation_requires_approved_three_step_evidence_sequence")
    expected = (
        "APPROVE_INSTANTLY_ACTIVATION "
        + report["campaign_id"] + " " + report["sequence_fingerprint"]
        + " " + _activation_leadset_fingerprint(leads)
    )
    if approval != expected:
        raise ValueError("activation_sequence_approval_required_or_stale")
    for lead in leads:
        variables = lead.get("payload")
        if not isinstance(variables, dict):
            variables = lead.get("custom_variables")
        if not isinstance(variables, dict) or not variables.get("leadscanner_lead_id"):
            raise ValueError("activation_requires_leadscanner_origin_for_all_leads")
        basis = variables.get("leadscanner_contact_basis")
        reference = variables.get("leadscanner_contact_basis_ref")
        if basis not in {"consent_verified", "existing_customer_related_verified"} or (
            not isinstance(reference, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._/-]{7,160}", reference)
        ):
            raise ValueError("activation_requires_documented_contact_permission")
    return True


def _require_registry_staged_for_activation(leads: list[dict], registry_rows: list[dict]) -> None:
    """Reject missing, ambiguous or suppressed canonical lead identities."""
    for lead in leads:
        email = _text(lead.get("email")).casefold()
        variables = lead.get("payload")
        if not isinstance(variables, dict):
            variables = lead.get("custom_variables")
        lead_id = _text((variables or {}).get("leadscanner_lead_id"))
        matching = [
            item for item in registry_rows
            if email in (item.get("identity") or {}).get("emails", set())
        ]
        if len(matching) != 1:
            raise ValueError("activation_registry_identity_missing_or_ambiguous")
        entry = matching[0]
        if (
            _text(entry.get("status")).casefold() != "instantly_staged"
            or lead_id not in (entry.get("identity") or {}).get("lead_ids", set())
        ):
            raise ValueError("activation_registry_suppression_or_identity_mismatch")


def _activate(
    client: InstantlyClient, campaign_id: str, *, activation_approval: str = "",
) -> dict:
    campaign = client.get_campaign(campaign_id)
    if not isinstance(campaign, dict) or _text(campaign.get("id")) != campaign_id:
        raise RuntimeError("campaign_readback_id_mismatch")
    campaign_status = campaign.get("status")
    if type(campaign_status) is not int or campaign_status not in SAFE_CAMPAIGN_STATUSES:
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
    for lead in leads:
        lead_status = lead.get("status")
        interest_status = lead.get("lt_interest_status")
        if (
            lead_status is not None and type(lead_status) is not int
            or interest_status is not None and type(interest_status) is not int
        ):
            raise ValueError("activation_lead_status_invalid")
        if lead_status in {-1, -2, -3} or interest_status in {-1, -2, -3, -4}:
            raise ValueError("activation_blocks_suppressed_lead_status")
        verification_status = lead.get("verification_status")
        if type(verification_status) is int and verification_status == 1:
            continue
        if verification_status is not None:
            raise ValueError("activation_requires_verified_leads_only")
        email = _text(lead.get("email")).casefold()
        if not email:
            raise ValueError("activation_requires_verified_leads_only")
        direct = _api(
            client,
            "GET",
            f"/email-verification/{_id(email, 'email')}",
        ) or {}
        if (
            _text(direct.get("verification_status")).casefold() != "verified"
            or direct.get("catch_all") is True
            or direct.get("catch_all") == "pending"
        ):
            raise ValueError("activation_requires_verified_leads_only")
    diagnostics = sending_status.get("diagnostics") or {}
    summary = sending_status.get("summary") or {}
    reason = _text(diagnostics.get("status") or summary.get("status")).casefold()
    if reason == "all_accounts_unhealthy":
        raise ValueError("activation_sending_status_all_accounts_unhealthy")
    leadscanner_campaign = _require_leadscanner_activation_approval(campaign, leads, activation_approval)
    if leadscanner_campaign:
        registry_url = os.getenv("DEDUPE_REGISTRY_CSV_URL", DEFAULT_REGISTRY_URL).strip() or DEFAULT_REGISTRY_URL
        _require_registry_staged_for_activation(
            leads, fetch_live_registry(registry_url=registry_url),
        )
    # A campaign can be edited while sender/lead preflight is running.
    current = client.get_campaign(campaign_id)
    if not isinstance(current, dict) or _text(current.get("id")) != campaign_id:
        raise RuntimeError("campaign_readback_id_mismatch")
    current_status = current.get("status")
    if type(current_status) is not int or current_status not in SAFE_CAMPAIGN_STATUSES:
        raise ValueError("campaign_changed_during_activation_preflight")
    if (
        current.get("email_list") != campaign.get("email_list")
        or current.get("allow_risky_contacts") != campaign.get("allow_risky_contacts")
        or current.get("sequences") != campaign.get("sequences")
    ):
        raise ValueError("campaign_changed_during_activation_preflight")
    if leadscanner_campaign:
        current_leads = _campaign_leads(client, campaign_id)
        if _activation_leadset_fingerprint(current_leads) != _activation_leadset_fingerprint(leads):
            raise ValueError("activation_leadset_changed_during_preflight")
        _require_registry_staged_for_activation(
            current_leads, fetch_live_registry(registry_url=registry_url),
        )
    operation = _api(client, "POST", f"/campaigns/{_id(campaign_id, 'campaign_id')}/activate", payload={})
    observed = client.get_campaign(campaign_id) or {}
    if (
        _text(observed.get("id")) != campaign_id
        or type(observed.get("status")) is not int
        or observed.get("status") not in {1, 4}
    ):
        raise RuntimeError("campaign_activation_readback_not_active")
    return {"operation": operation, "readback": observed, "preflight_lead_count": len(leads), "preflight_sending_status": sending_status}


def execute_command(command: dict, config: dict, client: InstantlyClient, *, run_attempt: str = "1") -> dict:
    validate_write_gate(command, config, run_attempt=run_attempt)
    action, args = command["action"], command["args"]

    if action == "audit_language_split":
        data = audit_language_split(client)
    elif action == "route_language_drafts":
        data = route_exact_language(
            client, language=_text(args.get("language")), campaign_id=_text(args.get("campaign_id")),
            max_leads=args.get("max_leads", 25),
            registry_url=os.getenv("DEDUPE_REGISTRY_CSV_URL", DEFAULT_REGISTRY_URL),
        )
    elif action == "audit_myhost_drafts":
        data = execute_migration(client, mode="audit", registry_url=os.getenv("DEDUPE_REGISTRY_CSV_URL", DEFAULT_REGISTRY_URL))
    elif action == "import_myhost_drafts":
        data = execute_migration(client, mode="import", registry_url=os.getenv("DEDUPE_REGISTRY_CSV_URL", DEFAULT_REGISTRY_URL), max_imports=_import_limit(args))
    elif action == "list_campaigns":
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
    elif action == "audit_campaign_schedule":
        campaign_id = _text(args.get("campaign_id"))
        if not campaign_id:
            raise ValueError("campaign_id_required")
        campaign = client.get_campaign(campaign_id)
        if not isinstance(campaign, dict) or _text(campaign.get("id")) != campaign_id:
            raise RuntimeError("campaign_readback_id_mismatch")
        raw_schedule = campaign.get("campaign_schedule") or {}
        schedules = raw_schedule.get("schedules") or [] if isinstance(raw_schedule, dict) else []
        if not isinstance(schedules, list):
            raise RuntimeError("campaign_schedules_invalid")
        data = {
            "campaign_id": campaign_id,
            "status": campaign.get("status"),
            "schedule": [
                {
                    "timezone": row.get("timezone"),
                    "timing": row.get("timing"),
                    "days": row.get("days"),
                }
                for row in schedules if isinstance(row, dict)
            ],
            "sender_count": len(campaign.get("email_list") or []),
            "available_config_fields": sorted(
                key for key in ("daily_limit","daily_max_leads","email_gap","stop_on_reply",
                                "open_tracking","link_tracking","text_only","insert_unsubscribe_header")
                if key in campaign
            ),
            "sending_action": False,
            "contains_campaign_copy": False,
        }
    elif action == "audit_campaign_sequence":
        campaign_id = _text(args.get("campaign_id"))
        if not campaign_id:
            raise ValueError("campaign_id_required")
        campaign = client.get_campaign(campaign_id)
        if not isinstance(campaign, dict) or _text(campaign.get("id")) != campaign_id:
            raise RuntimeError("campaign_readback_id_mismatch")
        data = inspect_campaign_sequence(campaign)
    elif action == "audit_activation_readiness":
        cid = _text(args.get("campaign_id"))
        if not cid:
            raise ValueError("campaign_id_required")
        campaign = client.get_campaign(cid)
        if not isinstance(campaign, dict) or _text(campaign.get("id")) != cid:
            raise RuntimeError("campaign_readback_id_mismatch")
        report = inspect_campaign_sequence(campaign)
        leads = _campaign_leads(client, cid)
        fingerprint = _activation_leadset_fingerprint(leads)
        basis_ok = 0
        for lead in leads:
            variables = lead.get("payload")
            if not isinstance(variables, dict):
                variables = lead.get("custom_variables")
            if isinstance(variables, dict) and (
                variables.get("leadscanner_contact_basis")
                in {"consent_verified", "existing_customer_related_verified"}
                and isinstance(variables.get("leadscanner_contact_basis_ref"), str)
                and re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9:._/-]{7,160}",
                    variables["leadscanner_contact_basis_ref"],
                )
            ):
                basis_ok += 1
        data = {
            "schema_version": "leadscanner-activation-readiness-audit/1.0",
            "campaign_id": cid,
            "campaign_status": campaign.get("status"),
            "sequence_fingerprint": report["sequence_fingerprint"],
            "leadset_fingerprint": fingerprint,
            "lead_count": len(leads),
            "documented_contact_basis_count": basis_ok,
            "missing_contact_basis_count": len(leads) - basis_ok,
            "leadscanner_variables": report["leadscanner_variables"],
            "automatic_send": False,
            "review_required": True,
            "approval_format": (
                "APPROVE_INSTANTLY_ACTIVATION <campaign_id> <sequence_fingerprint> <leadset_fingerprint>"
            ),
        }
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
    elif action == "verify_email":
        data = _verify_email(client, _text(args.get("email")))
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
        if (
            _text(observed.get("id")) != _text(created.get("id"))
            or type(observed.get("status")) is not int
            or observed.get("status") != 0
        ):
            raise RuntimeError("new_campaign_must_read_back_as_draft")
        data = {"operation": created, "readback": observed}
    elif action == "update_campaign":
        cid = _text(args.get("campaign_id"))
        current = client.get_campaign(cid) or {}
        if _text(current.get("id")) != cid:
            raise RuntimeError("campaign_readback_id_mismatch")
        current_status = current.get("status")
        if type(current_status) is not int or current_status not in SAFE_CAMPAIGN_STATUSES:
            raise ValueError("campaign_must_be_draft_or_paused_before_update")
        payload = _payload(args)
        operation = _api(
            client,
            "PATCH",
            f"/campaigns/{_id(cid, 'campaign_id')}",
            payload=payload,
        )
        observed = client.get_campaign(cid)
        if not isinstance(observed, dict) or _text(observed.get("id")) != cid:
            raise RuntimeError("campaign_update_readback_id_mismatch")
        if "sequences" in payload and (
            _sequence_copy_signature(observed.get("sequences"))
            != _sequence_copy_signature(payload["sequences"])
        ):
            raise RuntimeError("campaign_update_sequence_readback_mismatch")
        if "email_list" in payload and (
            not isinstance(observed.get("email_list"), list)
            or sorted(observed["email_list"]) != sorted(payload["email_list"])
        ):
            raise RuntimeError("campaign_update_sender_readback_mismatch")
        for field in (
            "allow_risky_contacts", "stop_on_reply", "stop_on_auto_reply",
            "open_tracking", "link_tracking", "insert_unsubscribe_header",
        ):
            if field in payload and (
                type(payload[field]) is not bool
                or observed.get(field) is not payload[field]
            ):
                raise RuntimeError(f"campaign_update_safety_field_readback_mismatch:{field}")
        for field in ("daily_limit", "daily_max_leads", "email_gap"):
            if field in payload and (
                type(payload[field]) is not int
                or type(observed.get(field)) is not int
                or observed[field] != payload[field]
            ):
                raise RuntimeError(f"campaign_update_limit_readback_mismatch:{field}")
        data = {"operation": operation, "readback": observed}
    elif action == "pause_campaign":
        cid = _text(args.get("campaign_id"))
        operation = _api(client, "POST", f"/campaigns/{_id(cid, 'campaign_id')}/pause", payload={})
        observed = client.get_campaign(cid) or {}
        if int(observed.get("status")) != 2:
            raise RuntimeError("campaign_pause_readback_not_paused")
        data = {"operation": operation, "readback": observed}
    elif action == "activate_campaign":
        data = _activate(
            client, _text(args.get("campaign_id")),
            activation_approval=_text(args.get("activation_approval")),
        )
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
    elif action == "mark_account_fixed":
        email = _text(args.get("email"))
        operation = _api(client, "POST", f"/accounts/{_id(email, 'email')}/mark-fixed", payload={})
        readback = _api(client, "GET", f"/accounts/{_id(email, 'email')}") or {}
        if type(readback.get("status")) is not int or readback.get("status") != 1:
            raise RuntimeError("account_mark_fixed_readback_not_active")
        data = {"operation": operation, "readback": readback}
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
            sequence_approval=_text(args.get("sequence_approval")),
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
