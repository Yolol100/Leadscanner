"""Disposable v2 backfill, no plaintext writes and no provider mutations.

Strong 256-bit independent HMAC key lives only in separately private Google
Sheets vault. Public canonical Sheet stores keyed digest tokens only. Re-run
is idempotent; never retry a write with an uncertain outcome in one run.
"""
from __future__ import annotations

import json
import os
import secrets
import sys

from _once_profile_historical_unverified_domains import (
    candidate_domain, official, source,
)
from dedupe_preflight import normalize_email, match_candidate
from historical_suppression import hmac_key, token as old_token, validate_rows as old_validate
from historical_v2 import (
    HEADERS, KEY_VERSION, SOURCE_TOTAL, TAB_NAME, VAULT_HEADERS,
    VAULT_SHEET_ID, VAULT_TAB, VERSION, key_from_vault, key_check,
    parse_rows, row_for_match, token,
)
from update_dedupe_registry import (
    DEFAULT_SPREADSHEET_ID, _authorized_session, read_live_values, append_values,
)


def get_or_create_key(session):
    values = read_live_values(session, VAULT_SHEET_ID, VAULT_TAB)
    if len(values) == 2:
        return key_from_vault(values)
    if values != [VAULT_HEADERS]:
        raise RuntimeError("private_hmac_key_vault_unexpected_state")
    random_key = secrets.token_hex(32)
    # Never retry uncertain writes in this process; a subsequent run
    # must re-read the vault and use any already-committed value.
    append_values(
        session, VAULT_SHEET_ID, VAULT_TAB,
        [[KEY_VERSION, random_key, "active"]],
    )
    after = read_live_values(session, VAULT_SHEET_ID, VAULT_TAB)
    if after != [VAULT_HEADERS, [KEY_VERSION, random_key, "active"]]:
        raise RuntimeError("private_hmac_key_exact_readback_failed")
    return key_from_vault(after)


def build_expected(items, key):
    verified, corporate, unknown = 0, 0, 0
    rows = []
    for item in items:
        source_id = str(item["id"]).lower()
        email = normalize_email(item.get("email"))
        first_party = official(item)
        candidate = candidate_domain(email) if not first_party else ""
        if first_party:
            verified += 1
        elif candidate:
            corporate += 1
        else:
            unknown += 1
        rows.append([
            VERSION, key_check(key), token(key, "source", source_id),
            token(key, "email", email),
            token(key, "official", first_party) if first_party else "",
            token(key, "corporate", candidate) if candidate else "",
        ])
    if (len(rows), verified, corporate, unknown) != (1128, 914, 146, 68):
        raise RuntimeError("historical_v2_classification_baseline_changed")
    if len({r[2] for r in rows}) != SOURCE_TOTAL:
        raise RuntimeError("historical_v2_nonunique_source")
    return rows


def run():
    # Validate complete old source before any state mutation. The original
    # HMAC tab also acts as independent source-identity continuity evidence.
    items = source()
    sheets, _account = _authorized_session()
    v1key = hmac_key()
    old_values = read_live_values(sheets, DEFAULT_SPREADSHEET_ID, "HistoricalHmac")
    old = old_validate(old_values, v1key, complete=True)
    if any(
        old["by_source"].get(old_token(v1key, "source", str(item["id"]).lower())) is None
        for item in items
    ):
        raise RuntimeError("original_historical_identities_changed")
    key = get_or_create_key(sheets)
    expected = build_expected(items, key)

    appended = 0
    existing = 0
    for offset in range(0, SOURCE_TOTAL, 100):
        chunk = expected[offset:offset + 100]
        before = parse_rows(
            read_live_values(sheets, DEFAULT_SPREADSHEET_ID, TAB_NAME),
            key, complete=False,
        )
        absent = []
        for record in chunk:
            actual = before["by_source"].get(record[2])
            if actual is None:
                absent.append(record)
            elif actual != record:
                raise RuntimeError("historical_v2_conflicting_earlier_record")
        if absent:
            append_values(sheets, DEFAULT_SPREADSHEET_ID, TAB_NAME, absent)
        after = parse_rows(
            read_live_values(sheets, DEFAULT_SPREADSHEET_ID, TAB_NAME),
            key, complete=False,
        )
        if any(after["by_source"].get(row[2]) != row for row in chunk):
            raise RuntimeError("historical_v2_batch_exact_readback_failed")
        appended += len(absent)
        existing += len(chunk) - len(absent)
        print(
            "HISTORICAL_V2_BATCH=green "
            + f"offset={offset} size={len(chunk)} new={len(absent)} "
            + f"existing={len(chunk)-len(absent)} total={after['count']}"
        )

    final = parse_rows(
        read_live_values(sheets, DEFAULT_SPREADSHEET_ID, TAB_NAME),
        key, complete=True,
    )
    if any(final["by_source"].get(row[2]) != row for row in expected):
        raise RuntimeError("historical_v2_final_exact_contents_changed")

    matcher = row_for_match(final, key)
    for item in items:
        matched = match_candidate({"email": item["email"]}, [matcher])
        if not matched or "historical_v2_email" not in matched["matched_by"]:
            raise RuntimeError("historical_v2_source_email_missing")
        first_party = official(item)
        corp = candidate_domain(item["email"]) if not first_party else ""
        domain = first_party or corp
        if domain and not match_candidate({"official_domain": domain}, [matcher]):
            raise RuntimeError("historical_v2_domain_not_enforced")
    return {
        "status": "green",
        "source_count": SOURCE_TOTAL,
        "full_email_protection": final["count"],
        "verified_official_domain_protection": final["official_count"],
        "conservative_custom_mail_domain_protection": final["corporate_count"],
        "unattributable_shared_provider_count": 68,
        "appended": appended,
        "existing": existing,
        "chunk_size": 100,
        "plaintext_written": False,
        "provider_modified": False,
        "emails_sent": 0,
        "google_service_account_key_independent": True,
    }


if __name__ == "__main__":
    try:
        result = run()
    except Exception:
        print("HISTORICAL_V2=failed private_details_suppressed")
        sys.exit(1)
    print("HISTORICAL_V2=green " + json.dumps(result, sort_keys=True))
