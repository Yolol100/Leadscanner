"""Read one private lead draft request from Google Sheets; never write it."""
from __future__ import annotations

import json
import os
import re
from urllib.parse import quote

from url_safety import is_public_http_url

DRAFT_QUEUE_ID = "1AOsEsxkG2He6SOlD92BZpmY2DAj3716Fp953oqgy1jk"
DRAFT_QUEUE_TAB = "DraftQueue"
HEADERS = ["draft_id", "created_at", "company", "email", "source_url", "subject", "body"]
DRAFT_ID_RE = re.compile(r"^draft-[0-9a-f]{32}$")
EMAIL_LOCAL_RE = re.compile(r"^[a-z0-9._%+\-]+$", re.I)
EMAIL_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.I)
UNFILLED_PLACEHOLDER_RE = re.compile(r"\[[^\[\]\n]{1,64}\]")


def valid_general_email(value: str) -> bool:
    """Basic ASCII general mailbox format; the official site remains the authority."""
    if not 3 <= len(value) <= 254 or value.count("@") != 1:
        return False
    local, host = value.split("@")
    if (not 1 <= len(local) <= 64 or local.startswith(".") or local.endswith(".")
            or ".." in local or not EMAIL_LOCAL_RE.fullmatch(local)):
        return False
    labels = host.split(".")
    if (len(labels) < 2 or len(host) > 253 or not 2 <= len(labels[-1]) <= 63
            or not all(EMAIL_LABEL_RE.fullmatch(label) for label in labels)):
        return False
    return labels[-1].isalpha() or labels[-1].startswith("xn--")


def _text(value: object) -> str:
    return str(value or "").strip()


def authorized_session():
    raw = (os.getenv("LEAD_REGISTRY_SERVICE_ACCOUNT_JSON", "").strip()
           or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip())
    if not raw:
        raise RuntimeError("draft_queue_credentials_missing")
    try:
        info = json.loads(raw)
        if not isinstance(info, dict) or info.get("type") != "service_account":
            raise ValueError("invalid credential")
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
        cred = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
        )
        return AuthorizedSession(cred)
    except Exception:
        raise RuntimeError("draft_queue_auth_invalid") from None


def read_values(session) -> list[list[object]]:
    url = (
        "https://sheets.googleapis.com/v4/spreadsheets/"
        + DRAFT_QUEUE_ID
        + "/values/"
        + quote(DRAFT_QUEUE_TAB + "!A:G", safe="")
    )
    try:
        response = session.get(url, timeout=20)
        if response.status_code != 200:
            raise RuntimeError("draft_queue_read_failed")
        values = response.json().get("values")
        if not isinstance(values, list):
            raise RuntimeError("draft_queue_values_missing")
        return values
    except Exception:
        raise RuntimeError("draft_queue_read_failed") from None


def _validate_row(row: dict[str, str]) -> dict[str, str]:
    draft_id = _text(row.get("draft_id")).casefold()
    company = _text(row.get("company"))
    email = _text(row.get("email")).casefold()
    source_url = _text(row.get("source_url"))
    subject = _text(row.get("subject"))
    body = str(row.get("body") or "").replace("\r\n", "\n").replace("\r", "\n").strip()

    if not DRAFT_ID_RE.fullmatch(draft_id):
        raise RuntimeError("draft_queue_id_invalid")
    if not company or len(company) > 160 or any(ord(ch) < 32 for ch in company):
        raise RuntimeError("draft_queue_company_invalid")
    if not valid_general_email(email):
        raise RuntimeError("draft_queue_email_invalid")
    if not is_public_http_url(source_url):
        raise RuntimeError("draft_queue_source_url_invalid")
    if not subject or len(subject) > 160 or any(ch in subject for ch in "\r\n\x00"):
        raise RuntimeError("draft_queue_subject_invalid")
    if not body or len(body) > 6000 or "\x00" in body:
        raise RuntimeError("draft_queue_body_invalid")

    if UNFILLED_PLACEHOLDER_RE.search(subject + "\n" + body):
        raise RuntimeError("draft_queue_unfilled_placeholder")

    return {
        "draft_id": draft_id,
        "created_at": _text(row.get("created_at")),
        "company": company,
        "email": email,
        "source_url": source_url,
        "subject": subject,
        "body": body,
    }


def load_drafts(draft_ids: list[str], session=None) -> list[dict[str, str]]:
    """Fetch up to 50 exact private queue entries with ONE authorized Sheets read."""
    if not isinstance(draft_ids, list) or not 1 <= len(draft_ids) <= 50:
        raise RuntimeError("draft_batch_size_invalid")
    ids = [_text(item).casefold() for item in draft_ids]
    if (any(not DRAFT_ID_RE.fullmatch(item) for item in ids)
            or len(set(ids)) != len(ids)):
        raise RuntimeError("draft_batch_ids_invalid")
    session = session if session is not None else authorized_session()
    values = read_values(session)
    if not values or values[0] != HEADERS:
        raise RuntimeError("draft_queue_headers_invalid")
    wanted = set(ids)
    matches: dict[str, dict[str, str]] = {}
    for raw in values[1:]:
        if not isinstance(raw, list) or len(raw) > len(HEADERS):
            raise RuntimeError("draft_queue_row_shape_invalid")
        padded = [str(value or "") for value in raw] + [""] * (len(HEADERS) - len(raw))
        row = dict(zip(HEADERS, padded))
        key = _text(row.get("draft_id")).casefold()
        if key not in wanted:
            continue
        if key in matches:
            raise RuntimeError("draft_queue_id_missing_or_duplicate")
        matches[key] = _validate_row(row)
    if len(matches) != len(ids):
        raise RuntimeError("draft_queue_id_missing_or_duplicate")
    return [matches[key] for key in ids]


def load_draft(draft_id: str, session=None) -> dict[str, str]:
    return load_drafts([draft_id], session)[0]
