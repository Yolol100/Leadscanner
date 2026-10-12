"""Temporary, bounded historical exclusion backfill. REMOVE after green.

Read 1,128 source identities; append ONLY keyed HMACs to the existing workbook's
separate tab in 100-contact chunks. No private names/emails/domains/IDs in public
logs, Sheets, artifacts, errors or Git. No provider writes or mail transmission.
Safe to resume: reconcile exact IDs and contents before every append.
"""
from __future__ import annotations

import json
import os
import re
import sys

import requests

from dedupe_preflight import normalize_domain, normalize_email, match_candidate
from historical_suppression import (
    HEADERS, SOURCE_TOTAL, TAB_NAME, VERSION, hmac_key, key_check,
    suppression_row, token, validate_rows,
)
from update_dedupe_registry import (
    DEFAULT_SPREADSHEET_ID, _authorized_session, read_live_values, append_values,
)

LIST_ID = "24deb187-59e0-43b5-86b8-fe37a7b21e2a"
URL = "https://api.instantly.ai/api/v2/leads/list"
UUID = re.compile(r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$")
SIZE = 100


def _get_source() -> list[dict]:
    key = os.environ.get("INSTANTLY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("migration_source_key_unavailable")
    source = []
    seen_ids, seen_emails, cursors = set(), set(), set()
    cursor = ""
    with requests.Session() as session:
        for _page in range(25):
            args = {"list_id": LIST_ID, "limit": SIZE}
            if cursor:
                args["starting_after"] = cursor
            response = session.post(URL, headers={
                "Authorization": "Bearer " + key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            }, json=args, timeout=30)
            if response.status_code != 200:
                raise RuntimeError("migration_source_read_failed")
            result = response.json()
            items = result.get("items") if isinstance(result, dict) else None
            if not isinstance(items, list):
                raise RuntimeError("migration_source_page_invalid")
            for row in items:
                if not isinstance(row, dict) or row.get("list_id") != LIST_ID:
                    raise RuntimeError("migration_source_identity_invalid")
                lead_id = str(row.get("id") or "").strip().lower()
                email = normalize_email(row.get("email"))
                if (not UUID.fullmatch(lead_id) or not email
                        or lead_id in seen_ids or email in seen_emails):
                    raise RuntimeError("migration_source_invalid_or_duplicate")
                seen_ids.add(lead_id)
                seen_emails.add(email)
                source.append(row)
            cursor_next = str(result.get("next_starting_after") or "").strip()
            if not cursor_next:
                break
            if cursor_next == cursor or cursor_next in cursors or not items:
                raise RuntimeError("migration_source_cursor_invalid")
            cursors.add(cursor_next)
            cursor = cursor_next
        else:
            raise RuntimeError("migration_source_page_limit")
    if len(source) != SOURCE_TOTAL:
        raise RuntimeError("migration_source_count_changed")
    return sorted(source, key=lambda row: str(row["id"]).lower())


def _confirmed_official_domain(item: dict) -> str:
    vals = item.get("payload")
    if not isinstance(vals, dict):
        vals = item.get("custom_variables")
    if not isinstance(vals, dict):
        return ""
    for prefix in ("leadscanner_site_refresh_", "leadscanner_site_candidate_"):
        if str(vals.get(prefix + "source_type") or "") != "official_site":
            continue
        domain = normalize_domain(vals.get(prefix + "official_domain"))
        evidence = normalize_domain(vals.get(prefix + "evidence_url"))
        if domain and evidence == domain and "." in domain and domain not in {"com", "org", "nl"}:
            return domain
    return ""


def _expected_rows(source: list[dict], secret: bytes) -> list[list[str]]:
    check = key_check(secret)
    expected = []
    for row in source:
        lead_id = str(row["id"]).lower()
        email = normalize_email(row.get("email"))
        domain = _confirmed_official_domain(row)
        expected.append([
            VERSION, check,
            token(secret, "source", lead_id),
            token(secret, "email", email),
            token(secret, "domain", domain) if domain else "",
        ])
    if len(set(row[2] for row in expected)) != SOURCE_TOTAL:
        raise RuntimeError("migration_hash_identity_collision")
    return expected


def run() -> dict:
    secret = hmac_key()
    source = _get_source()  # complete verified provider inventory before writes
    expected = _expected_rows(source, secret)
    sheets, _client_email = _authorized_session()
    inserted_total = 0
    previous_total = 0

    for start in range(0, SOURCE_TOTAL, SIZE):
        chunk = expected[start:start + SIZE]
        before = validate_rows(
            read_live_values(sheets, DEFAULT_SPREADSHEET_ID, TAB_NAME),
            secret, complete=False,
        )
        missing = []
        for row in chunk:
            old = before["by_source"].get(row[2])
            if old is None:
                missing.append(row)
            elif old != row:
                raise RuntimeError("migration_conflicting_existing_row")
        # This POST may have an uncertain result on transport failure.
        # Never retry blindly: exit, re-read on the next full run, append
        # ONLY identities not found with exact contents.
        if missing:
            append_values(sheets, DEFAULT_SPREADSHEET_ID, TAB_NAME, missing)
        after = validate_rows(
            read_live_values(sheets, DEFAULT_SPREADSHEET_ID, TAB_NAME),
            secret, complete=False,
        )
        if any(after["by_source"].get(row[2]) != row for row in chunk):
            raise RuntimeError("migration_exact_chunk_readback_failed")
        if after["count"] < before["count"] or after["count"] > SOURCE_TOTAL:
            raise RuntimeError("migration_provider_unexpected_count")
        inserted_total += len(missing)
        previous_total += len(chunk) - len(missing)
        print("HISTORICAL_HASH_BATCH=green "
              + f"offset={start} size={len(chunk)} new={len(missing)} "
              + f"existing={len(chunk)-len(missing)} verified={after['count']}")

    final = validate_rows(
        read_live_values(sheets, DEFAULT_SPREADSHEET_ID, TAB_NAME),
        secret, complete=True,
    )
    if any(final["by_source"].get(row[2]) != row for row in expected):
        raise RuntimeError("migration_final_contents_mismatch")

    # Prove the actual production dedupe matcher blocks all historical emails.
    registry_row = suppression_row(final, secret)
    for item in source:
        match = match_candidate({"email": item["email"]}, [registry_row])
        if not match or "historical_email" not in match["matched_by"]:
            raise RuntimeError("migration_production_matcher_failed")
    return {
        "status": "green", "source_count": SOURCE_TOTAL,
        "opaque_suppression_count": final["count"],
        "new": inserted_total, "already_exact": previous_total,
        "batch_limit": SIZE, "plaintext_contacts_written": False,
        "source_modified": False, "email_sent": False,
    }


if __name__ == "__main__":
    try:
        result = run()
    except Exception:
        print("HISTORICAL_HASH_IMPORT=failed private_details_suppressed")
        sys.exit(1)
    print("HISTORICAL_HASH_IMPORT=green " + json.dumps(result, sort_keys=True))
