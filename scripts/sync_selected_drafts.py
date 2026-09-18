from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from lead_row import validate_row
from myhost_draft import append_and_verify, build_message, connect_imap, find_drafts_folder
from private_config import load_private_postal_address
from sheets import build_service, get_values, rows_from_values, selected_rows

QUEUE_SHEET = "OutreachQueue"


def parse_ids(path: str, expected_count: int) -> list[str]:
    ids = [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(ids) != expected_count:
        raise RuntimeError(f"expected {expected_count} lead IDs, got {len(ids)}")
    if len(set(ids)) != len(ids):
        raise RuntimeError("lead IDs contain duplicates")
    return ids


def run(lead_id_file: str, expected_count: int, report: str | None = None) -> dict:
    spreadsheet_id = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        raise RuntimeError("OUTREACH_SPREADSHEET_ID is required")

    lead_ids = parse_ids(lead_id_file, expected_count)
    values = get_values(build_service(), spreadsheet_id, QUEUE_SHEET)
    rows = selected_rows(rows_from_values(values), lead_ids)
    clean_rows = [validate_row(row) for row in rows]
    postal_address = load_private_postal_address()
    messages = [(row, build_message(row, postal_address)) for row in clean_rows]

    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        for row, msg in messages:
            append_and_verify(client, folder, msg, row["lead_id"])
    finally:
        try:
            client.logout()
        except Exception:
            pass

    result = {
        "status": "green",
        "count": len(messages),
        "lead_ids": lead_ids,
        "transport": "IMAP_DRAFT_ONLY",
        "smtp_send": "not_available",
    }
    if report:
        Path(report).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lead-id-file", required=True)
    parser.add_argument("--expected-count", required=True, type=int)
    parser.add_argument("--report")
    args = parser.parse_args()
    try:
        result = run(args.lead_id_file, args.expected_count, args.report)
    except Exception as exc:
        print(f"MYHOST_DRAFT_SYNC=blocked detail={exc}")
        return 2
    print(f"MYHOST_DRAFT_SYNC=green count={result['count']} transport=IMAP_DRAFT_ONLY smtp_send=not_available")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
