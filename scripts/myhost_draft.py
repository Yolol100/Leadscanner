"""Store exactly one review draft in Mijn.Host via IMAP; never send mail."""
from __future__ import annotations

import imaplib
import os
import re
import ssl
import time
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate, make_msgid

from draft_queue_readonly import load_draft, load_drafts
from dedupe_preflight import match_candidate, normalize_company, normalize_domain, domains_match
from registry_readonly import load_suppressions

DRAFT_HEADER = "X-Webactueel-Draft-ID"


def _text(value: object) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _mailbox_arg(folder: str) -> str:
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'


def connect_imap():
    host = os.getenv("OUTREACH_IMAP_HOST", "mail.andrewbaeten.nl").strip()
    port = int(os.getenv("OUTREACH_IMAP_PORT", "993"))
    user = os.getenv("OUTREACH_MAIL_USER", "info@andrewbaeten.nl").strip()
    password = os.getenv("OUTREACH_MAIL_PASSWORD", "")
    if not host or not user or not password or not (1 <= port <= 65535):
        raise RuntimeError("imap_configuration_missing")
    client = imaplib.IMAP4_SSL(
        host, port, ssl_context=ssl.create_default_context(), timeout=20
    )
    try:
        client.login(user, password)
    except Exception:
        try:
            client.logout()
        except Exception:
            pass
        raise RuntimeError("imap_login_failed") from None
    return client


def find_drafts_folder(client) -> str:
    preferred = os.getenv("OUTREACH_DRAFT_FOLDER", "").strip()
    status, rows = client.list()
    if status != "OK":
        raise RuntimeError("imap_folder_list_failed")

    special: list[str] = []
    named: list[str] = []
    for raw in rows or []:
        entry = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        match = re.fullmatch(
            r'\((?P<flags>[^)]*)\)\s+(?:"(?:\\.|[^"\\])*"|NIL)\s+'
            r'(?P<mailbox>"(?:\\.|[^"\\])*"|[^\s"]+)\s*',
            entry,
        )
        if not match:
            continue
        token = match.group("mailbox")
        folder = token[1:-1].replace('\\"', '"').replace('\\\\', '\\') if token.startswith('"') else token
        low = folder.casefold()
        flags = match.group("flags").casefold().split()
        if "\\drafts" in flags:
            special.append(folder)
        elif low.replace("/", ".").split(".")[-1] in {"draft", "drafts", "concept", "concepten"}:
            named.append(folder)

    choices = list(dict.fromkeys(special if special else named))
    if preferred:
        if preferred not in choices:
            raise RuntimeError("configured_drafts_folder_not_verified")
        return preferred
    if len(choices) != 1:
        raise RuntimeError("drafts_folder_missing_or_ambiguous")
    return choices[0]


def build_message(row: dict[str, str]) -> EmailMessage:
    sender_name = os.getenv("OUTREACH_SENDER_NAME", "Andrew Baeten").strip()
    sender_email = os.getenv("OUTREACH_SENDER_EMAIL", "info@andrewbaeten.nl").strip()
    if not sender_name or sender_email.count("@") != 1:
        raise RuntimeError("sender_identity_invalid")
    msg = EmailMessage(policy=policy.default)
    msg["From"] = f"{sender_name} <{sender_email}>"
    msg["To"] = row["email"]
    msg["Subject"] = row["subject"]
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender_email.rsplit("@", 1)[1])
    msg[DRAFT_HEADER] = row["draft_id"]
    msg.set_content(row["body"])
    return msg


def _plain_body(msg: EmailMessage) -> str:
    if msg.is_multipart():
        part = msg.get_body(preferencelist=("plain",))
        return _text(part.get_content() if part else "")
    return _text(msg.get_content())


def _matches(expected: EmailMessage, actual: EmailMessage) -> bool:
    return (
        _text(actual.get(DRAFT_HEADER, "")) == _text(expected.get(DRAFT_HEADER, ""))
        and _text(actual.get("To", "")).casefold() == _text(expected.get("To", "")).casefold()
        and _text(actual.get("Subject", "")) == _text(expected.get("Subject", ""))
        and _plain_body(actual) == _plain_body(expected)
    )


def _find_matches(client, folder: str, draft_id: str, *, selected: bool = False) -> list[tuple[bytes, EmailMessage, bool]]:
    if not selected and client.select(_mailbox_arg(folder), readonly=True)[0] != "OK":
        raise RuntimeError("drafts_folder_select_failed")
    status, data = client.search(None, "HEADER", DRAFT_HEADER, f'"{draft_id}"')
    if status != "OK":
        raise RuntimeError("draft_search_failed")
    results = []
    for seq in (data[0] if data else b"").split():
        status, payload = client.fetch(seq, "(FLAGS RFC822)")
        if status != "OK":
            raise RuntimeError("draft_readback_failed")
        raw_msg = None
        meta = b""
        for item in payload or []:
            if isinstance(item, tuple) and len(item) >= 2:
                head = item[0]
                meta += head if isinstance(head, bytes) else str(head).encode("ascii", errors="ignore")
                if isinstance(item[1], (bytes, bytearray)):
                    raw_msg = bytes(item[1])
        if raw_msg is None:
            raise RuntimeError("draft_readback_missing_message")
        msg = BytesParser(policy=policy.default).parsebytes(raw_msg)
        is_draft = bool(re.search(rb"(?:^|[\s(])\\Draft(?=[\s)])", meta, re.I))
        results.append((seq, msg, is_draft))
    return results


def save_draft(client, folder: str, row: dict[str, str], *, selected: bool = False) -> str:
    expected = build_message(row)
    existing = _find_matches(client, folder, row["draft_id"], selected=selected)
    if len(existing) > 1:
        raise RuntimeError("duplicate_draft_id_in_mailbox")
    if existing:
        _, actual, is_draft = existing[0]
        if not is_draft or not _matches(expected, actual):
            raise RuntimeError("existing_draft_changed")
        return "existing"

    status, _ = client.append(_mailbox_arg(folder), "(\\Draft)", None, expected.as_bytes())
    if status != "OK":
        raise RuntimeError("imap_append_failed")

    for attempt in range(5):
        if attempt:
            time.sleep(0.5)
        found = _find_matches(client, folder, row["draft_id"], selected=True)
        if len(found) == 1:
            _, actual, is_draft = found[0]
            if is_draft and _matches(expected, actual):
                return "created"
            raise RuntimeError("draft_readback_mismatch")
        if len(found) > 1:
            raise RuntimeError("duplicate_draft_after_append")
    raise RuntimeError("draft_readback_missing")


def create_from_queue(draft_id: str) -> str:
    row = load_draft(draft_id)
    # Recheck all historical contacts, bounces and opt-outs immediately before
    # even creating a draft. This internal safety gate is not a fifth step.
    try:
        registry = load_suppressions()
        matched = match_candidate({
            "name_hint": row["company"],
            "website_hint": row["source_url"],
            "email": row["email"],
        }, registry)
    except Exception:
        raise RuntimeError("registry_unavailable_before_draft") from None
    if matched is not None:
        raise RuntimeError("historically_suppressed_before_draft")
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        return save_draft(client, folder, row)
    finally:
        try:
            client.logout()
        except Exception:
            pass

def create_batch_from_queue(draft_ids: list[str]) -> dict[str, int]:
    """Process up to 100 IDs: reject individuals, fail closed on shared faults.

    A single Sheets read and complete historical registry check happen before
    any IMAP login. Each eligible draft still receives exact readback.
    """
    rows = load_drafts(draft_ids, skip_invalid=True)
    invalid = len(draft_ids) - len(rows)
    try:
        registry = load_suppressions()
        company_seen: set[str] = set()
        domain_seen: set[str] = set()
        email_seen: set[str] = set()
        eligible: list[dict[str, str]] = []
        suppressed = duplicate = 0
        for row in rows:
            ident = {
                "name_hint": row["company"],
                "website_hint": row["source_url"],
                "email": row["email"],
            }
            # Registry/key-vault failures must abort the ENTIRE batch.
            if match_candidate(ident, registry) is not None:
                suppressed += 1
                continue
            name = normalize_company(row["company"])
            domain = normalize_domain(row["source_url"])
            email = row["email"].casefold()
            if (name in company_seen or email in email_seen or
                    any(domains_match(domain, item) for item in domain_seen)):
                duplicate += 1
                continue
            company_seen.add(name)
            domain_seen.add(domain)
            email_seen.add(email)
            eligible.append(row)
    except Exception:
        raise RuntimeError("batch_preflight_unavailable") from None

    result = {
        "total": len(draft_ids), "created": 0, "existing": 0,
        "skipped_invalid": invalid, "skipped_suppressed": suppressed,
        "skipped_duplicate": duplicate,
    }
    if not eligible:
        return result

    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        selected = False
        for row in eligible:
            # IMAP errors/changed drafts stop the run; retries remain idempotent.
            outcome = save_draft(client, folder, row, selected=selected)
            selected = True
            if outcome == "created":
                result["created"] += 1
            elif outcome == "existing":
                result["existing"] += 1
            else:
                raise RuntimeError("batch_draft_outcome_invalid")
    finally:
        try:
            client.logout()
        except Exception:
            pass
    return result
