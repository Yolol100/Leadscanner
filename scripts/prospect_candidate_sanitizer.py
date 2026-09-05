#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from typing import Mapping, Sequence

from outreach_sender import build_sheets_service, ensure_expected_headers, get_values, rows_from_values
from prospect_discovery import BoundedHttpClient, DiscoveryError
from prospect_source_semantics import obvious_non_target, source_semantic_target_check

PROSPECT_SHEET = "ProspectCandidates"
PROSPECT_HEADERS = [
    "candidate_id", "discovered_at", "company", "website", "source_url",
    "source_id", "source_type", "country", "matched_terms", "status", "reason",
]
HARD_MAX = 100


def _text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _manufacturing_source(row: Mapping[str, object]) -> bool:
    return "manufactur" in f"{row.get('source_id', '')} {row.get('source_url', '')}".casefold()


def _replace_rows(service, spreadsheet_id: str, rows: Sequence[Mapping[str, object]]) -> None:
    values = [PROSPECT_HEADERS] + [[str(row.get(header, "")) for header in PROSPECT_HEADERS] for row in rows]
    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range=f"'{PROSPECT_SHEET}'!A:K", body={}
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{PROSPECT_SHEET}'!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def sanitize_rows(
    rows: Sequence[dict[str, object]],
    *,
    fetch,
    max_checks: int = HARD_MAX,
) -> tuple[int, int, int]:
    checked = rejected = deferred = 0
    for row in rows:
        if checked >= max_checks:
            break
        if _text(row.get("status")).casefold() == "rejected":
            continue
        company = _text(row.get("company"))
        website = _text(row.get("website"))
        source_id = _text(row.get("source_id"))
        source_url = _text(row.get("source_url"))
        direct_reason = obvious_non_target(company, website)
        if direct_reason:
            row["status"] = "rejected"
            row["reason"] = f"source_semantic_target_policy: {direct_reason}"
            checked += 1
            rejected += 1
            continue
        if not _manufacturing_source(row):
            continue
        checked += 1
        try:
            html = fetch(website)
        except DiscoveryError:
            deferred += 1
            continue
        allowed, reason = source_semantic_target_check(
            source_id=source_id,
            source_url=source_url,
            company=company,
            website=website,
            html=html,
        )
        if not allowed:
            row["status"] = "rejected"
            row["reason"] = f"source_semantic_target_policy: {reason}"
            rejected += 1
    return checked, rejected, deferred


def run() -> int:
    spreadsheet_id = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        raise RuntimeError("OUTREACH_SPREADSHEET_ID is required")
    if not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is required")
    service = build_sheets_service()
    headers, rows = rows_from_values(get_values(service, spreadsheet_id, PROSPECT_SHEET))
    ensure_expected_headers(headers, PROSPECT_HEADERS, PROSPECT_SHEET)
    client = BoundedHttpClient(
        user_agent=os.getenv("PROSPECT_QUALIFICATION_USER_AGENT", "WebactueelQualification/1.0 (+https://andrewbaeten.nl)"),
        timeout=float(os.getenv("PROSPECT_QUALIFICATION_TIMEOUT_SECONDS", "10") or "10"),
        max_bytes=min(max(int(os.getenv("PROSPECT_QUALIFICATION_MAX_BYTES", "524288") or "524288"), 65536), 2097152),
        min_interval=float(os.getenv("PROSPECT_QUALIFICATION_MIN_INTERVAL_SECONDS", "0.5") or "0.5"),
    )
    checked, rejected, deferred = sanitize_rows(rows, fetch=client.fetch_text)
    if rejected:
        _replace_rows(service, spreadsheet_id, rows)
    print(f"PROSPECT_SANITIZER=complete checked={checked} rejected={rejected} deferred={deferred} send_permission=none")
    return 0


def main() -> int:
    try:
        return run()
    except (RuntimeError, ValueError) as exc:
        print(f"PROSPECT_SANITIZER=blocked detail={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
