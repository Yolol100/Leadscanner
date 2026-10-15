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
HISTORY_TAB_ID = 683104992
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


def _identity(company, website, email, source):
    from dedupe_preflight import candidate_identity
    return candidate_identity({"company": company, "website": website,
                               "email": email, "official_url": source})


def _overlaps(a, b):
    from dedupe_preflight import domains_match
    return (
        (bool(a["company"]) and a["company"] == b["company"]) or
        bool(a["emails"] & b["emails"]) or
        any(domains_match(x, y) for x in a["domains"] for y in b["domains"])
    )


def _history_additions(history, expected):
    # Existing private history is the permanent discovery-level exclusion list.
    # Do not interpret draft_queued as proof of IMAP readback.
    previous = []
    for number, raw in enumerate(history[1:], start=2):
        if not isinstance(raw, list) or len(raw) > len(HISTORY_COLS):
            raise RuntimeError("lead_history_invalid_row")
        if not any(str(x).strip() for x in raw):
            raise RuntimeError("lead_history_blank_row")
        row = [str(x or "").strip() for x in raw] + [""] * (len(HISTORY_COLS) - len(raw))
        if (not row[1] or not valid_general_email(row[3]) or
                safe_hint(row[2]) != row[2] or safe_hint(row[4]) != row[4] or
                row[5] not in {"verified_lead", "draft_queued", "draft_saved"}):
            raise RuntimeError("lead_history_incomplete")
        identity = _identity(row[1], row[2], row[3], row[4])
        if not identity["company"] or not identity["domains"] or not identity["emails"]:
            raise RuntimeError("lead_history_identity_invalid")
        if any(_overlaps(identity, known) for known in previous):
            raise RuntimeError("lead_history_duplicate_identity")
        previous.append(identity)

    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).isoformat()
    additions = []
    for row in expected[1:]:
        identity = _identity(row[1], row[2], row[3], row[4])
        if any(_overlaps(identity, known) for known in previous):
            raise RuntimeError("lead_history_already_recorded")
        previous.append(identity)
        additions.append([row[0], row[1], row[2], row[3], row[4],
                          "verified_lead", "", timestamp])
    if len(history) + len(additions) > 10000:
        raise RuntimeError("lead_history_capacity_exceeded")
    return additions


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
        history = _read_history(conn, base)
        additions = _history_additions(history, expected)
        # The snapshot replacement and permanent history append must commit
        # together. Sheets batchUpdate is atomic: no partial two-write state.
        requests = [{
            "updateCells": {
                "range": {"sheetId": TAB_ID, "startRowIndex": 0,
                          "endRowIndex": MAX + 1, "startColumnIndex": 0,
                          "endColumnIndex": len(COLS)},
                "rows": rows, "fields": "userEnteredValue"
            }
        }]
        if additions:
            requests.append({"appendCells": {
                "sheetId": HISTORY_TAB_ID,
                "rows": [{"values": [{"userEnteredValue": {"stringValue": x}} if x else {}
                                     for x in item]} for item in additions],
                "fields": "userEnteredValue"
            }})
        response = conn.post(base + ":batchUpdate",
                             json={"requests": requests}, timeout=30)
        if response.status_code != 200:
            raise RuntimeError("approved_handoff_write_failed")
        got = conn.get(base + "/values/" + quote("Approved!A1:I101", safe=""), timeout=20)
        if got.status_code != 200 or got.json().get("values") != expected:
            raise RuntimeError("approved_handoff_readback_failed")
        actual = _read_history(conn, base)
        if actual != history + additions:
            raise RuntimeError("lead_history_readback_failed")
        return len(approved)
    except Exception:
        raise RuntimeError("approved_handoff_unverified") from None
