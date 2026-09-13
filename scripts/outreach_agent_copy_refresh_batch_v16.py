from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from typing import Mapping

from outreach_agent_prepare import CONTACT_HEADERS, CONTACT_SHEET, FULL_QUEUE_HEADERS, PROSPECT_HEADERS, PROSPECT_SHEET
from outreach_agent_prepare_v16 import COPY_CONTRACT, build_prepared_row, qualification_evidence_ok
from outreach_agent_copy_refresh import COPY_FIELDS, REFRESHABLE_STATUSES, TERMINAL_FIELDS, _agent_metadata, _queue_rows_with_numbers, _text
from outreach_sender import QUEUE_SHEET, build_sheets_service, ensure_expected_headers, get_values, rows_from_values
from prospect_agent_qualification import AGENT_QUALIFICATION_HEADERS, AGENT_QUALIFICATION_SHEET
from prospect_target_policy import canonical_country

PRESERVED_FIELDS = (
    "lead_id", "company", "website", "email", "status", "compliance_status", "compliance_basis",
    "opt_out_mode", "stage", "sender_mailbox_id", "sender_email", "sent_at", "followup_sent_at",
    "message_id", "followup_message_id", "reply_at", "bounce_at",
)


def _column_name(index: int) -> str:
    output = ""
    value = index
    while value:
        value, rem = divmod(value - 1, 26)
        output = chr(65 + rem) + output
    return output


def _index_unique(rows, key: str):
    counts = Counter(_text(row.get(key)) for row in rows if _text(row.get(key)))
    return {
        _text(row.get(key)): row
        for row in rows
        if _text(row.get(key)) and counts[_text(row.get(key))] == 1
    }, counts


def _merge(existing: Mapping[str, object], refreshed: Mapping[str, object]) -> dict[str, str]:
    if _text(existing.get("status")).casefold() not in REFRESHABLE_STATUSES:
        raise RuntimeError("queue status is not safe for copy refresh")
    if any(_text(existing.get(field)) for field in TERMINAL_FIELDS):
        raise RuntimeError("queue row already has send/reply/bounce evidence")
    for field in ("lead_id", "company", "website", "email"):
        if _text(existing.get(field)).casefold() != _text(refreshed.get(field)).casefold():
            raise RuntimeError(f"copy refresh identity mismatch for {field}")
    old_meta = _agent_metadata(existing)
    new_meta = _agent_metadata(refreshed)
    if _text(old_meta.get("agent_type")).casefold() != _text(new_meta.get("agent_type")).casefold():
        raise RuntimeError("copy refresh cannot switch agent type")
    if _text(new_meta.get("copy_contract")) != COPY_CONTRACT:
        raise RuntimeError("refreshed row did not produce the current v16 copy contract")

    merged = {header: str(existing.get(header, "")) for header in FULL_QUEUE_HEADERS}
    for field in COPY_FIELDS:
        merged[field] = str(refreshed.get(field, ""))
    merged["last_error"] = ""
    for field in PRESERVED_FIELDS:
        if field in merged:
            merged[field] = str(existing.get(field, ""))
    return merged


def _write_report(path: str, payload: Mapping[str, object]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def refresh_batch(*, spreadsheet_id: str, country: str, limit: int, report_path: str) -> dict[str, object]:
    if not spreadsheet_id.strip() or not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("OUTREACH_SPREADSHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON are required")
    country = canonical_country(country)
    if not country:
        raise ValueError("country is required")
    limit = max(1, min(int(limit), 500))

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

    candidates_by_id, candidate_counts = _index_unique(candidates, "candidate_id")
    qualifications_by_id, qualification_counts = _index_unique(qualifications, "candidate_id")
    contacts_by_id, contact_counts = _index_unique(contacts, "candidate_id")

    changes: list[tuple[int, dict[str, str]]] = []
    skipped: list[dict[str, str]] = []
    already_current = 0
    considered = 0

    for row_number, existing in queue_rows:
        if len(changes) >= limit:
            break
        if _text(existing.get("status")).casefold() not in REFRESHABLE_STATUSES:
            continue
        if canonical_country(_text(existing.get("country"))) != country:
            continue
        if any(_text(existing.get(field)) for field in TERMINAL_FIELDS):
            continue
        source = _text(existing.get("source"))
        if not source.startswith("agent_offer:"):
            continue
        considered += 1
        try:
            old_meta = _agent_metadata(existing)
        except RuntimeError as exc:
            skipped.append({"lead_id": _text(existing.get("lead_id")), "reason": str(exc)})
            continue
        if _text(old_meta.get("copy_contract")) == COPY_CONTRACT:
            already_current += 1
            continue

        lead_id = _text(existing.get("lead_id"))
        if not lead_id or candidate_counts.get(lead_id) != 1 or qualification_counts.get(lead_id) != 1 or contact_counts.get(lead_id) != 1:
            skipped.append({"lead_id": lead_id, "reason": "candidate/qualification/contact identity is not unique"})
            continue
        candidate = candidates_by_id[lead_id]
        qualification = qualifications_by_id[lead_id]
        contact = contacts_by_id[lead_id]
        agent_type = _text(qualification.get("agent_type")).casefold()
        if not qualification_evidence_ok(candidate, qualification, agent_type=agent_type):
            skipped.append({"lead_id": lead_id, "reason": "current evidence contract is not satisfied"})
            continue
        if _text(old_meta.get("agent_type")).casefold() != agent_type:
            skipped.append({"lead_id": lead_id, "reason": "existing queue agent does not match current qualification"})
            continue

        try:
            os.environ["AGENT_SALES_TARGET_TYPE"] = agent_type
            refreshed = build_prepared_row(
                candidate,
                qualification,
                contact,
                postal_address=os.getenv("OUTREACH_POSTAL_ADDRESS", ""),
                sender_mailbox_id=_text(existing.get("sender_mailbox_id")) or os.getenv("OUTREACH_MAILBOX_ID", "primary"),
                sender_email=_text(existing.get("sender_email")) or os.getenv("OUTREACH_SENDER_EMAIL", "info@andrewbaeten.nl"),
            )
            merged = _merge(existing, refreshed)
        except (RuntimeError, ValueError, OSError) as exc:
            skipped.append({"lead_id": lead_id, "reason": str(exc)[:240]})
            continue
        changes.append((row_number, merged))

    if changes:
        end_column = _column_name(len(FULL_QUEUE_HEADERS))
        data = [
            {
                "range": f"'{QUEUE_SHEET}'!A{row_number}:{end_column}{row_number}",
                "values": [[merged.get(header, "") for header in FULL_QUEUE_HEADERS]],
            }
            for row_number, merged in changes
        ]
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "RAW", "data": data},
        ).execute()

        readback_values = get_values(service, spreadsheet_id, QUEUE_SHEET)
        _, readback_rows = _queue_rows_with_numbers(readback_values)
        readback_by_number = {number: row for number, row in readback_rows}
        for row_number, merged in changes:
            readback = readback_by_number.get(row_number)
            if not readback:
                raise RuntimeError(f"copy refresh readback missing row {row_number}")
            for field in FULL_QUEUE_HEADERS:
                if str(readback.get(field, "")) != str(merged.get(field, "")):
                    raise RuntimeError(f"copy refresh readback mismatch row={row_number} field={field}")
            if _text(_agent_metadata(readback).get("copy_contract")) != COPY_CONTRACT:
                raise RuntimeError(f"copy refresh readback row {row_number} is not current v16")

    report = {
        "status": "green",
        "country": country,
        "considered": considered,
        "refreshed": len(changes),
        "already_current": already_current,
        "skipped": skipped,
        "copy_contract": COPY_CONTRACT,
        "send_permission": "none",
        "mailbox_write": "not_invoked",
        "smtp_send": "not_invoked",
    }
    _write_report(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh safe unsent agent outreach rows to the v16 source-aligned copy contract.")
    parser.add_argument("--country", required=True)
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--report", default="outreach-agent-copy-refresh-batch-v16.json")
    args = parser.parse_args()
    try:
        report = refresh_batch(
            spreadsheet_id=os.getenv("OUTREACH_SPREADSHEET_ID", ""),
            country=args.country,
            limit=args.limit,
            report_path=args.report,
        )
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"OUTREACH_COPY_REFRESH_V16=blocked detail={exc} send_permission=none smtp_send=not_invoked")
        return 2
    print(
        "OUTREACH_COPY_REFRESH_V16=green "
        f"refreshed={report['refreshed']} already_current={report['already_current']} "
        f"skipped={len(report['skipped'])} copy_contract={COPY_CONTRACT} "
        "send_permission=none mailbox_write=not_invoked smtp_send=not_invoked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
