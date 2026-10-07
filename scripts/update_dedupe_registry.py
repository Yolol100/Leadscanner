#!/usr/bin/env python3
"""Phase 12: append exact review-draft identities to the canonical Google Sheet.

The Sheet remains the single historical suppression source. The write is
fail-closed and only runs after exact IMAP readback has passed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import quote, urlparse

from dedupe_preflight import (
    domains_match,
    normalize_company as canonical_normalize_company,
    normalize_domain as canonical_normalize_domain,
)

HEADERS = [
    "company",
    "website",
    "domain",
    "emails",
    "status",
    "history",
    "lead_ids",
    "last_event_at",
    "sources",
    "exclude_from_new_leads",
]
DEFAULT_SPREADSHEET_ID = "1p4vZnCdcex9zpTAV-ssebXqZcBS2TU6KfXwS-4d2iSI"
DEFAULT_SHEET_NAME = "DedupeRegistry"


def _text(value: object) -> str:
    return str(value or "").strip()


def normalize_company(value: object) -> str:
    return canonical_normalize_company(value)


def normalize_domain(value: object) -> str:
    return canonical_normalize_domain(value)


def split_values(value: object) -> set[str]:
    return {
        part.strip().casefold()
        for part in re.split(r"[;,\n]+", _text(value))
        if part.strip()
    }


def normalize_row(row: list[object]) -> list[str]:
    values = [_text(value) for value in row[: len(HEADERS)]]
    return values + [""] * (len(HEADERS) - len(values))


def row_identity(row: list[object]) -> dict:
    values = normalize_row(row)
    return {
        "company": normalize_company(values[0]),
        "domain": normalize_domain(values[2] or values[1]),
        "emails": split_values(values[3]),
        "lead_ids": split_values(values[6]),
    }


def rows_match(left: list[object], right: list[object]) -> bool:
    a = row_identity(left)
    b = row_identity(right)
    if a["lead_ids"] & b["lead_ids"]:
        return True
    if a["emails"] & b["emails"]:
        return True
    if domains_match(a["domain"], b["domain"]):
        return True
    if a["company"] and a["company"] == b["company"]:
        return True
    return False


def plan_registry_update(readback: dict, current_values: list[list[object]]) -> dict:
    if readback.get("status") != "green":
        raise ValueError("readback_must_be_green")
    if readback.get("automatic_send") is not False:
        raise ValueError("automatic_send_must_be_false")
    if readback.get("registry_headers") != HEADERS:
        raise ValueError("registry_header_contract_mismatch")
    if not current_values or normalize_row(current_values[0]) != HEADERS:
        raise ValueError("live_registry_headers_mismatch")

    existing_rows = [normalize_row(row) for row in current_values[1:] if any(_text(v) for v in row)]
    requested_rows = [normalize_row(row) for row in (readback.get("registry_rows") or [])]
    if len(requested_rows) != int(readback.get("draft_count") or 0):
        raise ValueError("registry_intent_count_mismatch")

    append_rows: list[list[str]] = []
    existing_count = 0
    for row in requested_rows:
        identity = row_identity(row)
        if not any((identity["company"], identity["domain"], identity["emails"], identity["lead_ids"])):
            raise ValueError("registry_intent_without_identity")
        if row[9].casefold() != "true":
            raise ValueError("registry_intent_must_suppress")
        matches = [current for current in existing_rows + append_rows if rows_match(row, current)]
        if matches:
            existing_count += 1
            continue
        append_rows.append(row)

    return {
        "requested_count": len(requested_rows),
        "append_rows": append_rows,
        "append_count": len(append_rows),
        "existing_count": existing_count,
    }


def exact_rows_present(expected_rows: list[list[str]], current_values: list[list[object]]) -> bool:
    normalized = [normalize_row(row) for row in current_values[1:] if any(_text(v) for v in row)]
    for expected in expected_rows:
        expected = normalize_row(expected)
        lead_id = expected[6].casefold()
        matches = [row for row in normalized if lead_id and lead_id in split_values(row[6])]
        if len(matches) != 1 or matches[0] != expected:
            return False
    return True


def _authorized_session():
    raw = (
        os.getenv("LEAD_REGISTRY_SERVICE_ACCOUNT_JSON", "").strip()
        or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    )
    if not raw:
        raise RuntimeError(
            "LEAD_REGISTRY_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_JSON is required for canonical registry writes"
        )
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("LEAD_REGISTRY_SERVICE_ACCOUNT_JSON is invalid JSON") from exc
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError("google-auth is required for canonical registry writes") from exc

    credentials = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return AuthorizedSession(credentials), _text(info.get("client_email"))


def _api_values_url(spreadsheet_id: str, sheet_name: str) -> str:
    range_name = quote(f"{sheet_name}!A:J", safe="")
    return f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range_name}"


def read_live_values(session, spreadsheet_id: str, sheet_name: str) -> list[list[object]]:
    response = session.get(_api_values_url(spreadsheet_id, sheet_name), timeout=20)
    if response.status_code != 200:
        raise RuntimeError(f"registry_read_failed status={response.status_code}")
    payload = response.json()
    values = payload.get("values")
    if not isinstance(values, list):
        raise RuntimeError("registry_read_returned_no_values")
    return values


def append_values(session, spreadsheet_id: str, sheet_name: str, rows: list[list[str]]) -> None:
    if not rows:
        return
    url = (
        _api_values_url(spreadsheet_id, sheet_name)
        + ":append?valueInputOption=RAW&insertDataOption=INSERT_ROWS"
    )
    response = session.post(
        url,
        json={"majorDimension": "ROWS", "values": rows},
        timeout=20,
    )
    if response.status_code not in {200, 201}:
        raise RuntimeError(f"registry_append_failed status={response.status_code}")


def check_registry_access(*, spreadsheet_id: str, sheet_name: str) -> dict:
    session, client_email = _authorized_session()
    current = read_live_values(session, spreadsheet_id, sheet_name)
    if not current or normalize_row(current[0]) != HEADERS:
        raise RuntimeError("live_registry_headers_mismatch")

    header_range = quote(f"{sheet_name}!A1:J1", safe="")
    header_url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{header_range}"
        "?valueInputOption=RAW"
    )
    response = session.put(
        header_url,
        json={"majorDimension": "ROWS", "values": [HEADERS]},
        timeout=20,
    )
    if response.status_code not in {200, 201}:
        raise RuntimeError(f"registry_write_preflight_failed status={response.status_code}")
    confirmed = read_live_values(session, spreadsheet_id, sheet_name)
    if not confirmed or normalize_row(confirmed[0]) != HEADERS:
        raise RuntimeError("registry_write_preflight_readback_mismatch")
    return {
        "schema_version": "leadscanner-dedupe-registry-access/1.0",
        "status": "green",
        "spreadsheet_id": spreadsheet_id,
        "sheet_name": sheet_name,
        "service_account": client_email,
        "write_intent": "validated_before_draft_creation",
        "automatic_send": False,
    }


def update_registry(readback: dict, *, spreadsheet_id: str, sheet_name: str) -> dict:
    if readback.get("status") != "green":
        raise ValueError("readback_must_be_green")
    if readback.get("automatic_send") is not False:
        raise ValueError("automatic_send_must_be_false")
    if readback.get("registry_headers") != HEADERS:
        raise ValueError("registry_header_contract_mismatch")
    registry_rows = readback.get("registry_rows")
    draft_count = readback.get("draft_count")
    if (
        not isinstance(registry_rows, list)
        or isinstance(draft_count, bool)
        or not isinstance(draft_count, int)
        or draft_count < 0
        or len(registry_rows) != draft_count
    ):
        raise ValueError("registry_intent_count_mismatch")

    if draft_count == 0:
        return {
            "schema_version": "leadscanner-dedupe-registry-update/1.0",
            "status": "green",
            "spreadsheet_id": spreadsheet_id,
            "sheet_name": sheet_name,
            "service_account": None,
            "requested_count": 0,
            "appended_count": 0,
            "already_present_count": 0,
            "exact_readback": True,
            "automatic_send": False,
        }
    session, client_email = _authorized_session()
    current = read_live_values(session, spreadsheet_id, sheet_name)
    plan = plan_registry_update(readback, current)
    append_values(session, spreadsheet_id, sheet_name, plan["append_rows"])
    after = read_live_values(session, spreadsheet_id, sheet_name)
    if not exact_rows_present(plan["append_rows"], after):
        raise RuntimeError("registry_exact_readback_mismatch_after_append")

    return {
        "schema_version": "leadscanner-dedupe-registry-update/1.0",
        "status": "green",
        "spreadsheet_id": spreadsheet_id,
        "sheet_name": sheet_name,
        "service_account": client_email,
        "requested_count": plan["requested_count"],
        "appended_count": plan["append_count"],
        "already_present_count": plan["existing_count"],
        "exact_readback": True,
        "automatic_send": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--readback")
    parser.add_argument("--output", required=True)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument(
        "--spreadsheet-id",
        default=os.getenv("LEAD_REGISTRY_SPREADSHEET_ID", DEFAULT_SPREADSHEET_ID),
    )
    parser.add_argument(
        "--sheet-name",
        default=os.getenv("LEAD_REGISTRY_SHEET_NAME", DEFAULT_SHEET_NAME),
    )
    args = parser.parse_args()

    if args.check_only:
        result = check_registry_access(
            spreadsheet_id=args.spreadsheet_id,
            sheet_name=args.sheet_name,
        )
    else:
        if not args.readback:
            raise SystemExit("--readback is required unless --check-only is used")
        readback = json.loads(Path(args.readback).read_text(encoding="utf-8"))
        result = update_registry(
            readback,
            spreadsheet_id=args.spreadsheet_id,
            sheet_name=args.sheet_name,
        )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.check_only:
        print("DEDUPE_REGISTRY_ACCESS=green write_intent=validated_before_draft_creation")
    else:
        print(
            "DEDUPE_REGISTRY_UPDATE=green "
            f"requested={result['requested_count']} appended={result['appended_count']} "
            f"already_present={result['already_present_count']} exact_readback=true"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
