#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os

from outreach_agent_prepare import CONTACT_SHEET, LEAD_SHEET, PROSPECT_SHEET
from outreach_sender import QUEUE_SHEET, build_sheets_service, get_values, rows_from_values
from prospect_discovery import host_key


def text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def email(value: object) -> str:
    return text(value).casefold()


def _rows(service, spreadsheet_id: str, sheet: str):
    _, rows = rows_from_values(get_values(service, spreadsheet_id, sheet))
    return rows


def capture(*, spreadsheet_id: str, output: str) -> dict[str, list[str]]:
    if not spreadsheet_id.strip():
        raise RuntimeError("OUTREACH_SPREADSHEET_ID is required")
    if not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is required")
    if not output.strip():
        raise RuntimeError("baseline output path is required")

    service = build_sheets_service()
    queue_rows = _rows(service, spreadsheet_id, QUEUE_SHEET)
    prospect_rows = _rows(service, spreadsheet_id, PROSPECT_SHEET)
    contact_rows = _rows(service, spreadsheet_id, CONTACT_SHEET)
    lead_rows = _rows(service, spreadsheet_id, LEAD_SHEET)

    lead_ids: set[str] = set()
    domains: set[str] = set()
    emails: set[str] = set()

    def add_id(value: object) -> None:
        value = text(value)
        if value:
            lead_ids.add(value)

    def add_domain(value: object) -> None:
        value = host_key(text(value))
        if value:
            domains.add(value)

    def add_email(value: object) -> None:
        value = email(value)
        if value:
            emails.add(value)

    for row in queue_rows:
        add_id(row.get("lead_id"))
        add_domain(row.get("website"))
        add_email(row.get("email"))

    for row in prospect_rows:
        add_id(row.get("candidate_id"))
        add_domain(row.get("website"))

    for row in contact_rows:
        add_id(row.get("candidate_id"))
        add_domain(row.get("website"))
        add_email(row.get("email"))

    for row in lead_rows:
        add_domain(row.get("Website"))
        add_email(row.get("E-mail"))

    baseline = {
        "lead_ids": sorted(lead_ids),
        "domains": sorted(domains),
        "emails": sorted(emails),
    }
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(baseline, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return baseline


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture fail-closed pre-run net-new lead baseline")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        baseline = capture(
            spreadsheet_id=os.getenv("OUTREACH_SPREADSHEET_ID", ""),
            output=args.output,
        )
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"DRAFT_FIRST_BASELINE=blocked detail={exc} smtp_send=not_invoked")
        return 2
    print(
        "DRAFT_FIRST_BASELINE=green "
        f"lead_ids={len(baseline['lead_ids'])} domains={len(baseline['domains'])} "
        f"emails={len(baseline['emails'])} smtp_send=not_invoked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
