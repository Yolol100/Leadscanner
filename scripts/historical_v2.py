"""Independent-key historical suppression with strict complete-state readback.

Only opaque HMAC values live in the public Google Sheets workbook.
The random 256-bit key is stored in a separate, PRIVATE Google Sheets vault
granted only to its owner and the Sheets service account. A Google service
account credential rotation does not change the HMAC key.
"""
from __future__ import annotations

import hashlib
import hmac
import re

VERSION = "hmac-sha256-v2"
TAB_NAME = "HistoricalHmacV2"
VAULT_SHEET_ID = "1wgSYVjxoetEg9v7N3F6s1_43UGDHEHET1F02vdMqas4"
VAULT_TAB = "Keys"
SOURCE_TOTAL = 1128
HEADERS = [
    "version", "key_check", "source_id_token", "email_token",
    "official_domain_token", "corporate_mail_domain_token",
]
VAULT_HEADERS = ["version", "key_hex", "status"]
KEY_VERSION = "leadscanner-independent-hmac-v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
CHECK = "Leadscanner/HMACv2/independent-key-check"


def derive_key(raw_hex: str) -> bytes:
    if not isinstance(raw_hex, str) or not HEX64.fullmatch(raw_hex):
        raise RuntimeError("historical_v2_vault_key_invalid")
    return hmac.new(
        bytes.fromhex(raw_hex), b"Leadscanner/historical-suppression/v2",
        hashlib.sha256,
    ).digest()


def key_from_vault(values: list[list[object]]) -> bytes:
    if (not isinstance(values, list) or len(values) != 2
            or values[0] != VAULT_HEADERS
            or not isinstance(values[1], list) or len(values[1]) != 3
            or values[1][0] != KEY_VERSION or values[1][2] != "active"):
        raise RuntimeError("historical_v2_vault_unavailable_or_modified")
    return derive_key(str(values[1][1]))


def token(key: bytes, kind: str, value: str) -> str:
    if kind not in {"check", "email", "official", "corporate", "source"} or not value:
        raise ValueError("historical_v2_token_input_invalid")
    return hmac.new(
        key, (kind + "\0" + value).encode("utf-8"), hashlib.sha256
    ).hexdigest()


def key_check(key: bytes) -> str:
    return token(key, "check", CHECK)


def parse_rows(values: list[list[object]], key: bytes, *, complete: bool) -> dict:
    if not isinstance(values, list) or not values or values[0] != HEADERS:
        raise RuntimeError("historical_v2_headers_missing")
    marker = key_check(key)
    source_index, emails, official, corporate = {}, set(), set(), set()
    off_count = corp_count = 0
    for line in values[1:]:
        if not isinstance(line, list) or len(line) > 6:
            raise RuntimeError("historical_v2_row_shape_invalid")
        if not any(str(x or "").strip() for x in line):
            continue
        row = [str(x or "").strip() for x in line] + [""] * (6 - len(line))
        version, check, source_id, email, official_domain, corp_domain = row
        if (
            version != VERSION or check != marker or
            not HEX64.fullmatch(source_id) or not HEX64.fullmatch(email) or
            (official_domain and not HEX64.fullmatch(official_domain)) or
            (corp_domain and not HEX64.fullmatch(corp_domain)) or
            (official_domain and corp_domain)
        ):
            raise RuntimeError("historical_v2_bad_hash_key_or_domain")
        if source_id in source_index or email in emails:
            raise RuntimeError("historical_v2_duplicate_identity")
        source_index[source_id] = row
        emails.add(email)
        if official_domain:
            official.add(official_domain)
            off_count += 1
        if corp_domain:
            corporate.add(corp_domain)
            corp_count += 1
        if len(source_index) > SOURCE_TOTAL:
            raise RuntimeError("historical_v2_source_overflow")
    if complete and (
        len(source_index) != SOURCE_TOTAL or off_count != 914 or corp_count != 146
    ):
        raise RuntimeError("historical_v2_incomplete")
    return {
        "by_source": source_index,
        "emails": emails,
        "official": official,
        "corporate": corporate,
        "count": len(source_index),
        "official_count": off_count,
        "corporate_count": corp_count,
    }


def row_for_match(parsed: dict, key: bytes) -> dict:
    return {
        "identity": {"company": "", "domains": set(), "emails": set(), "lead_ids": set()},
        "v2_key": key, "v2_emails": parsed["emails"],
        "v2_official": parsed["official"], "v2_corporate": parsed["corporate"],
        "status": "historical_v2_suppression", "row_number": 0,
    }


def match(identity: dict, record: dict) -> list[str]:
    key = record.get("v2_key")
    if not isinstance(key, bytes):
        return []
    matched = []
    if any(token(key, "email", e) in record["v2_emails"] for e in identity["emails"]):
        matched.append("historical_v2_email")
    for domain in identity["domains"]:
        parts = domain.split(".")
        variants = [domain] + [
            ".".join(parts[i:]) for i in range(1, len(parts) - 1)
        ]
        if any(token(key, "official", d) in record["v2_official"] for d in variants):
            matched.append("historical_v2_official_domain")
            break
        if any(token(key, "corporate", d) in record["v2_corporate"] for d in variants):
            matched.append("historical_v2_corporate_mail_domain")
            break
    return matched


def read_production_state(session, read_live_values, spreadsheet_id: str):
    """Read vault and public tokens with the same authorized Sheets client."""
    key = key_from_vault(read_live_values(session, VAULT_SHEET_ID, VAULT_TAB))
    public = read_live_values(session, spreadsheet_id, TAB_NAME)
    parsed = parse_rows(public, key, complete=True)
    return row_for_match(parsed, key)
