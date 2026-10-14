"""Read deduplication and independent HMAC suppression without writes."""
import json
import os
import re
from urllib.parse import quote

from dedupe_preflight import load_registry_values
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
