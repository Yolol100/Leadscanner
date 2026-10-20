"""Owner-only PRIVATE, read-only snapshot of exactly 60 old V2 Drafts.

The live IMAP readers and independent original-MIME archive verifier are called
by migrate_v2_drafts before this module runs. This module has NO mailbox writer
and writes only a private, pre-created, hidden Google Sheets tab. Never log rows.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import quote

SHEET_ID = "13dLUKiX3mWjPWly_UPJFYolOcLc2JBD7Cxv2QBHXRGM"
SHEET_TAB = "V2 60 Live Inventaris 20261020"
SHEET_GID = 443964530
OLD_COUNT = 60
HEADERS = (
    "Bronnummer", "Draft-ID", "UIDVALIDITY", "Actuele IMAP UID",
    "MIME SHA256", "Origineel MIME archiefstatus", "Archief MIME SHA256",
    "V2-categorie", "V2-actief", "Zakelijk e-mailadres",
    "Officiele bron URL", "HMAC / juridische status", "Pilot-status",
    "GitHub run ID", "Snapshot UTC",
)
DIGITS = re.compile(r"[1-9][0-9]*\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
DRAFT = re.compile(r"draft-[0-9a-f]{32}\Z")


def build_rows(records, state, archived, validity, *, run_id, now=None):
    """Fail closed unless exact live old-generation membership is known."""
    if (not DIGITS.fullmatch(str(validity))
            or not DIGITS.fullmatch(str(run_id))
            or not isinstance(records, dict)
            or not isinstance(state, dict)
            or not isinstance(archived, dict)):
        raise RuntimeError("v2_private_inventory_scope_invalid")
    snapshot = now or datetime.now(timezone.utc)
    if snapshot.tzinfo is None:
        raise RuntimeError("v2_private_inventory_scope_invalid")
    old_keys = [k for k, item in state.items() if item[1] == "old"]
    if len(old_keys) != OLD_COUNT:
        raise RuntimeError("v2_private_inventory_scope_invalid")
    result = [list(HEADERS)]
    seen_uids = set()
    for key in sorted(old_keys, key=lambda k: int(records[k]["number"])):
        row = records.get(key)
        uid, generation, sha = state[key]
        if (not row or not DRAFT.fullmatch(key)
                or generation != "old"
                or not DIGITS.fullmatch(str(uid))
                or str(uid) in seen_uids
                or not SHA.fullmatch(str(sha))
                or row["category"] not in {"target", "source_hold"}
                or row["active"] not in {True, False}
                or not str(row["new"]["email"]).count("@") == 1
                or not str(row["new"]["source_url"]).startswith(("https://", "http://"))):
            raise RuntimeError("v2_private_inventory_scope_invalid")
        seen_uids.add(str(uid))
        archived_item = archived.get(key)
        if archived_item:
            archived_sha = archived_item.get("sha256", "")
            if archived_sha != sha:
                raise RuntimeError("v2_private_inventory_archive_mismatch")
            archive_status = "ARCHIEF_ORIGINEEL_MIME_SHA_OK"
        else:
            archived_sha = ""
            archive_status = "GEEN_ORIGINEEL_MIME_ARCHIEF"
        result.append([
            str(row["number"]), key, str(validity), str(uid), str(sha),
            archive_status, archived_sha, row["category"],
            "JA" if row["active"] else "NEE", row["new"]["email"],
            row["new"]["source_url"], "GROEPS_HMAC_GATE_GELEZEN; LEGAL_OPEN",
            "NEE - OFFICIELE SITE / INDIVIDUELE REVIEW / MIME_ARCHIEF",
            str(run_id), snapshot.astimezone(timezone.utc).isoformat(),
        ])
    if len(result) != OLD_COUNT + 1:
        raise RuntimeError("v2_private_inventory_scope_invalid")
    return result


def store_rows(rows, session):
    """Write an empty, hidden, fixed private tab exactly once, then read back.

    No unverified remote row contents or exception strings may reach logs.
    """
    if (len(rows) != OLD_COUNT + 1 or rows[0] != list(HEADERS)
            or any(len(row) != len(HEADERS) for row in rows)):
        raise RuntimeError("v2_private_inventory_scope_invalid")
    base = "https://sheets.googleapis.com/v4/spreadsheets/" + SHEET_ID
    values_path = "/values/" + quote("'" + SHEET_TAB + "'!A1:O61", safe="")
    try:
        info = session.get(
            base + "?fields=sheets(properties(sheetId,title,hidden,gridProperties(rowCount,columnCount)))",
            timeout=25)
        if info.status_code != 200:
            raise ValueError("missing private sheet")
        matches = [
            p for p in (s.get("properties", {}) for s in info.json().get("sheets", []))
            if p.get("sheetId") == SHEET_GID and p.get("title") == SHEET_TAB
        ]
        if (len(matches) != 1 or matches[0].get("hidden") is not True
                or matches[0].get("gridProperties", {}).get("rowCount") != OLD_COUNT + 1
                or matches[0].get("gridProperties", {}).get("columnCount") != len(HEADERS)):
            raise ValueError("private sheet mismatch")
        before = session.get(base + values_path, timeout=25)
        if before.status_code != 200 or before.json().get("values", []):
            raise ValueError("private sheet not empty")
        payload = {
            "requests": [{
                "updateCells": {
                    "range": {
                        "sheetId": SHEET_GID,
                        "startRowIndex": 0,
                        "endRowIndex": OLD_COUNT + 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": len(HEADERS),
                    },
                    "rows": [{"values": [
                        {"userEnteredValue": {"stringValue": str(s)}} for s in row
                    ]} for row in rows],
                    "fields": "userEnteredValue",
                }
            }]
        }
        written = session.post(base + ":batchUpdate", json=payload, timeout=35)
        if written.status_code != 200:
            raise ValueError("private sheet write failed")
        checked = session.get(base + values_path, timeout=25)
        if checked.status_code != 200 or checked.json().get("values") != rows:
            raise ValueError("private sheet readback mismatch")
    except Exception:
        raise RuntimeError("v2_private_inventory_readback_failed") from None
    return OLD_COUNT
