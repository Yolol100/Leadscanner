from __future__ import annotations

import os
from collections import Counter

from outreach_replyhub import REPLY_HEADERS, REPLY_SHEET
from outreach_reporting import (
    MAILBOX_HEALTH_HEADERS,
    MAILBOX_HEALTH_SHEET,
    VARIANT_ANALYTICS_HEADERS,
    VARIANT_ANALYTICS_SHEET,
)
from outreach_sender import (
    QUEUE_HEADERS,
    QUEUE_SHEET,
    build_sheets_service,
    ensure_expected_headers,
    get_values,
    rows_from_values,
)
from outreach_sequences import (
    SEQUENCE_HEADERS,
    SEQUENCE_SHEET,
    enabled as sequence_enabled,
    validate_sequence_rows,
)

SEQUENCE_QUEUE_STATES = {
    "approved",
    "verification_pending",
    "sent",
    "followup_sent",
    "sequence_complete",
    "replied",
    "opted_out",
    "bounced",
    "blocked",
    "manual_review",
    "error",
    "sending",
}


def validate_queue_sequence_alignment(
    queue_rows: list[dict[str, str]],
    sequence_rows: list[dict[str, str]],
) -> list[str]:
    errors: list[str] = []
    queue_ids = [str(row.get("lead_id", "")).strip() for row in queue_rows if str(row.get("lead_id", "")).strip()]
    counts = Counter(queue_ids)
    queue_by_lead = {
        str(row.get("lead_id", "")).strip(): row
        for row in queue_rows
        if str(row.get("lead_id", "")).strip()
    }
    for lead_id, count in counts.items():
        if count > 1:
            errors.append(f"OutreachQueue has duplicate lead_id {lead_id}")

    sequence_leads = {
        str(row.get("lead_id", "")).strip()
        for row in sequence_rows
        if sequence_enabled(row) and str(row.get("lead_id", "")).strip()
    }
    for lead_id in sorted(sequence_leads):
        queue = queue_by_lead.get(lead_id)
        if queue is None:
            errors.append(f"sequence lead {lead_id} has no matching OutreachQueue row")
            continue
        state = str(queue.get("status", "")).strip().lower()
        if state not in SEQUENCE_QUEUE_STATES:
            errors.append(
                f"sequence lead {lead_id} queue status {state or '<blank>'} is not transport-approved; "
                "review the lead and set an allowed lifecycle state before running the workflow"
            )
    return errors


def check_extended_contract(service, spreadsheet_id: str) -> list[str]:
    checks: list[str] = []

    queue_headers, queue_rows = rows_from_values(
        get_values(service, spreadsheet_id, QUEUE_SHEET)
    )
    ensure_expected_headers(queue_headers, QUEUE_HEADERS, QUEUE_SHEET)
    checks.append(f"sheet:{QUEUE_SHEET}:alignment")

    sequence_headers, sequence_rows = rows_from_values(
        get_values(service, spreadsheet_id, SEQUENCE_SHEET)
    )
    ensure_expected_headers(sequence_headers, SEQUENCE_HEADERS, SEQUENCE_SHEET)
    errors = validate_sequence_rows(sequence_rows)
    errors.extend(validate_queue_sequence_alignment(queue_rows, sequence_rows))
    if errors:
        raise RuntimeError("sequence contract failed: " + "; ".join(errors[:20]))
    checks.append(f"sheet:{SEQUENCE_SHEET}")

    for sheet_name, expected in (
        (REPLY_SHEET, REPLY_HEADERS),
        (VARIANT_ANALYTICS_SHEET, VARIANT_ANALYTICS_HEADERS),
        (MAILBOX_HEALTH_SHEET, MAILBOX_HEALTH_HEADERS),
    ):
        headers, _ = rows_from_values(get_values(service, spreadsheet_id, sheet_name))
        ensure_expected_headers(headers, expected, sheet_name)
        checks.append(f"sheet:{sheet_name}")
    return checks


def main() -> int:
    spreadsheet_id = os.environ["OUTREACH_SPREADSHEET_ID"]
    if not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is required for extended preflight")
    service = build_sheets_service()
    checks = check_extended_contract(service, spreadsheet_id)
    print("EXTENDED_OUTREACH_PREFLIGHT=green checks=" + ",".join(checks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
