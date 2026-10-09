"""Copy confirmed NL/EN mijn.host draft leads into non-sending Instantly campaigns.

Every mutation is an allowlisted GitHub command. Never send, activate, delete, or
change the source lead list. The campaign must be Draft with zero sender accounts.
Provider jobs are not retried if their outcome is uncertain.
"""
from __future__ import annotations

import re
import time
from collections import Counter

from instantly_language_campaigns import (
    LANGUAGE_CAMPAIGN_NAMES, classify_language, inspect_lead_language, read_imported_leads,
)
from instantly_client import InstantlyClient
from myhost_instantly_import import blocked_values, registry_allows_draft
from instantly_service import DEFAULT_REGISTRY_URL, fetch_live_registry

MAX_ROUTE_BATCH = 250
HOLD_FREE_MAIL = frozenset((
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com",
    "live.com", "yahoo.com", "icloud.com", "aol.com", "proton.me",
    "protonmail.com", "mail.com", "msn.com", "gmx.com"
))


def _text(value) -> str:
    return str(value or "").strip()


def _items(raw: object) -> tuple[list[dict], str]:
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise RuntimeError("routing_provider_page_invalid")
    items = raw["items"]
    if any(not isinstance(row, dict) for row in items):
        raise RuntimeError("routing_provider_row_invalid")
    return items, _text(raw.get("next_starting_after"))


def destination_emails(client: InstantlyClient, cid: str) -> set[str]:
    emails, seen, cursor = set(), set(), ""
    for _ in range(60):
        rows, next_cursor = _items(client.list_leads(campaign=cid, limit=100, starting_after=cursor or None))
        for item in rows:
            email = _text(item.get("email")).casefold()
            if not email or email in emails:
                raise RuntimeError("routing_destination_duplicate_or_missing_email")
            emails.add(email)
        if not next_cursor:
            return emails
        if not rows or cursor == next_cursor or next_cursor in seen:
            raise RuntimeError("routing_destination_pagination_invalid")
        seen.add(next_cursor)
        cursor = next_cursor
    raise RuntimeError("routing_destination_limit_exceeded")


def preflight_campaign(client: InstantlyClient, language: str, cid: str) -> None:
    campaign = client.get_campaign(cid)
    if not isinstance(campaign, dict) or _text(campaign.get("id")) != cid:
        raise RuntimeError("routing_campaign_identity_mismatch")
    if campaign.get("name") != LANGUAGE_CAMPAIGN_NAMES[language]:
        raise ValueError("routing_target_name_mismatch")
    if type(campaign.get("status")) is not int or campaign["status"] != 0:
        raise ValueError("routing_target_must_be_draft")
    if campaign.get("email_list") != []:
        raise ValueError("routing_campaign_must_have_no_senders")
    sequences = campaign.get("sequences")
    if not isinstance(sequences, list) or len(sequences) != 1:
        raise ValueError("routing_three_step_sequence_required")
    steps = sequences[0].get("steps") if isinstance(sequences[0], dict) else None
    if not isinstance(steps, list) or len(steps) != 3:
        raise ValueError("routing_three_step_sequence_required")
    if steps[0].get("variants") != [{
        "subject":"{{leadscanner_subject}}", "body":"{{leadscanner_body}}"
    }]:
        raise ValueError("routing_personalized_first_step_required")
    for step in steps:
        if step.get("type") != "email" or not isinstance(step.get("variants"), list) or len(step["variants"]) != 1:
            raise ValueError("routing_email_step_contract_invalid")
    if campaign.get("allow_risky_contacts") is not False or campaign.get("stop_on_reply") is not True:
        raise ValueError("routing_campaign_safety_options_required")


def _wait_job(client: InstantlyClient, job: object, *, sleep_fn=time.sleep) -> None:
    job_id = _text(job.get("id") or job.get("job_id")) if isinstance(job, dict) else ""
    if not job_id or not re.fullmatch(r"[a-zA-Z0-9-]{12,100}", job_id):
        raise RuntimeError("routing_background_job_id_missing")
    for i in range(30):
        status = client._request("GET", "/background-jobs/" + job_id, retry_safe=True) or {}
        if not isinstance(status, dict):
            raise RuntimeError("routing_background_job_invalid")
        state = _text(status.get("status")).casefold()
        if state in {"completed","success"}:
            return
        if state in {"failed","error"}:
            raise RuntimeError("routing_background_job_failed")
        if state not in {"pending","processing","in_progress","queued","running","created",""}:
            raise RuntimeError("routing_background_job_unknown_status")
        if i < 29:
            sleep_fn(1)
    raise RuntimeError("routing_background_job_pending_no_retry")


def _step(label, func, *args, **kwargs):
    """Use fixed stage names; never log recipient names, emails or provider bodies."""
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        # Expose only HTTP status or fixed transport labels; never provider copy.
        raw = str(exc)
        match = re.fullmatch(r"instantly_api_error status=(\d{3})", raw)
        suffix = ("_http" + match.group(1)) if match else (
            "_network" if raw == "instantly_network_error" else ""
        )
        raise RuntimeError(f"routing_stage_{label}_{type(exc).__name__}{suffix}") from exc


def route_exact_language(client: InstantlyClient, *, language: str, campaign_id: str, max_leads: int = 25,
                         registry_url: str = DEFAULT_REGISTRY_URL) -> dict:
    if language not in {"nl","en"}:
        raise ValueError("routing_language_invalid")
    if type(max_leads) is not int or not 1 <= max_leads <= MAX_ROUTE_BATCH:
        raise ValueError("routing_batch_limit_invalid")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", campaign_id or ""):
        raise ValueError("routing_campaign_id_invalid")

    _step('campaign_preflight', preflight_campaign, client, language, campaign_id)
    source_id, rows = _step('source_list', read_imported_leads, client)
    registry = _step('registry', fetch_live_registry, registry_url=registry_url)
    blocklist = _step('blocklist', blocked_values, client)
    already = _step('destination_before', destination_emails, client, campaign_id)
    counters = Counter()
    selected = []
    for row in sorted(rows, key=lambda v: _text(v.get("email")).casefold()):
        if inspect_lead_language(row) != language:
            continue
        email = _text(row.get("email")).casefold()
        if email in already:
            counters["already_present"] += 1
            continue
        domain = email.rsplit("@", 1)[-1]
        if not email or "@" not in email or domain in HOLD_FREE_MAIL:
            counters["personal_email_hold"] += 1
            continue
        if email in blocklist or domain in blocklist:
            counters["blocklist_hold"] += 1
            continue
        variables = row.get("payload") or row.get("custom_variables") or {}
        if variables.get("leadscanner_contact_basis") != "review_required":
            counters["contact_basis_hold"] += 1
            continue
        if not registry_allows_draft({
            "email":email, "lead_id":_text(variables.get("leadscanner_source_lead_id")),
        }, registry):
            counters["registry_hold"] += 1
            continue
        if (not isinstance(row.get("id"), str)
                or not re.fullmatch(r"[0-9a-fA-F-]{36}", row["id"])):
            counters["missing_provider_id_hold"] += 1
            continue
        selected.append(row)
    selected = selected[:max_leads]
    result = {
        "schema_version": "leadscanner-instantly-language-route/1.0",
        "language": language,
        "campaign_id": campaign_id,
        "source_list_id": source_id,
        "source_count": len(rows),
        "route_candidates_remaining": max(0, sum(inspect_lead_language(row) == language for row in rows)
                                           - counters["already_present"] - counters["personal_email_hold"]
                                           - counters["blocklist_hold"] - counters["contact_basis_hold"]
                                           - counters["registry_hold"] - counters["missing_provider_id_hold"]),
        "already_present_count": counters["already_present"],
        "held_counts": {
            k: counters[k] for k in (
                "personal_email_hold", "blocklist_hold",
                "contact_basis_hold", "registry_hold", "missing_provider_id_hold"
            )
        },
        "attempt_count": len(selected),
        "confirmed_copied_count": 0,
        "campaign_activated": False,
        "automatic_send": False,
        "original_list_modified": False,
        "sensitive_contact_data": False,
    }
    if not selected:
        return result

    # Exact pre-write preflight, never allow a changed campaign to receive leads.
    _step("campaign_prewrite", preflight_campaign, client, language, campaign_id)
    payload = {
        "list_id": source_id, "to_campaign_id": campaign_id,
        "ids": [row["id"] for row in selected],
        "copy_leads": True, "reset_interest_status": False,
    }
    # No blind retry of this non-idempotent POST.
    created = _step("copy_write", client._request, "POST", "/leads/move", json=payload)
    _step("background_readback", _wait_job, client, created)
    # Complete one-to-one after-state recheck (no addresses in public result).
    copied = _step('destination_after', destination_emails, client, campaign_id)
    for row in selected:
        if _text(row.get("email")).casefold() not in copied:
            raise RuntimeError("routing_destination_readback_missing_lead")
    _step('campaign_final', preflight_campaign, client, language, campaign_id)
    result["confirmed_copied_count"] = len(selected)
    return result
