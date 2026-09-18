from __future__ import annotations

import json
import os
from typing import Iterable

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def build_service():
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is required")
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def get_values(service, spreadsheet_id: str, sheet_name: str) -> list[list[str]]:
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!A:AZ")
        .execute()
    )
    return result.get("values", [])


def rows_from_values(values: list[list[str]]) -> list[dict[str, str]]:
    if not values:
        return []
    headers = [str(v).strip() for v in values[0]]
    rows: list[dict[str, str]] = []
    for raw in values[1:]:
        row = {headers[i]: str(raw[i]).strip() if i < len(raw) else "" for i in range(len(headers)) if headers[i]}
        if any(row.values()):
            rows.append(row)
    return rows


def selected_rows(rows: Iterable[dict[str, str]], lead_ids: list[str]) -> list[dict[str, str]]:
    by_id = {row.get("lead_id", "").strip(): row for row in rows if row.get("lead_id", "").strip()}
    missing = [lead_id for lead_id in lead_ids if lead_id not in by_id]
    if missing:
        raise RuntimeError("Missing lead IDs: " + ", ".join(missing))
    return [by_id[lead_id] for lead_id in lead_ids]
