from __future__ import annotations

import os

from outreach_sender import (
    QUEUE_HEADERS,
    QUEUE_SHEET,
    SUPPRESSION_HEADERS,
    SUPPRESSION_SHEET,
    build_sheets_service,
    ensure_expected_headers,
    get_values,
    normalize_address,
    rows_from_values,
    suppression_match,
    suppression_sets,
)
from prospect_target_policy import canonical_country

POSTAL_PLACEHOLDER = "{{OUTREACH_POSTAL_ADDRESS}}"


def _text(value: object) -> str:
    return str(value or "").strip()


def validate_one_time_batch(
    queue_rows: list[dict[str, str]],
    suppression_rows: list[dict[str, str]],
    expected_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    approved = {
        _text(row.get("lead_id"))
        for row in queue_rows
        if _text(row.get("status")).casefold() == "approved"
    }
    approved.discard("")
    if approved != expected_ids:
        errors.append(
            "approved lead set mismatch: expected="
            + ",".join(sorted(expected_ids))
            + " actual="
            + ",".join(sorted(approved))
        )
        return errors

    rows_by_id = {_text(row.get("lead_id")): row for row in queue_rows if _text(row.get("lead_id"))}
    suppressed_emails, suppressed_domains = suppression_sets(suppression_rows)

    for lead_id in sorted(expected_ids):
        row = rows_by_id.get(lead_id)
        if not row:
            errors.append(f"{lead_id}: missing queue row")
            continue
        if canonical_country(row.get("country", "")) != "US":
            errors.append(f"{lead_id}: country must be US")
        if _text(row.get("compliance_status")).casefold() != "approved":
            errors.append(f"{lead_id}: compliance_status must be approved")
        if _text(row.get("compliance_basis")).casefold() != "other_verified_basis":
            errors.append(f"{lead_id}: compliance_basis must be other_verified_basis")
        if _text(row.get("opt_out_mode")).casefold() != "reply_optout":
            errors.append(f"{lead_id}: opt_out_mode must be reply_optout")
        address = normalize_address(row.get("email", ""))
        if "@" not in address:
            errors.append(f"{lead_id}: invalid email syntax")
        if suppression_match(address, suppressed_emails, suppressed_domains):
            errors.append(f"{lead_id}: recipient is suppressed")
        body = str(row.get("body", ""))
        if POSTAL_PLACEHOLDER not in body:
            errors.append(f"{lead_id}: missing private postal placeholder")
        if "commercial message" not in body.casefold() and "advertisement" not in body.casefold():
            errors.append(f"{lead_id}: missing commercial identification")
    return errors


def process() -> int:
    spreadsheet_id = os.environ["OUTREACH_SPREADSHEET_ID"]
    if not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is required")
    expected_ids = {
        item.strip()
        for item in os.getenv("OUTREACH_ONE_TIME_EXPECTED_LEADS", "").split(",")
        if item.strip()
    }
    if not expected_ids:
        raise RuntimeError("OUTREACH_ONE_TIME_EXPECTED_LEADS is required")

    service = build_sheets_service()
    queue_headers, queue_rows = rows_from_values(get_values(service, spreadsheet_id, QUEUE_SHEET))
    suppression_headers, suppression_rows = rows_from_values(
        get_values(service, spreadsheet_id, SUPPRESSION_SHEET)
    )
    ensure_expected_headers(queue_headers, QUEUE_HEADERS + ["compliance_basis"], QUEUE_SHEET)
    ensure_expected_headers(suppression_headers, SUPPRESSION_HEADERS, SUPPRESSION_SHEET)

    errors = validate_one_time_batch(queue_rows, suppression_rows, expected_ids)
    if errors:
        for error in errors:
            print("one_time_guard_error=" + error)
        print("ONE_TIME_US_OUTREACH_GUARD=blocked")
        return 2
    print("ONE_TIME_US_OUTREACH_GUARD=green expected=" + ",".join(sorted(expected_ids)))
    return 0


if __name__ == "__main__":
    raise SystemExit(process())
