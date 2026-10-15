"""Write only website-verified, non-suppressed businesses to a PRIVATE sheet tab.

Separate from the unverified Candidates tab and read-only Mijn.Host Draft Queue.
All values are private Google Sheets stringValue cells, never GitHub artifacts/logs.
"""
from __future__ import annotations
import os
import re
from urllib.parse import quote

from draft_queue_readonly import valid_general_email
from new_leads import safe_hint
from private_candidate_handoff import authorized_writer, SHEET_ID

TAB = "Approved"
TAB_ID = 723410156
COLS = ("run_id", "company", "website", "email", "source_url",
        "cluster", "branche_meervoud", "greeting", "status")
STATUS = "verified_website_and_email"
MAX = 100


def values(approved, run_id):
    if not isinstance(approved, list) or len(approved) > MAX:
        raise RuntimeError("approved_handoff_invalid_count")
    if not re.fullmatch(r"[0-9]{1,20}", str(run_id)):
        raise RuntimeError("approved_handoff_invalid_run")
    rows = [list(COLS)]
    for row in approved:
        if not isinstance(row, dict):
            raise RuntimeError("approved_handoff_invalid_row")
        name = str(row.get("company") or "").strip()
        website = str(row.get("website") or "").strip()
        email = str(row.get("email") or "").strip().lower()
        source = str(row.get("source_url") or "").strip()
        cluster = str(row.get("cluster") or "")
        plural = str(row.get("branche_meervoud") or "").strip()
        greeting = str(row.get("greeting") or "")
        if (not name or len(name) > 160 or any(ord(c) < 32 for c in name)
                or safe_hint(website) != website or safe_hint(source) != source
                or not valid_general_email(email) or cluster not in "123456"
                or not plural or len(plural) > 80 or
                greeting != ("Hoi," if int(cluster) >= 5 else "Goedendag,")
                or row.get("status") != STATUS):
            raise RuntimeError("approved_handoff_invalid_row")
        rows.append([str(run_id), name, website, email, source,
                     cluster, plural, greeting, STATUS])
    return rows


def store_approved(approved, *, run_id=None, session=None):
    rid = str(run_id or os.getenv("GITHUB_RUN_ID") or "")
    expected = values(approved, rid)
    padded = expected + [[""] * len(COLS) for _ in range(MAX + 1 - len(expected))]
    rows = [{"values": [{"userEnteredValue": {"stringValue": x}} if x else {}
                         for x in row]} for row in padded]
    base = "https://sheets.googleapis.com/v4/spreadsheets/" + SHEET_ID
    conn = session if session is not None else authorized_writer()
    try:
        response = conn.post(base + ":batchUpdate", json={"requests": [{
            "updateCells": {
                "range": {"sheetId": TAB_ID, "startRowIndex": 0,
                          "endRowIndex": MAX + 1, "startColumnIndex": 0,
                          "endColumnIndex": len(COLS)},
                "rows": rows, "fields": "userEnteredValue"
            }
        }]}, timeout=30)
        if response.status_code != 200:
            raise RuntimeError("approved_handoff_write_failed")
        got = conn.get(base + "/values/" + quote("Approved!A1:I101", safe=""),
                       timeout=20)
        if got.status_code != 200 or got.json().get("values") != expected:
            raise RuntimeError("approved_handoff_readback_failed")
        return len(approved)
    except Exception:
        raise RuntimeError("approved_handoff_unverified") from None
