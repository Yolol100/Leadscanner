#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build

QUEUE_RANGE = "OutreachQueue!A:AC"
REQUIRED_HEADERS = {
    "lead_id", "company", "email", "country", "status", "sent_at", "message_id"
}


def service():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise SystemExit("GOOGLE_SERVICE_ACCOUNT_JSON is required")
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def rows(spreadsheet_id: str):
    values = service().spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=QUEUE_RANGE
    ).execute().get("values", [])
    if not values:
        raise SystemExit("OutreachQueue is empty")
    headers = [str(x).strip() for x in values[0]]
    missing = REQUIRED_HEADERS.difference(headers)
    if missing:
        raise SystemExit("OutreachQueue missing headers: " + ", ".join(sorted(missing)))
    for raw in values[1:]:
        padded = list(raw) + [""] * (len(headers) - len(raw))
        yield dict(zip(headers, padded))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spreadsheet-id", required=True)
    parser.add_argument("--country", default="US")
    parser.add_argument("--timezone", default="Europe/Amsterdam")
    parser.add_argument("--github-output", default="")
    args = parser.parse_args()

    country = args.country.strip().upper()
    today = datetime.now(ZoneInfo(args.timezone)).date().isoformat()
    all_rows = list(rows(args.spreadsheet_id))

    approved = [r for r in all_rows if str(r.get("status", "")).strip().casefold() == "approved"]
    approved_country = [r for r in approved if str(r.get("country", "")).strip().upper() == country]
    approved_other = [r for r in approved if str(r.get("country", "")).strip().upper() != country]

    sent_today = []
    for row in all_rows:
        if str(row.get("country", "")).strip().upper() != country:
            continue
        sent_at = str(row.get("sent_at", "")).strip()
        message_id = str(row.get("message_id", "")).strip()
        if sent_at.startswith(today) and message_id:
            sent_today.append(row)

    payload = {
        "date": today,
        "country": country,
        "sent_today": len(sent_today),
        "approved_country": len(approved_country),
        "approved_other": len(approved_other),
        "manual_review_country": sum(
            1 for r in all_rows
            if str(r.get("country", "")).strip().upper() == country
            and str(r.get("status", "")).strip().casefold() == "manual_review"
        ),
    }
    print(json.dumps(payload, sort_keys=True))

    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            for key, value in payload.items():
                handle.write(f"{key}={value}\n")

    # This controller is intentionally US-only. A non-US approved row could be
    # selected by the shared sender workflow, so stop rather than broadening scope.
    if approved_other:
        print(f"CAMPAIGN_STATE=blocked approved_non_{country}={len(approved_other)}")
        return 2
    print("CAMPAIGN_STATE=green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
