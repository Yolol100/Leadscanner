from __future__ import annotations

import argparse
import json
import os
import re
from typing import Mapping, Sequence

from outreach_agent_prepare import CONTACT_HEADERS, CONTACT_SHEET, FULL_QUEUE_HEADERS, PROSPECT_HEADERS, PROSPECT_SHEET
from outreach_agent_prepare_v2 import COPY_CONTRACT, build_prepared_row
from outreach_sender import QUEUE_SHEET, build_sheets_service, ensure_expected_headers, get_values, rows_from_values
from prospect_agent_qualification import AGENT_CATALOG, AGENT_QUALIFICATION_HEADERS, AGENT_QUALIFICATION_SHEET

SAFE_LEAD_ID = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
REFRESHABLE_STATUSES = {"prepared", "manual_review"}
TERMINAL_FIELDS = ("sent_at", "followup_sent_at", "message_id", "followup_message_id", "reply_at", "bounce_at")
COPY_FIELDS = (
    "subject",
    "body",
    "followup_subject",
    "followup_body",
    "followup_delay_days",
    "verification_status",
    "verification_checked_at",
    "source",
)


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _one(rows: Sequence[Mapping[str, object]], key: str, value: str, label: str) -> Mapping[str, object]:
    matches = [row for row in rows if _text(row.get(key)) == value]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {label} row for lead_id; found {len(matches)}")
    return matches[0]


def _queue_rows_with_numbers(values: list[list[str]]) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    if not values:
        return [], []
    headers = [str(value).strip() for value in values[0]]
    rows: list[tuple[int, dict[str, str]]] = []
    for offset, raw in enumerate(values[1:], start=2):
        padded = list(raw) + [""] * max(0, len(headers) - len(raw))
        rows.append((offset, {headers[index]: str(padded[index]) for index in range(len(headers))}))
    return headers, rows


def _agent_metadata(row: Mapping[str, object]) -> dict[str, object]:
    source = _text(row.get("source"))
    if not source.startswith("agent_offer:"):
        raise RuntimeError("existing queue row is not an agent_offer row")
    try:
        payload = json.loads(source.split(":", 1)[1])
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("existing agent_offer metadata is invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("existing agent_offer metadata must be an object")
    return payload


def merge_refreshed_copy(existing: Mapping[str, object], refreshed: Mapping[str, object]) -> dict[str, str]:
    status = _text(existing.get("status")).casefold()
    if status not in REFRESHABLE_STATUSES:
        raise RuntimeError("queue status is not safe for copy refresh")
    if any(_text(existing.get(field)) for field in TERMINAL_FIELDS):
        raise RuntimeError("queue row already has send/reply/bounce evidence")

    for field in ("lead_id", "company", "website", "email"):
        if _text(existing.get(field)).casefold() != _text(refreshed.get(field)).casefold():
            raise RuntimeError(f"copy refresh identity mismatch for {field}")

    old_meta = _agent_metadata(existing)
    new_meta = _agent_metadata(refreshed)
    old_agent = _text(old_meta.get("agent_type")).casefold()
    new_agent = _text(new_meta.get("agent_type")).casefold()
    if not old_agent or old_agent != new_agent:
        raise RuntimeError("copy refresh cannot switch agent type")
    if _text(new_meta.get("copy_contract")) != COPY_CONTRACT:
        raise RuntimeError("refreshed row did not produce the current v13.5 copy contract")

    merged = {header: str(existing.get(header, "")) for header in FULL_QUEUE_HEADERS}
    for field in COPY_FIELDS:
        merged[field] = str(refreshed.get(field, ""))
    merged["last_error"] = ""
    # Independent commercial gates stay unchanged. This command refreshes copy only
    # and never turns manual review/prepared state into live send permission.
    for field in ("status", "compliance_status", "compliance_basis", "opt_out_mode", "stage", "sender_mailbox_id", "sender_email"):
        merged[field] = str(existing.get(field, ""))
    return merged


def _write_report(path: str, payload: Mapping[str, object]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def refresh_one(*, lead_id: str, spreadsheet_id: str, report_path: str) -> dict[str, str]:
    if not SAFE_LEAD_ID.fullmatch(lead_id or ""):
        raise ValueError("lead_id contains unsupported characters")
    if not spreadsheet_id.strip():
        raise RuntimeError("OUTREACH_SPREADSHEET_ID is required")
    if not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is required")

    service = build_sheets_service()
    candidate_headers, candidates = rows_from_values(get_values(service, spreadsheet_id, PROSPECT_SHEET))
    ensure_expected_headers(candidate_headers, PROSPECT_HEADERS, PROSPECT_SHEET)
    qualification_headers, qualifications = rows_from_values(get_values(service, spreadsheet_id, AGENT_QUALIFICATION_SHEET))
    ensure_expected_headers(qualification_headers, AGENT_QUALIFICATION_HEADERS, AGENT_QUALIFICATION_SHEET)
    contact_headers, contacts = rows_from_values(get_values(service, spreadsheet_id, CONTACT_SHEET))
    ensure_expected_headers(contact_headers, CONTACT_HEADERS, CONTACT_SHEET)
    queue_values = get_values(service, spreadsheet_id, QUEUE_SHEET)
    queue_headers, queue_rows = _queue_rows_with_numbers(queue_values)
    ensure_expected_headers(queue_headers, FULL_QUEUE_HEADERS, QUEUE_SHEET)

    candidate = _one(candidates, "candidate_id", lead_id, PROSPECT_SHEET)
    qualification = _one(qualifications, "candidate_id", lead_id, AGENT_QUALIFICATION_SHEET)
    contact = _one(contacts, "candidate_id", lead_id, CONTACT_SHEET)
    queue_matches = [(row_number, row) for row_number, row in queue_rows if _text(row.get("lead_id")) == lead_id]
    if len(queue_matches) != 1:
        raise RuntimeError(f"expected exactly one OutreachQueue row for lead_id; found {len(queue_matches)}")
    row_number, existing = queue_matches[0]

    agent_type = _text(qualification.get("agent_type")).casefold()
    if agent_type not in AGENT_CATALOG:
        raise RuntimeError("qualification does not contain one approved agent type")
    old_meta = _agent_metadata(existing)
    if _text(old_meta.get("agent_type")).casefold() != agent_type:
        raise RuntimeError("existing queue agent does not match current qualification")

    os.environ["AGENT_SALES_TARGET_TYPE"] = agent_type
    refreshed = build_prepared_row(
        candidate,
        qualification,
        contact,
        postal_address=os.getenv("OUTREACH_POSTAL_ADDRESS", ""),
        sender_mailbox_id=_text(existing.get("sender_mailbox_id")) or os.getenv("OUTREACH_MAILBOX_ID", "primary"),
        sender_email=_text(existing.get("sender_email")) or os.getenv("OUTREACH_SENDER_EMAIL", "info@andrewbaeten.nl"),
    )
    merged = merge_refreshed_copy(existing, refreshed)

    end_column = chr(ord("A") + len(FULL_QUEUE_HEADERS) - 1) if len(FULL_QUEUE_HEADERS) <= 26 else "AC"
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{QUEUE_SHEET}'!A{row_number}:{end_column}{row_number}",
        valueInputOption="RAW",
        body={"values": [[merged.get(header, "") for header in FULL_QUEUE_HEADERS]]},
    ).execute()

    readback_values = get_values(service, spreadsheet_id, QUEUE_SHEET)
    _, readback_rows = _queue_rows_with_numbers(readback_values)
    readback_matches = [row for number, row in readback_rows if number == row_number and _text(row.get("lead_id")) == lead_id]
    if len(readback_matches) != 1:
        raise RuntimeError("copy refresh write succeeded but exact queue readback failed")
    readback = readback_matches[0]
    for field in FULL_QUEUE_HEADERS:
        if str(readback.get(field, "")) != str(merged.get(field, "")):
            raise RuntimeError(f"copy refresh readback mismatch for {field}")
    metadata = _agent_metadata(readback)
    if _text(metadata.get("copy_contract")) != COPY_CONTRACT:
        raise RuntimeError("copy refresh readback is not on the current v13.5 contract")

    report = {
        "lead_id": lead_id,
        "row_number": row_number,
        "agent_type": agent_type,
        "copy_contract": COPY_CONTRACT,
        "status": readback.get("status", ""),
        "compliance_status": readback.get("compliance_status", ""),
        "compliance_basis_preserved": readback.get("compliance_basis", ""),
        "send_permission": "none",
        "smtp_send": "not_invoked",
    }
    _write_report(report_path, report)
    return readback


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh exactly one existing agent outreach row to current v13.5 copy without granting send permission.")
    parser.add_argument("--lead-id", required=True)
    parser.add_argument("--report", default="outreach-agent-copy-refresh-report.json")
    args = parser.parse_args(argv)
    try:
        row = refresh_one(
            lead_id=args.lead_id.strip(),
            spreadsheet_id=os.getenv("OUTREACH_SPREADSHEET_ID", ""),
            report_path=args.report,
        )
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"OUTREACH_AGENT_COPY_REFRESH=blocked detail={exc}")
        return 2
    metadata = _agent_metadata(row)
    print(
        "OUTREACH_AGENT_COPY_REFRESH=green "
        f"lead_id={args.lead_id.strip()} copy_contract={metadata.get('copy_contract', '')} "
        f"status={row.get('status', '')} compliance_status={row.get('compliance_status', '')} "
        "send_permission=none smtp_send=not_invoked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
