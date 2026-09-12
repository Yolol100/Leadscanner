from __future__ import annotations

import argparse
import json
import os
import re

import outreach_queue_imap_draft_sync as base
from outreach_queue_imap_draft import rows_from_values

LEAD_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,180}$")
_SELECTED_IDS: tuple[str, ...] = ()


def _load_ids(path: str, expected_count: int) -> tuple[str, ...]:
    if not path:
        raise RuntimeError("lead-id file is required")
    with open(path, encoding="utf-8") as handle:
        ids = tuple(line.strip() for line in handle if line.strip())
    if len(ids) != expected_count:
        raise RuntimeError(f"expected {expected_count} lead IDs; found {len(ids)}")
    if len(set(ids)) != len(ids):
        raise RuntimeError("lead-id file contains duplicate lead IDs")
    invalid = [lead_id for lead_id in ids if not LEAD_ID_RE.fullmatch(lead_id)]
    if invalid:
        raise RuntimeError("lead-id file contains unsupported IDs")
    return ids


def _selected_target_rows(values: list[list[str]], _prefix: str, expected_count: int) -> list[dict[str, str]]:
    all_rows = rows_from_values(values)
    by_id: dict[str, dict[str, str]] = {}
    for row in all_rows:
        lead_id = (row.get("lead_id") or "").strip()
        if lead_id:
            if lead_id in by_id:
                raise RuntimeError(f"OutreachQueue contains duplicate lead_id: {lead_id}")
            by_id[lead_id] = row

    missing = [lead_id for lead_id in _SELECTED_IDS if lead_id not in by_id]
    if missing:
        raise RuntimeError("selected lead IDs missing from OutreachQueue: " + ", ".join(missing))

    rows = [by_id[lead_id] for lead_id in _SELECTED_IDS]
    if len(rows) != expected_count:
        raise RuntimeError(f"expected {expected_count} selected queue rows; found {len(rows)}")

    recipients = [base._normalize_email(row.get("email", "")) for row in rows]
    if any(not recipient for recipient in recipients):
        raise RuntimeError("selected queue rows contain a blank recipient email")
    if len(set(recipients)) != len(recipients):
        raise RuntimeError("selected queue rows contain duplicate recipient emails")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize an explicit set of OutreachQueue rows to mijn.host IMAP Drafts")
    parser.add_argument("--lead-id-file", required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    if args.expected_count < 1 or args.expected_count > 100:
        print("MYHOST_SELECTED_DRAFT_SYNC=blocked detail=expected count must be between 1 and 100 smtp_send=not_invoked")
        return 2

    global _SELECTED_IDS
    try:
        _SELECTED_IDS = _load_ids(args.lead_id_file, args.expected_count)
        base._target_rows = _selected_target_rows
        result = base.sync_queue_drafts(
            lead_prefix="selected-explicit-ids",
            expected_count=args.expected_count,
            spreadsheet_id=os.getenv("OUTREACH_SPREADSHEET_ID", ""),
            apply=args.apply,
            report_path=args.report,
        )
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"MYHOST_SELECTED_DRAFT_SYNC=blocked detail={exc} smtp_send=not_invoked")
        return 2

    status = result.get("status", "blocked")
    counts = result.get("counts", {})
    marker = "green" if status == "green" else ("preflight_green" if status == "preflight_green" else "blocked")
    print(
        f"MYHOST_SELECTED_DRAFT_SYNC={marker} target={counts.get('target', 0)} "
        f"create={counts.get('create', 0)} replace={counts.get('replace', 0)} "
        f"unchanged={counts.get('unchanged', 0)} final_readback={counts.get('final_readback', 0)} "
        f"smtp_send=not_invoked"
    )
    return 0 if marker in {"green", "preflight_green"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
