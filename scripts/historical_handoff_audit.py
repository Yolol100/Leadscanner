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


def run() -> dict:
    client = InstantlyClient(os.environ["INSTANTLY_API_KEY"])
    rows = _source_rows(client, EXPECTED_SOURCE_COUNT)
    registry = fetch_live_registry(registry_url=DEFAULT_REGISTRY_URL)
    blocked = blocked_values(client)
    ready, destinations = {}, {}
    for language, (campaign_id, _) in TARGET_CAMPAIGNS.items():
        try:
            preflight_campaign(client, language, campaign_id)
        except (ValueError, RuntimeError):
            ready[language] = False
        else:
            ready[language] = True
        destinations[language] = destination_emails(client, campaign_id)
    return audit_counts(rows, registry, blocked, destinations, ready)


def main() -> int:
    try:
        report = run()
    except Exception:
        raise SystemExit("HISTORICAL_HANDOFF_AUDIT=failed_private_details_suppressed") from None
    print("HISTORICAL_HANDOFF_AUDIT=green " + json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
