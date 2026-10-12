"""Disposable, read-only source-shape diagnostic for historical records.

Runs only in a protected main-branch job using the pre-existing source secret.
Never print raw provider data, addresses, IDs, hashes, keys or website content.
"""
from __future__ import annotations

from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
import re
import sys

import requests
from cold_stages import valid_email
from dedupe_preflight import normalize_email

LIST_ID = "24deb187-59e0-43b5-86b8-fe37a7b21e2a"
API = "https://api.instantly.ai/api/v2/leads/list"
UUID = re.compile(r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$")
EXPECTED = 1128
OUTPUT_KEYS = (
    "records", "pages", "invalid_rows", "wrong_list", "invalid_source_id",
    "duplicate_source_id", "missing_normalized_email", "duplicate_email",
    "new_lead_email_ineligible", "copy_subject_and_body", "copy_partial",
    "copy_absent", "blocked_status_flag",
    "raw_company_name", "raw_website", "raw_company_domain",
    "payload_company_name", "payload_website", "payload_official_domain",
    "name_hint_resolved", "site_hint_resolved", "site_and_name_resolved",
    "site_without_name", "name_without_site", "neither_name_nor_site",
)
FATAL_KEYS = (
    "invalid_rows", "wrong_list", "invalid_source_id", "duplicate_source_id",
    "missing_normalized_email", "duplicate_email",
)


def classify(records: list[object]) -> Counter:
    """Keep invalid historic acquisition addresses but never skip identities."""
    result = Counter()
    ids, emails = set(), set()
    for row in records:
        result["records"] += 1
        if not isinstance(row, dict):
            result["invalid_rows"] += 1
            continue
        if row.get("list_id") != LIST_ID:
            result["wrong_list"] += 1
        source_id = str(row.get("id") or "").strip().lower()
        if not UUID.fullmatch(source_id):
            result["invalid_source_id"] += 1
        elif source_id in ids:
            result["duplicate_source_id"] += 1
        else:
            ids.add(source_id)
        address = normalize_email(row.get("email"))
        if not address:
            result["missing_normalized_email"] += 1
        elif address in emails:
            result["duplicate_email"] += 1
        else:
            emails.add(address)
        # Discovery eligibility is NOT historical source identity validity.
        if address and not valid_email(address):
            result["new_lead_email_ineligible"] += 1
        if row.get("status") in (-1, -2, -3):
            result["blocked_status_flag"] += 1
        vals = row.get("payload")
        if not isinstance(vals, dict):
            vals = row.get("custom_variables")
        if not isinstance(vals, dict):
            vals = {}
        has_copy = False
        partial_copy = False
        for prefix in ("leadscanner_site_refresh_", "leadscanner_site_candidate_"):
            has_subject = bool(str(vals.get(prefix + "subject") or "").strip())
            has_body = bool(str(vals.get(prefix + "body") or "").strip())
            if has_subject and has_body:
                has_copy = True
            elif has_subject or has_body:
                partial_copy = True
        if str(row.get("company_name") or "").strip():
            result["raw_company_name"] += 1
        if str(row.get("website") or "").strip():
            result["raw_website"] += 1
        if str(row.get("company_domain") or "").strip():
            result["raw_company_domain"] += 1
        if str(vals.get("companyName") or vals.get("company_name") or "").strip():
            result["payload_company_name"] += 1
        if str(vals.get("website") or "").strip():
            result["payload_website"] += 1
        if any(str(vals.get(prefix + "official_domain") or "").strip()
               for prefix in ("leadscanner_site_refresh_", "leadscanner_site_candidate_")):
            result["payload_official_domain"] += 1
        if has_copy:
            result["copy_subject_and_body"] += 1
        elif partial_copy:
            result["copy_partial"] += 1
        else:
            result["copy_absent"] += 1
    return result


def read_source() -> tuple[list[object], int]:
    key = os.getenv("INSTANTLY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("missing_source_access")
    collected, cursors, cursor, pages = [], set(), "", 0
    with requests.Session() as client:
        for _ in range(25):
            payload = {"list_id": LIST_ID, "limit": 100}
            if cursor:
                payload["starting_after"] = cursor
            try:
                response = client.post(API, json=payload, headers={
                    "Authorization": "Bearer " + key,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                }, timeout=30)
            except requests.RequestException:
                raise RuntimeError("source_read_failed") from None
            if response.status_code != 200:
                raise RuntimeError("source_read_failed")
            try:
                result = response.json()
            except ValueError:
                raise RuntimeError("source_page_invalid") from None
            items = result.get("items") if isinstance(result, dict) else None
            if not isinstance(items, list) or len(items) > 100:
                raise RuntimeError("source_page_invalid")
            pages += 1
            collected.extend(items)
            next_cursor = str(result.get("next_starting_after") or "").strip()
            if not next_cursor:
                return collected, pages
            if next_cursor == cursor or next_cursor in cursors or not items:
                raise RuntimeError("source_cursor_invalid")
            cursors.add(next_cursor)
            cursor = next_cursor
        raise RuntimeError("source_page_limit")


def main() -> int:
    try:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rows, pages = read_source()
            result = classify(rows)
            from _once_historical_site_redraft import historical_site, historical_name
            for row in rows:
                site = bool(historical_site(row))
                name = bool(historical_name(row))
                result["site_hint_resolved"] += int(site)
                result["name_hint_resolved"] += int(name)
                result["site_and_name_resolved"] += int(site and name)
                result["site_without_name"] += int(site and not name)
                result["name_without_site"] += int(name and not site)
                result["neither_name_nor_site"] += int(not site and not name)
            result["pages"] = pages
    except Exception as error:
        allowed = {
            "missing_source_access", "source_read_failed", "source_page_invalid",
            "source_cursor_invalid", "source_page_limit",
        }
        stage = str(error) if str(error) in allowed else "unknown_hold"
        print("HISTORICAL_SOURCE_DIAG=red stage=" + stage + " details_suppressed")
        return 1
    safe = {k: int(result[k]) for k in OUTPUT_KEYS}
    safe["expected"] = EXPECTED
    is_valid = result["records"] == EXPECTED and not any(result[k] for k in FATAL_KEYS)
    print("HISTORICAL_SOURCE_DIAG=" + ("green" if is_valid else "hold")
          + " " + json.dumps(safe, sort_keys=True))
    return 0 if is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
