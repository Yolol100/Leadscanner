"""Opaque, keyed historical suppression inside the existing dedupe workbook.

The workbook and GitHub source may stay public. No plaintext historical
addresses, domains, IDs or HMAC secret are persisted. The key is derived with
domain separation from the EXISTING Sheets service-account secret. Rotating
that private key requires an explicit historical re-key; fail closed otherwise.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re

TAB_NAME = "HistoricalHmac"
VERSION = "hmac-sha256-v1"
SOURCE_TOTAL = 1128
HEADERS = ["version", "key_check", "source_id_token", "email_token", "official_domain_token"]
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DOMAIN_LABEL = b"Leadscanner/historical-dedupe/key-derivation/v1"
CHECK_LABEL = "Leadscanner-history-verification"


def hmac_key() -> bytes:
    raw = (os.getenv("LEAD_REGISTRY_SERVICE_ACCOUNT_JSON") or
           os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or "").strip()
    if not raw:
        raise RuntimeError("historical_suppression_service_account_missing")
    try:
        info = json.loads(raw)
    except (ValueError, TypeError):
        raise RuntimeError("historical_suppression_service_account_invalid") from None
    private_key = info.get("private_key") if isinstance(info, dict) else None
    if not isinstance(private_key, str) or not private_key.startswith("-----BEGIN PRIVATE KEY-----"):
        raise RuntimeError("historical_suppression_private_key_unavailable")
    # Domain-separated HMAC key, not a public/unsalted digest of addresses.
    return hmac.new(private_key.encode("utf-8"), DOMAIN_LABEL, hashlib.sha256).digest()


def token(key: bytes, kind: str, value: str) -> str:
    if kind not in {"email", "domain", "source", "check"}:
        raise ValueError("historical_suppression_token_type")
    if not isinstance(value, str) or not value:
        raise ValueError("historical_suppression_empty_token_value")
    return hmac.new(key, (kind + "\0" + value).encode("utf-8"), hashlib.sha256).hexdigest()


def key_check(key: bytes) -> str:
    return token(key, "check", CHECK_LABEL)


def validate_rows(values: list[list[object]], key: bytes, *, complete: bool) -> dict:
    """Strictly validate the public tab without echoing its values."""
    if not isinstance(values, list) or not values or values[0] != HEADERS:
        raise RuntimeError("historical_suppression_headers_changed_or_missing")
    marker = key_check(key)
    indexed = {}
    emails = set()
    domains = set()
    for row in values[1:]:
        if not isinstance(row, list):
            raise RuntimeError("historical_suppression_row_invalid")
        if not any(str(v).strip() for v in row):
            continue
        if len(row) > len(HEADERS):
            raise RuntimeError("historical_suppression_unexpected_columns")
        fields = [str(v or "").strip() for v in row] + [""] * (len(HEADERS) - len(row))
        version, found_marker, source_id, email, domain = fields
        if (version != VERSION or found_marker != marker or not HEX64.fullmatch(source_id)
                or not HEX64.fullmatch(email) or (domain and not HEX64.fullmatch(domain))):
            raise RuntimeError("historical_suppression_hash_or_key_mismatch")
        if source_id in indexed or email in emails:
            raise RuntimeError("historical_suppression_duplicate_record")
        indexed[source_id] = fields
        emails.add(email)
        if domain:
            domains.add(domain)
        if len(indexed) > SOURCE_TOTAL:
            raise RuntimeError("historical_suppression_exceeds_source")
    if complete and len(indexed) != SOURCE_TOTAL:
        raise RuntimeError("historical_suppression_incomplete")
    return {"by_source": indexed, "emails": emails, "domains": domains, "count": len(indexed)}


def suppression_row(parsed: dict, key: bytes) -> dict:
    """A single in-memory token set compatible with ordinary registry rows."""
    return {
        "identity": {"company": "", "domains": set(), "emails": set(), "lead_ids": set()},
        "hmac_key": key,
        "hmac_emails": parsed["emails"],
        "hmac_domains": parsed["domains"],
        "status": "historical_suppression",
        "row_number": 0,
    }


def email_or_domain_is_suppressed(identity: dict, row: dict) -> list[str]:
    key = row.get("hmac_key")
    if not isinstance(key, bytes):
        return []
    checks = []
    for email in identity["emails"]:
        if token(key, "email", email) in row["hmac_emails"]:
            checks.append("historical_email")
            break
    for domain in identity["domains"]:
        labels = domain.split(".")
        # Exact host and child hosts of a verified original company domain.
        variants = [domain] + [
            ".".join(labels[i:]) for i in range(1, len(labels) - 1)
        ]
        if any(token(key, "domain", part) in row["hmac_domains"] for part in variants):
            checks.append("historical_domain")
            break
    return checks
