"""Read-only, aggregate-only Instantly handoff audit for reviewed historical drafts.

No recipient, content, source URL, company, approval token or campaign ID
is ever serialized to stdout/artifacts. No provider mutations occur here.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from urllib.parse import urlparse

from instantly_client import InstantlyClient
from instantly_campaign_copy import TARGET_CAMPAIGNS
from instantly_historical_site_research import (
    EXPECTED_SOURCE_COUNT, _custom, _source_rows, _text,
)
from instantly_language_campaigns import classify_language
from instantly_language_route import destination_emails, preflight_campaign
from instantly_service import DEFAULT_REGISTRY_URL, fetch_live_registry
from myhost_instantly_import import blocked_values, registry_allows_draft
from dedupe_preflight import normalize_domain

REQUIRED_SUFFIXES = (
    "subject", "body", "observation", "value_action", "evidence_url",
    "source_type", "signal_type", "contact_url", "official_domain",
    "checked_date",
)


# Fixed field categories only. These labels are public-safe; never emit
# destination values, recipient identifiers, URLs, copy, or hashes.
DESTINATION_DIFF_FIELDS = {
    "reviewed_subject": "leadscanner_subject",
    "reviewed_body": "leadscanner_body",
    "reviewed_observation": "leadscanner_observation",
    "reviewed_action": "leadscanner_value_action",
    "reviewed_evidence": "leadscanner_evidence_url",
    "reviewed_source_type": "leadscanner_evidence_source_type",
    "handoff_status": "leadscanner_handoff_status",
    "handoff_date": "leadscanner_handoff_review_date",
    "handoff_digest": "leadscanner_handoff_content_sha256",
}


def _reviewed_refresh(row: dict) -> tuple[str, str]:
    """Return (language, hold_reason) without exposing private input."""
    if row.get("status") in {-1, -2, -3}:
        return "", "suppressed"
    if row.get("campaign") is not None:
        return "", "already_assigned"
    values = _custom(row)
    if values.get("leadscanner_contact_basis") != "review_required":
        return "", "not_review_required"
    status = _text(values.get("leadscanner_site_refresh_status"))
    if status == "research_only_contact_unverified":
        return "", "research_only"
    if status != "candidate_review_required":
        return "", "no_review_candidate"
    fields = {
        suffix: values.get("leadscanner_site_refresh_" + suffix)
        for suffix in REQUIRED_SUFFIXES
    }
    if not all(isinstance(value, str) and value.strip() for value in fields.values()):
        return "", "incomplete_review"
    if fields["source_type"] != "official_site":
        return "", "unverified_source"
    domain = normalize_domain(fields["official_domain"])
    if (
        not domain
        or normalize_domain(fields["evidence_url"]) != domain
        or normalize_domain(fields["contact_url"]) != domain
        or any(token in fields["body"] + fields["subject"] for token in ("{{", "}}", "{%", "%}", "\x00"))
    ):
        return "", "unverified_evidence"
    if "@" not in _text(row.get("email")):
        return "", "invalid_recipient"
    language = classify_language(fields["subject"], fields["body"])
    if language not in TARGET_CAMPAIGNS:
        return "", "unknown_language"
    return language, ""


def audit_counts(rows: list[dict], registry_rows: list[dict], blocked: set[str],
                 destinations: dict[str, set[str]], ready: dict[str, bool]) -> dict:
    counts = Counter()
    languages = Counter()
    seen = set()
    for row in rows:
        counts["source_total"] += 1
        email = _text(row.get("email")).casefold()
        if email in seen:
            raise RuntimeError("handoff_source_duplicate_email")
        seen.add(email)
        language, hold = _reviewed_refresh(row)
        if hold:
            counts[hold] += 1
            continue
        counts["review_candidate"] += 1
        languages[language] += 1
        domain = email.rsplit("@", 1)[-1]
        if email in blocked or any(
            "@" not in entry and (domain == entry or domain.endswith("." + entry))
            for entry in blocked
        ):
            counts["provider_suppression_hold"] += 1
        elif not registry_allows_draft({
            "email": email, "lead_id": _text(_custom(row).get("leadscanner_source_lead_id")),
        }, registry_rows):
            counts["registry_hold"] += 1
        elif email in destinations[language]:
            counts["already_in_target"] += 1
        elif not ready[language]:
            counts["campaign_not_ready"] += 1
        else:
            counts["stage_eligible_review_only"] += 1

    if counts["source_total"] != EXPECTED_SOURCE_COUNT:
        raise RuntimeError("handoff_source_count_changed")
    report_counts = {k: int(counts[k]) for k in (
        "source_total", "review_candidate", "research_only", "no_review_candidate",
        "suppressed", "already_assigned", "not_review_required", "incomplete_review",
        "unverified_source", "unverified_evidence", "invalid_recipient",
        "unknown_language", "provider_suppression_hold", "registry_hold",
        "already_in_target", "campaign_not_ready", "stage_eligible_review_only",
    )}
    report = {
        "schema_version": "leadscanner-historical-handoff-audit/1.0",
        "counts": report_counts,
        "review_languages": {language: int(languages[language]) for language in ("nl", "en")},
        "campaigns_safe_for_staging": {language: bool(ready[language]) for language in ("nl", "en")},
        "contains_contact_data": False,
        "public_artifacts": False,
        "provider_mutation": False,
        "automatic_send": False,
    }
    if (sum(report_counts[k] for k in (
        "research_only", "no_review_candidate", "suppressed", "already_assigned",
        "not_review_required", "incomplete_review", "unverified_source",
        "unverified_evidence", "invalid_recipient", "unknown_language",
    )) + report_counts["review_candidate"]) != report_counts["source_total"]:
        raise RuntimeError("handoff_report_partition_invalid")
    return report


def audit_destination_copies(rows: list[dict], destination: dict[str, dict], client) -> dict[str, int]:
    """Privately verify every existing target copy against exact reviewed source.

    Never print or serialize destination IDs, recipient addresses, copy or hashes.
    """
    # Delayed import avoids circular dependency with stage's audit_counts.
    from historical_handoff_stage import build_destination_variables
    by_email = {
        _text(row.get("email")).casefold(): row
        for row in rows
    }
    counters: Counter[str] = Counter()
    seen = set()
    for language, dest_rows in destination.items():
        for email, summary in dest_rows.items():
            if email in seen:
                counters["duplicate_across_campaigns"] += 1
                continue
            seen.add(email)
            source = by_email.get(email)
            if source is None:
                counters["unexpected_unrelated_target"] += 1
                continue
            expected_language, hold = _reviewed_refresh(source)
            if hold or expected_language != language:
                counters["unexpected_source_or_language"] += 1
                continue
            lead_id = _text(summary.get("id"))
            if not lead_id:
                counters["missing_target_id"] += 1
                continue
            target = client.get_lead(lead_id)
            campaign_id = TARGET_CAMPAIGNS[language][0]
            if (
                not isinstance(target, dict)
                or _text(target.get("id")) != lead_id
                or _text(target.get("email")).casefold() != email
                or _text(target.get("campaign") or target.get("campaign_id")) != campaign_id
                or target.get("status") in {-1, -2, -3}
            ):
                counters["target_identity_or_state_conflict"] += 1
                continue
            try:
                expected_variables = build_destination_variables(source, target)
                actual_variables = _custom(target)
            except (ValueError, RuntimeError, TypeError, KeyError):
                counters["target_copy_source_mismatch"] += 1
                continue
            if actual_variables == expected_variables:
                counters["exact_personalization_verified"] += 1
                continue
            if not _text(actual_variables.get("leadscanner_handoff_status")):
                counters["copied_pending_personalization"] += 1
            else:
                counters["changed_or_unexpected_personalization"] += 1
            for label, key in DESTINATION_DIFF_FIELDS.items():
                if actual_variables.get(key) != expected_variables.get(key):
                    counters["mismatch_" + label] += 1
            other_keys = (
                set(actual_variables) | set(expected_variables)
            ) - set(DESTINATION_DIFF_FIELDS.values())
            if any(actual_variables.get(key) != expected_variables.get(key) for key in other_keys):
                counters["mismatch_other_existing_variable"] += 1
    report_keys = (
        "exact_personalization_verified", "copied_pending_personalization",
        "changed_or_unexpected_personalization",
        "target_copy_source_mismatch", "target_identity_or_state_conflict",
        "unexpected_source_or_language", "unexpected_unrelated_target",
        "duplicate_across_campaigns", "missing_target_id",
        "mismatch_other_existing_variable",
    )
    report_keys += tuple("mismatch_" + label for label in DESTINATION_DIFF_FIELDS)
    return {key: int(counters[key]) for key in report_keys}



def audit_workspace_capacity(client, required_new_copies: int) -> dict:
    """Read the Instantly billing limit without publishing plan or account data.

    This endpoint can be restricted to a different API scope. No available
    quota can be inferred if the response is missing/invalid/inaccessible.
    """
    if type(required_new_copies) is not int or required_new_copies < 0:
        raise ValueError("historical_handoff_invalid_required_capacity")
    try:
        raw = client._request(
            "GET", "/workspace-billing/plan-details", retry_safe=True
        )
    except Exception:
        return {"status": "unavailable", "sufficient_for_remaining": None}
    if not isinstance(raw, dict):
        return {"status": "unknown_schema", "sufficient_for_remaining": None}
    subscriptions = raw.get("subscriptions")
    if not isinstance(subscriptions, dict):
        return {"status": "unknown_schema", "sufficient_for_remaining": None}
    outreach = subscriptions.get("outreach")
    if not isinstance(outreach, dict):
        return {"status": "no_outreach_plan_reported", "sufficient_for_remaining": None}
    limit = outreach.get("total_lead_limit")
    used = outreach.get("current_lead_count")
    if (
        type(limit) is not int or type(used) is not int
        or limit < 0 or used < 0 or used > limit
    ):
        return {"status": "unknown_schema", "sufficient_for_remaining": None}
    available = limit - used
    status = (
        "at_limit" if available == 0
        else "insufficient" if available < required_new_copies
        else "sufficient"
    )
    band = (
        "0" if available == 0
        else "1-9" if available < 10
        else "10-99" if available < 100
        else "100-528" if available < 529
        else "529+"
    )
    return {
        "status": status,
        "sufficient_for_remaining": available >= required_new_copies,
        "remaining_capacity_band": band,
    }


def run() -> dict:
    client = InstantlyClient(os.environ["INSTANTLY_API_KEY"])
    rows = _source_rows(client, EXPECTED_SOURCE_COUNT)
    registry = fetch_live_registry(registry_url=DEFAULT_REGISTRY_URL)
    blocked = blocked_values(client)
    # The existing source and destinations are read only. Destination lead
    # readbacks detect partial /leads/move operations before resuming writes.
    from historical_handoff_stage import destination_rows
    ready, destinations, destination_records = {}, {}, {}
    for language, (campaign_id, _) in TARGET_CAMPAIGNS.items():
        try:
            preflight_campaign(client, language, campaign_id)
        except (ValueError, RuntimeError):
            ready[language] = False
        else:
            ready[language] = True
        destination_records[language] = destination_rows(client, campaign_id)
        destinations[language] = set(destination_records[language])
    report = audit_counts(rows, registry, blocked, destinations, ready)
    report["destination_readback"] = audit_destination_copies(rows, destination_records, client)
    report["provider_capacity"] = audit_workspace_capacity(
        client, report["counts"]["stage_eligible_review_only"]
    )
    return report


def main() -> int:
    try:
        report = run()
    except Exception:
        raise SystemExit("HISTORICAL_HANDOFF_AUDIT=failed_private_details_suppressed") from None
    print("HISTORICAL_HANDOFF_AUDIT=green " + json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
