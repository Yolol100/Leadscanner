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

HISTORY_TAB = "LeadHistory"
HISTORY_COLS = ("first_seen_run", "company", "website", "email",
                "source_url", "status", "draft_id", "recorded_at")


def _read_history(conn, base):
    response = conn.get(base + "/values/" + quote("LeadHistory!A1:H10000", safe=""), timeout=20)
    if response.status_code != 200:
        raise RuntimeError("lead_history_read_failed")
    history = response.json().get("values")
    if not isinstance(history, list) or not history or history[0] != list(HISTORY_COLS):
        raise RuntimeError("lead_history_headers_invalid")
    return history


def _remember_approved(conn, base, expected):
    # Before replacing Approved, keep each verified identity across every future run.
    # Only the active private sheet holds identities; never log row contents.
    history = _read_history(conn, base)
    from dedupe_preflight import candidate_identity, domains_match
    seen = [candidate_identity({"company": r[1], "website": r[2],
                                "email": r[3], "official_url": r[4]})
            for r in history[1:] if len(r) >= 6 and r[1] and r[3] and r[4]]
    additions = []
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    for row in expected[1:]:
        candidate = candidate_identity({"company": row[1], "website": row[2],
                                        "email": row[3], "official_url": row[4]})
        duplicate = any((candidate["company"] == prior["company"] or
                         bool(candidate["emails"] & prior["emails"]) or
                         any(domains_match(a, b) for a in candidate["domains"]
                             for b in prior["domains"])) for prior in seen)
        if duplicate:
            raise RuntimeError("lead_history_already_recorded")
        seen.append(candidate)
        additions.append([row[0], row[1], row[2], row[3], row[4],
                          "verified_lead", "", now])
    if not additions:
        return 0
    body = {"values": additions, "majorDimension": "ROWS"}
    resp = conn.post(base + "/values/" + quote("LeadHistory!A:H", safe="") + ":append",
                     params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
                     json=body, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError("lead_history_append_failed")
    actual = _read_history(conn, base)
    if actual != history + additions:
        raise RuntimeError("lead_history_append_readback_failed")
    return len(additions)



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
                not (greeting == ("Hoi," if int(cluster) >= 5 else "Goedendag,")
                     or re.fullmatch(r"Hoi [A-ZÀ-ÿ][A-Za-zÀ-ÿ-]{1,40},", greeting))
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
        # Failure to persist the new identities blocks claiming completed handoff.
        _remember_approved(conn, base, expected)
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
