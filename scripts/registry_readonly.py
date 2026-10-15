"""Read deduplication and independent HMAC suppression without writes."""
import json
import os
import re
from urllib.parse import quote

from dedupe_preflight import load_registry_values, candidate_identity
from historical_v2 import read_production_state

REGISTRY_ID = "1p4vZnCdcex9zpTAV-ssebXqZcBS2TU6KfXwS-4d2iSI"
REGISTRY_TAB = "DedupeRegistry"
_ID = re.compile(r"^[A-Za-z0-9_-]{15,128}$")
_TAB = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,40}$")


def authorized_session():
    raw = (os.getenv("LEAD_REGISTRY_SERVICE_ACCOUNT_JSON", "").strip()
           or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip())
    if not raw:
        raise RuntimeError("registry_credentials_missing")
    try:
        info = json.loads(raw)
        if not isinstance(info, dict) or info.get("type") != "service_account":
            raise ValueError("invalid credential")
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
        cred = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
        return AuthorizedSession(cred)
    except Exception:
        raise RuntimeError("registry_auth_invalid") from None


def read_values(session, spreadsheet_id, tab):
    if not _ID.fullmatch(spreadsheet_id) or not _TAB.fullmatch(tab):
        raise RuntimeError("registry_location_invalid")
    url = ("https://sheets.googleapis.com/v4/spreadsheets/"
           + spreadsheet_id + "/values/" + quote(tab + "!A:J", safe=""))
    try:
        response = session.get(url, timeout=20)
        if response.status_code != 200:
            raise RuntimeError("read_failed")
        values = response.json().get("values")
        if not isinstance(values, list):
            raise RuntimeError("missing_values")
        return values
    except Exception:
        raise RuntimeError("registry_read_failed") from None


def load_suppressions(session=None):
    session = session if session is not None else authorized_session()
    ordinary = load_registry_values(read_values(session, REGISTRY_ID, REGISTRY_TAB))
    historic = read_production_state(session, read_values, REGISTRY_ID)
    if historic.get("status") != "historical_v2_suppression":
        raise RuntimeError("historical_suppression_unavailable")
    return ordinary + [historic]


# Private append-only discoveries are suppressed for NEW SEARCHES only.
# Do not add them to load_suppressions(): a lead still needs its first draft.
LEAD_HISTORY_ID = "13dLUKiX3mWjPWly_UPJFYolOcLc2JBD7Cxv2QBHXRGM"
LEAD_HISTORY_TAB = "LeadHistory"
LEAD_HISTORY_HEADERS = [
    "first_seen_run", "company", "website", "email", "source_url",
    "status", "draft_id", "recorded_at",
]


def load_discovery_suppressions(session=None):
    session = session if session is not None else authorized_session()
    baseline = load_suppressions(session=session)
    values = read_values(session, LEAD_HISTORY_ID, LEAD_HISTORY_TAB)
    if not values or values[0] != LEAD_HISTORY_HEADERS:
        raise RuntimeError("lead_history_headers_invalid")
    history = []
    seen = set()
    for number, raw in enumerate(values[1:], start=2):
        if not isinstance(raw, list) or len(raw) > len(LEAD_HISTORY_HEADERS):
            raise RuntimeError("lead_history_invalid_row")
        if not any(str(x).strip() for x in raw):
            continue
        padded = [str(x or "").strip() for x in raw] + [""] * (len(LEAD_HISTORY_HEADERS) - len(raw))
        run_id, company, website, email, source, status, draft_id, created = padded
        if (not company or not email or not source or status not in {"verified_lead", "draft_queued"}):
            raise RuntimeError("lead_history_incomplete")
        identity = candidate_identity({"company": company, "website": website,
                                       "email": email, "official_url": source})
        if not identity["domains"] or not identity["emails"] or not identity["company"]:
            raise RuntimeError("lead_history_identity_missing")
        key = (identity["company"], tuple(sorted(identity["domains"])), email.casefold())
        if key in seen:
            raise RuntimeError("lead_history_duplicate_row")
        seen.add(key)
        history.append({"identity": identity, "status": status, "row_number": number})
    return baseline + history
