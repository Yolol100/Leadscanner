"""One-time, explicitly authorized, no-send handoff of reviewed historical drafts.

Copy existing isolated Instantly source leads to the established unsendable
NL/EN campaigns, then apply the reviewed refresh copy only to the destination.
No sender assignment, activation, mail send, source mutation or public PII.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timezone

from instantly_client import InstantlyClient
from instantly_campaign_copy import TARGET_CAMPAIGNS
from instantly_historical_site_research import (
    EXPECTED_SOURCE_COUNT, BATCH_SIZE, _custom, _source_rows, _text,
)
from historical_handoff_audit import _reviewed_refresh, audit_counts
from instantly_language_route import _items, _wait_job, preflight_campaign
from instantly_service import DEFAULT_REGISTRY_URL, fetch_live_registry
from myhost_instantly_import import TARGET_LIST_ID, blocked_values, registry_allows_draft
from update_dedupe_registry import (
    HEADERS, DEFAULT_SPREADSHEET_ID, DEFAULT_SHEET_NAME,
    check_registry_access, update_registry,
)

EXPECTED_REVIEWED = 776
REVIEW_DATE = "2026-10-12"
MAX_DESTINATION_PAGES = 60


def destination_rows(client, campaign_id: str) -> dict[str, dict]:
    result, cursor, seen = {}, "", set()
    for _ in range(MAX_DESTINATION_PAGES):
        page, next_cursor = _items(
            client.list_leads(campaign=campaign_id, limit=100, starting_after=cursor or None)
        )
        for item in page:
            email = _text(item.get("email")).casefold()
            if email in result or not email or not item.get("id"):
                raise RuntimeError("historical_handoff_duplicate_destination")
            result[email] = item
        if not next_cursor:
            return result
        if next_cursor == cursor or next_cursor in seen or not page:
            raise RuntimeError("historical_handoff_destination_pagination_invalid")
        seen.add(next_cursor)
        cursor = next_cursor
    raise RuntimeError("historical_handoff_destination_limit_exceeded")


def build_destination_variables(source_row: dict, destination_row: dict) -> dict:
    values = _custom(source_row)
    target = _custom(destination_row)
    email = _text(source_row.get("email")).casefold()
    if (
        _text(destination_row.get("email")).casefold() != email
        or target.get("leadscanner_import_origin") != "myhost_drafts"
        or _text(target.get("leadscanner_source_lead_id")) !=
           _text(values.get("leadscanner_source_lead_id"))
        or not _text(values.get("leadscanner_source_lead_id"))
        or values.get("leadscanner_contact_basis") != "review_required"
        or target.get("leadscanner_contact_basis") != "review_required"
    ):
        raise RuntimeError("historical_handoff_destination_identity_mismatch")
    language, reason = _reviewed_refresh(source_row)
    if reason or language not in {"nl", "en"}:
        raise RuntimeError("historical_handoff_source_no_longer_approved")
    if values.get("leadscanner_site_refresh_checked_date") != REVIEW_DATE:
        raise RuntimeError("historical_handoff_review_date_drift")

    edited = dict(target)
    fields = {
        "leadscanner_subject": "leadscanner_site_refresh_subject",
        "leadscanner_body": "leadscanner_site_refresh_body",
        "leadscanner_observation": "leadscanner_site_refresh_observation",
        "leadscanner_value_action": "leadscanner_site_refresh_value_action",
        "leadscanner_evidence_url": "leadscanner_site_refresh_evidence_url",
    }
    for final_key, refresh_key in fields.items():
        edited[final_key] = values[refresh_key]
    edited["leadscanner_evidence_source_type"] = "official_site"
    # No "consent_verified" upgrade: operator approved content for PAUSED
    # staging only. Separate contact permission remains required for sending.
    edited["leadscanner_contact_basis"] = "review_required"
    edited["leadscanner_handoff_status"] = "reviewed_staged_no_send"
    edited["leadscanner_handoff_review_date"] = REVIEW_DATE
    digest = hashlib.sha256(
        json.dumps(
            [edited[k] for k in fields],
            ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    edited["leadscanner_handoff_content_sha256"] = digest
    return edited


def _safe_readback(client, lead_id: str, *, campaign: str, email: str) -> dict:
    result = client.get_lead(lead_id)
    if (
        not isinstance(result, dict)
        or _text(result.get("id")) != lead_id
        or _text(result.get("email")).casefold() != email
        or _text(result.get("campaign") or result.get("campaign_id")) != campaign
        or result.get("status") in {-1, -2, -3}
    ):
        raise RuntimeError("historical_handoff_destination_readback_mismatch")
    return result


def _update_destination(client, source: dict, target: dict, campaign_id: str, *, sleep_fn=time.sleep) -> bool:
    lead_id = _text(target.get("id"))
    email = _text(source.get("email")).casefold()
    before = _safe_readback(client, lead_id, campaign=campaign_id, email=email)
    current = _custom(before)
    expected = build_destination_variables(source, before)
    if current == expected:
        return False
    if _text(current.get("leadscanner_handoff_status")) == "reviewed_staged_no_send":
        # Previously content-bound review cannot silently be replaced by
        # changed recipient copy, even if the source stayed reviewed.
        raise RuntimeError("historical_handoff_already_staged_copy_changed")
    if _text(current.get("leadscanner_handoff_status")):
        raise RuntimeError("historical_handoff_other_status_conflict")
    # Never retry a PATCH of uncertain outcome. Retry GET-only propagation.
    try:
        client._request("PATCH", "/leads/" + lead_id, json={"custom_variables": expected})
    except Exception:
        raise RuntimeError("historical_handoff_write_outcome_unknown_reconcile_first") from None
    for i in range(6):
        after = _safe_readback(client, lead_id, campaign=campaign_id, email=email)
        if (
            _custom(after) == expected
            and after.get("status") == before.get("status")
            and after.get("lt_interest_status") == before.get("lt_interest_status")
        ):
            return True
        if i < 5:
            sleep_fn((0.5, 1, 1.5, 2, 3)[i])
    raise RuntimeError("historical_handoff_destination_variables_readback_mismatch")


def _registry_row(row: dict, language: str) -> list[str]:
    vars_ = _custom(row)
    campaign_id = TARGET_CAMPAIGNS[language][0]
    return [
        _text(row.get("company_name") or vars_.get("company_name")),
        _text(row.get("website") or vars_.get("website")),
        _text(vars_.get("leadscanner_site_refresh_official_domain")),
        _text(row.get("email")).casefold(),
        "instantly_staged", "instantly_staged",
        _text(vars_.get("leadscanner_source_lead_id")),
        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "instantly:campaign:" + campaign_id, "TRUE",
    ]


def stage_batch(
    client, *, offset: int, expected_reviewed: int = EXPECTED_REVIEWED,
    max_targets: int = BATCH_SIZE,
) -> dict:
    if type(offset) is not int or offset < 0 or offset % BATCH_SIZE:
        raise ValueError("historical_handoff_invalid_batch_offset")
    if expected_reviewed != EXPECTED_REVIEWED:
        raise ValueError("historical_handoff_expected_review_count_drift")
    if type(max_targets) is not int or not 1 <= max_targets <= BATCH_SIZE:
        raise ValueError("historical_handoff_max_targets_invalid")
    source = _source_rows(client, EXPECTED_SOURCE_COUNT)
    if offset >= len(source):
        raise ValueError("historical_handoff_offset_outside_source")
    registry = fetch_live_registry(registry_url=DEFAULT_REGISTRY_URL)
    blocked = blocked_values(client)

    # The registry is checked before any provider mutation, and any newly
    # staged identities are recorded with independent exact readback.
    check_registry_access(
        spreadsheet_id=DEFAULT_SPREADSHEET_ID, sheet_name=DEFAULT_SHEET_NAME,
    )
    targets = {}
    ready = {}
    for language, (cid, _) in TARGET_CAMPAIGNS.items():
        preflight_campaign(client, language, cid)
        ready[language] = True
        targets[language] = destination_rows(client, cid)

    audit = audit_counts(
        source, registry, blocked,
        {k: set(v) for k, v in targets.items()}, ready,
    )
    if audit["counts"]["review_candidate"] != expected_reviewed:
        raise RuntimeError("historical_handoff_approved_cohort_changed")
    count = Counter()
    selected: dict[str, list[dict]] = {"nl": [], "en": []}
    copied_to: dict[str, str] = {}
    for row in source[offset:offset+BATCH_SIZE]:
        language, hold = _reviewed_refresh(row)
        if hold:
            count["not_approved_or_research_only"] += 1
            continue
        variables = _custom(row)
        if variables.get("leadscanner_site_refresh_checked_date") != REVIEW_DATE:
            raise RuntimeError("historical_handoff_stale_review_content")
        email = _text(row.get("email")).casefold()
        domain = email.rsplit("@", 1)[-1]
        if email in blocked or any(
            "@" not in v and (domain == v or domain.endswith("." + v))
            for v in blocked
        ):
            count["suppressed"] += 1
            continue
        if not registry_allows_draft({
            "email": email, "lead_id": _text(variables.get("leadscanner_source_lead_id")),
        }, registry):
            count["registry_hold"] += 1
            continue
        if any(email in targets[other] for other in ("nl", "en") if other != language):
            count["other_campaign_hold"] += 1
            continue
        if sum(map(len, selected.values())) >= max_targets:
            count["deferred_after_limit"] += 1
            continue
        # Reconcile a prior partial copy instead of issuing a duplicate POST.
        if email in targets[language]:
            selected[language].append(row)
            count["existing_target_to_verify"] += 1
        else:
            selected[language].append(row)
            count["new_copy_requested"] += 1

    # Freeze the selected source rows immediately before provider writes.
    for language, rows in selected.items():
        if not rows:
            continue
        cid = TARGET_CAMPAIGNS[language][0]
        preflight_campaign(client, language, cid)
        for row in rows:
            src = client.get_lead(_text(row["id"]))
            if (
                not isinstance(src, dict)
                or src.get("id") != row["id"]
                or src.get("list_id") != TARGET_LIST_ID
                or src.get("campaign") is not None
                or src.get("status") in {-1,-2,-3}
                or _text(src.get("email")).casefold() != _text(row.get("email")).casefold()
                or _custom(src) != _custom(row)
            ):
                raise RuntimeError("historical_handoff_source_changed_before_copy")

        fresh = destination_rows(client, cid)
        copy_ids = [
            row["id"] for row in rows
            if _text(row.get("email")).casefold() not in fresh
        ]
        if copy_ids:
            try:
                job = client._request("POST", "/leads/move", json={
                    "list_id": TARGET_LIST_ID,
                    "to_campaign_id": cid,
                    "ids": copy_ids,
                    "copy_leads": True,
                    "reset_interest_status": False,
                })
            except Exception:
                raise RuntimeError("historical_handoff_copy_outcome_unknown_reconcile_first") from None
            _wait_job(client, job)
            fresh = destination_rows(client, cid)

        for row in rows:
            email = _text(row.get("email")).casefold()
            target = fresh.get(email)
            if not target:
                raise RuntimeError("historical_handoff_copied_lead_missing")
            source_now = client.get_lead(_text(row["id"]))
            if (
                not isinstance(source_now, dict)
                or _custom(source_now) != _custom(row)
                or source_now.get("campaign") is not None
                or source_now.get("list_id") != TARGET_LIST_ID
                or source_now.get("status") in {-1, -2, -3}
            ):
                raise RuntimeError("historical_handoff_source_changed_during_copy")
            preflight_campaign(client, language, cid)
            changed = _update_destination(client, row, target, cid)
            count["destination_personalization_confirmed"] += 1
            if changed:
                count["destination_updated"] += 1
            src = client.get_lead(_text(row["id"]))
            if (
                not isinstance(src, dict)
                or src.get("campaign") is not None
                or src.get("list_id") != TARGET_LIST_ID
                or _custom(src) != _custom(row)
            ):
                raise RuntimeError("historical_handoff_source_was_modified")
            copied_to[email] = language
        preflight_campaign(client, language, cid)

    # Registry readback is separate from Instantly readback. Existing
    # historical records already marked for suppression are kept unchanged.
    if copied_to:
        records = [
            _registry_row(row, copied_to[_text(row.get("email")).casefold()])
            for row in source[offset:offset+BATCH_SIZE]
            if _text(row.get("email")).casefold() in copied_to
        ]
        result = update_registry(
            {
                "status": "green", "automatic_send": False,
                "registry_headers": HEADERS,
                "registry_rows": records, "draft_count": len(records),
            },
            spreadsheet_id=DEFAULT_SPREADSHEET_ID,
            sheet_name=DEFAULT_SHEET_NAME,
        )
        if result.get("exact_readback") is not True:
            raise RuntimeError("historical_handoff_registry_readback_missing")
        count["registry_verified"] = len(records)

    report = {
        "schema_version": "leadscanner-historical-paused-stage/1.0",
        "status": "green",
        "batch_offset": offset,
        "batch_size": len(source[offset:offset+BATCH_SIZE]),
        "source_count": len(source),
        "approved_cohort_count": expected_reviewed,
        "counts": dict(sorted(count.items())),
        "source_records_modified": 0,
        "campaign_activation": False,
        "sender_accounts_assigned": False,
        "email_sent": 0,
        "public_prospect_data": False,
    }
    return report


def safe_failure_code(error: Exception) -> str:
    """Never show provider/private exception content in public Actions logs."""
    value = str(error)
    # Internal fixed labels are safe. Never echo email, URL, tokens or bodies.
    if re.fullmatch(
        r"(?:historical_handoff|routing_background_job|routing_stage|registry|live_registry)"
        r"_[a-z0-9_]{3,100}", value,
    ):
        return value
    if re.fullmatch(r"instantly_api_error status=[45][0-9]{2}", value):
        return "instantly_http_" + value.rsplit("=", 1)[-1]
    return {
        ValueError: "value_contract",
        RuntimeError: "runtime_unknown",
        KeyError: "missing_field",
        TypeError: "type_contract",
    }.get(type(error), "unexpected_exception")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", required=True, type=int)
    parser.add_argument("--approved-cohort", type=int, default=EXPECTED_REVIEWED)
    parser.add_argument("--max-targets", type=int, default=BATCH_SIZE)
    args = parser.parse_args()
    try:
        client = InstantlyClient(os.environ["INSTANTLY_API_KEY"])
        result = stage_batch(
            client, offset=args.offset, expected_reviewed=args.approved_cohort,
            max_targets=args.max_targets,
        )
    except Exception as error:
        raise SystemExit(
            "HISTORICAL_PAUSED_STAGE=failed_reconcile_before_retry cause="
            + safe_failure_code(error)
        ) from None
    print("HISTORICAL_PAUSED_STAGE=green " + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
