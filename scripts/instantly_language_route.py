"""Copy confirmed NL/EN mijn.host draft leads into non-sending Instantly campaigns.

Every mutation is an allowlisted GitHub command. Never send, activate, delete, or
change the source lead list. The campaign must be Draft or Paused with zero sender accounts. Active,
completed, unrecognized, or sender-assigned campaigns are rejected.
Provider jobs are not retried if their outcome is uncertain.
"""
from __future__ import annotations

import re
import time
from collections import Counter

from instantly_language_campaigns import (
    LANGUAGE_CAMPAIGN_NAMES, classify_language, inspect_lead_language, read_imported_leads,
)
from instantly_client import InstantlyClient, SAFE_CAMPAIGN_STATUSES
from instantly_campaign_copy import campaign_copy_matches, first_mail_uses_verified_recipient_detail
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


def _private_first_mail_pair(row: dict) -> tuple[str, str] | None:
    """Normalize only for in-memory duplicate detection, never publish copy."""
    values = row.get("payload")
    if not isinstance(values, dict):
        values = row.get("custom_variables")
    if not isinstance(values, dict):
        return None
    subject, body = values.get("leadscanner_subject"), values.get("leadscanner_body")
    if not isinstance(subject, str) or not subject.strip() or not isinstance(body, str) or not body.strip():
        return None
    return (" ".join(subject.casefold().split()), " ".join(body.casefold().split()))


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
    if type(campaign.get("status")) is not int or campaign["status"] not in SAFE_CAMPAIGN_STATUSES:
        raise ValueError("routing_target_must_be_draft_or_paused")
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
    if not campaign_copy_matches(campaign, language):
        raise ValueError("routing_campaign_copy_readback_mismatch")


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
                         registry_url: str = DEFAULT_REGISTRY_URL, dry_run: bool = False) -> dict:
    if language not in {"nl","en"}:
        raise ValueError("routing_language_invalid")
    if type(max_leads) is not int or not 1 <= max_leads <= MAX_ROUTE_BATCH:
        raise ValueError("routing_batch_limit_invalid")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", campaign_id or ""):
        raise ValueError("routing_campaign_id_invalid")
    if type(dry_run) is not bool:
        raise ValueError("routing_dry_run_must_be_boolean")

    _step('campaign_preflight', preflight_campaign, client, language, campaign_id)
    source_id, rows = _step('source_list', read_imported_leads, client)
    # Two real imported contacts have an identical normalized subject/body pair.
    # Identical first-mail copy is not independently reviewed as recipient-specific.
    # Hold both copies until differentiated copy is reviewed; do not guess edits.
    private_first_mail_counts = Counter(
        pair for row in rows if (pair := _private_first_mail_pair(row)) is not None
    )
    # Equal observations for different contacts can pass a name-swap test.
    # Until an actual distinct website detail is reviewed, both stay held.
    first_party_observation_counts = Counter(
        " ".join(text.casefold().split())
        for row in rows
        if isinstance((values := row.get("payload") or row.get("custom_variables")), dict)
        if isinstance((text := values.get("leadscanner_observation")), str) and text.strip()
    )
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
        if email in blocklist or any(
            "@" not in entry and (domain == entry or domain.endswith("." + entry))
            for entry in blocklist
        ):
            counters["blocklist_hold"] += 1
            continue
        variables = row.get("payload") or row.get("custom_variables") or {}
        basis = variables.get("leadscanner_contact_basis")
        proof = variables.get("leadscanner_contact_basis_ref")
        if basis not in {"consent_verified", "existing_customer_related_verified"} or (
            not isinstance(proof, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._/-]{7,160}", proof)
        ):
            counters["contact_basis_hold"] += 1
            continue
        reviewed_subject = variables.get("leadscanner_subject")
        reviewed_body = variables.get("leadscanner_body")
        if not isinstance(reviewed_subject, str) or not reviewed_subject.strip() or (
            not isinstance(reviewed_body, str) or not reviewed_body.strip()
        ):
            counters["missing_reviewed_first_mail_hold"] += 1
            continue
        if "webactueel" in (reviewed_subject + "\n" + reviewed_body).casefold():
            counters["obsolete_sender_brand_hold"] += 1
            continue
        # Signed full business identity is required for step 1; do not silently
        # rewrite already reviewed imported mail. Missing signatures need review.
        if not re.search(r"(?im)^\s*(?:groet|met vriendelijke groet|best|kind regards),?\s*\n\s*andrew baeten\s*$", reviewed_body):
            counters["sender_identity_hold"] += 1
            continue
        private_pair = _private_first_mail_pair(row)
        if private_pair is None or private_first_mail_counts[private_pair] > 1:
            counters["duplicate_first_mail_copy_hold"] += 1
            continue
        # Legacy mail copy alone is not enough to personalize follow-ups.
        # Only move leads with concrete first-party evidence and an offer tied
        # to that evidence. Missing facts stay in the unsendable source list.
        if (
            variables.get("leadscanner_evidence_source_type") != "official_site"
            or not all(isinstance(variables.get(key),str) and variables[key].strip() for key in (
                "leadscanner_observation","leadscanner_value_action","leadscanner_evidence_url"
            ))
        ):
            counters["personalization_evidence_hold"] += 1
            continue
        if not first_mail_uses_verified_recipient_detail(
            reviewed_body, variables["leadscanner_observation"],
            variables["leadscanner_value_action"],
            variables["leadscanner_evidence_source_type"],
            variables["leadscanner_evidence_url"],
        ):
            counters["first_mail_not_recipient_specific_hold"] += 1
            continue
        if first_party_observation_counts[
            " ".join(variables["leadscanner_observation"].casefold().split())
        ] > 1:
            counters["reused_website_observation_hold"] += 1
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
    eligible_count = len(selected)
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
                                           - counters["personalization_evidence_hold"] - counters["obsolete_sender_brand_hold"]
                                           - counters["missing_reviewed_first_mail_hold"] - counters["sender_identity_hold"]
                                           - counters["duplicate_first_mail_copy_hold"]
                                           - counters["first_mail_not_recipient_specific_hold"]
                                           - counters["reused_website_observation_hold"] - counters["registry_hold"] - counters["missing_provider_id_hold"]),
        "already_present_count": counters["already_present"],
        "held_counts": {
            k: counters[k] for k in (
                "personal_email_hold", "blocklist_hold",
                "contact_basis_hold", "personalization_evidence_hold",
                "obsolete_sender_brand_hold", "missing_reviewed_first_mail_hold",
                "sender_identity_hold", "duplicate_first_mail_copy_hold",
                "first_mail_not_recipient_specific_hold",
                "reused_website_observation_hold",
                "registry_hold", "missing_provider_id_hold"
            )
        },
        "eligible_candidate_count": eligible_count,
        "attempt_count": 0 if dry_run else len(selected),
        "dry_run": dry_run,
        "confirmed_copied_count": 0,
        "campaign_activated": False,
        "automatic_send": False,
        "original_list_modified": False,
        "sensitive_contact_data": False,
    }
    if dry_run or not selected:
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
