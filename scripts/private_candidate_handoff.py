"""Private, one-page handoff of Overture company hints; never publish identities.

The sheet is a temporary bridge from Leadscanner discovery to the existing
Leads Skill, NOT a CRM and NOT a source of verified email addresses.
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import quote

from new_leads import safe_hint

SHEET_ID = "13dLUKiX3mWjPWly_UPJFYolOcLc2JBD7Cxv2QBHXRGM"
SHEET_TAB = "Candidates"
TAB_ID = 571812143
COLUMNS = ("run_id", "company", "website_hint", "status")
MAX_CANDIDATES = 100
ROWS = MAX_CANDIDATES + 1
STATUS = "requires_official_site_verification"


def authorized_writer():
    raw = (os.getenv("LEAD_REGISTRY_SERVICE_ACCOUNT_JSON", "").strip()
           or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip())
    if not raw:
        raise RuntimeError("private_handoff_credentials_missing")
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
        info = json.loads(raw)
        if info.get("type") != "service_account":
            raise ValueError("invalid credential")
        credentials = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        return AuthorizedSession(credentials)
    except Exception:
        raise RuntimeError("private_handoff_auth_invalid") from None


def _values(candidates: list[dict], run_id: str) -> list[list[str]]:
    if not isinstance(candidates, list) or len(candidates) > MAX_CANDIDATES:
        raise RuntimeError("private_handoff_size_invalid")
    if not re.fullmatch(r"[0-9]{1,20}", run_id):
        raise RuntimeError("private_handoff_run_id_invalid")
    content = [list(COLUMNS)]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise RuntimeError("private_handoff_row_invalid")
        company = str(candidate.get("company") or "").strip()
        website = str(candidate.get("website_hint") or "").strip()
        if (not company or len(company) > 160
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in company)
                or not safe_hint(website) == website
                or candidate.get("status") != STATUS):
            raise RuntimeError("private_handoff_row_invalid")
        content.append([run_id, company, website, STATUS])
    return content


def store_candidates(candidates: list[dict], *, run_id: str | None = None,
                     session=None) -> int:
    """Replace last run, clear stale entries and verify exact private readback."""
    rid = str(run_id or os.getenv("GITHUB_RUN_ID") or "")
    visible = _values(candidates, rid)
    padded = visible + [["", "", "", ""] for _ in range(ROWS - len(visible))]
    # For stale rows, absent userEnteredValue deliberately clears the previous
    # cell. A submitted company string is never a formula.
    payload_rows = [
        {"values": [
            {"userEnteredValue": {"stringValue": value}} if value else {}
            for value in row
        ]} for row in padded
    ]
    base = "https://sheets.googleapis.com/v4/spreadsheets/" + SHEET_ID
    session = session if session is not None else authorized_writer()
    try:
        response = session.post(base + ":batchUpdate", json={"requests": [{
            "updateCells": {
                "range": {
                    "sheetId": TAB_ID,
                    "startRowIndex": 0,
                    "endRowIndex": ROWS,
                    "startColumnIndex": 0,
                    "endColumnIndex": len(COLUMNS)
                },
                "rows": payload_rows,
                "fields": "userEnteredValue"
            }
        }]}, timeout=30)
        if response.status_code != 200:
            raise RuntimeError("write_failed")
        read_url = base + "/values/" + quote(SHEET_TAB + "!A1:D101", safe="")
        readback = session.get(read_url, timeout=20)
        if readback.status_code != 200:
            raise RuntimeError("read_failed")
        received = readback.json().get("values")
        if received != visible:
            raise RuntimeError("mismatch")
        return len(candidates)
    except Exception:
        raise RuntimeError("private_handoff_unverified") from None
