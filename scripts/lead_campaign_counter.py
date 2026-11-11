"""Read-only cumulative campaign progress from private, verified evidence.

No prospect data leaves Google Sheets. The caller may log aggregate counts only.
Use the exact existing LeadHistory and WebsiteEvidence identity/provenance.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from approved_handoff import _read_history
from fast_website_evidence import COLUMNS, _digest, _read
from private_candidate_handoff import SHEET_ID, authorized_writer

CONFIRMED = frozenset({"verified_with_detail", "verified_activity_only"})
MANUAL = "needs_manual_check"
EVIDENCE_RANGE = "WebsiteEvidence!A1:N2200"


def _date(value):
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise RuntimeError("campaign_date_invalid") from None
    if timestamp.tzinfo is None:
        raise RuntimeError("campaign_date_missing_timezone")
    return timestamp


def verified_count(since_utc, *, session=None):
    """Count only distinct, historically new and official-site-confirmed leads."""
    cutoff = _date(since_utc)
    conn = session if session is not None else authorized_writer()
    base = "https://sheets.googleapis.com/v4/spreadsheets/" + SHEET_ID
    history = _read_history(conn, base)
    raw = _read(conn, EVIDENCE_RANGE)
    if not raw or raw[0] != list(COLUMNS):
        raise RuntimeError("campaign_evidence_headers_invalid")

    official = {}
    for line in raw[1:]:
        if len(line) != len(COLUMNS):
            raise RuntimeError("campaign_evidence_row_invalid")
        rec = dict(zip(COLUMNS, line))
        if rec["source_tab"] != "Approved":
            continue
        key = rec["record_key"]
        if key in official:
            raise RuntimeError("campaign_evidence_duplicate_key")
        if rec["status"] not in CONFIRMED | {MANUAL}:
            raise RuntimeError("campaign_evidence_unknown_status")
        official[key] = rec

    matched = set()
    count = 0
    for row in history[1:]:
        if len(row) != 8:
            raise RuntimeError("campaign_history_row_invalid")
        if row[5] != "verified_lead":
            continue
        timestamp = _date(row[7])
        if timestamp < cutoff:
            continue
        _, company, website, email, _, _, _, _ = row
        key = "Approved:" + _digest([company, website, email])[:24]
        if key in matched:
            raise RuntimeError("campaign_history_duplicate_identity")
        matched.add(key)
        evidence = official.get(key)
        if evidence is None:
            # No first-party evidence means HOLD, never a confirmed lead.
            continue
        if (evidence["company"] != company or evidence["website"] != website
                or evidence["email"] != email):
            raise RuntimeError("campaign_identity_mismatch")
        if evidence["status"] in CONFIRMED:
            count += 1
    return count


def remaining(since_utc, *, goal=450, session=None):
    if not isinstance(goal, int) or not 1 <= goal <= 5000:
        raise ValueError("campaign_goal_invalid")
    return max(0, goal - verified_count(since_utc, session=session))
