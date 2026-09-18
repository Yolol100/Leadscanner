from __future__ import annotations

import imaplib
import os
import re
import ssl
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import SMTP
from email.utils import formatdate, make_msgid


def _normalize_text(value: str) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def build_message(row: dict[str, str], postal_address: str) -> EmailMessage:
    body = row["body"].strip()
    if postal_address.casefold() not in body.casefold():
        body = body + "\n\n" + postal_address

    msg = EmailMessage(policy=SMTP)
    msg["From"] = f'{os.getenv("OUTREACH_SENDER_NAME", "Andrew Baeten")} <{os.getenv("OUTREACH_SENDER_EMAIL", "info@andrewbaeten.nl")}>'
    msg["To"] = row["email"]
    msg["Subject"] = row["subject"]
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="andrewbaeten.nl")
    msg["X-Webactueel-Lead-ID"] = row["lead_id"]
    msg.set_content(body)
    return msg


def connect_imap():
    host = os.getenv("OUTREACH_IMAP_HOST", "mail.andrewbaeten.nl").strip()
    port = int(os.getenv("OUTREACH_IMAP_PORT", "993"))
    user = os.getenv("OUTREACH_MAIL_USER", "info@andrewbaeten.nl").strip()
    password = os.getenv("OUTREACH_MAIL_PASSWORD", "")
    if not password:
        raise RuntimeError("OUTREACH_MAIL_PASSWORD is required")
    client = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context())
    client.login(user, password)
    return client


def find_drafts_folder(client) -> str:
    preferred = os.getenv("OUTREACH_DRAFT_FOLDER", "").strip()
    if preferred:
        return preferred
    status, rows = client.list()
    if status != "OK":
        raise RuntimeError("Could not list IMAP folders")
    choices: list[str] = []
    for raw in rows or []:
        text = raw.decode("utf-8", errors="replace")
        match = re.search(r'"([^"\\]*(?:\\.[^"\\]*)*)"\s*$', text)
        folder = match.group(1).replace('\\"', '"') if match else text.split()[-1].strip('"')
        choices.append(folder)
    for folder in choices:
        low = folder.casefold()
        if "draft" in low or "concept" in low:
            return folder
    raise RuntimeError("No Drafts/Concepten IMAP folder found")


def find_lead_message_ids(client, folder: str, lead_id: str) -> list[bytes]:
    if client.select(f'"{folder}"', readonly=True)[0] != "OK":
        raise RuntimeError("Could not open drafts folder")
    status, data = client.search(None, "HEADER", "X-Webactueel-Lead-ID", f'"{lead_id}"')
    if status != "OK":
        raise RuntimeError(f"Could not search draft readback for {lead_id}")
    return list((data[0] if data else b"").split())


def fetch_message(client, message_id: bytes) -> EmailMessage:
    status, data = client.fetch(message_id, "(RFC822)")
    if status != "OK":
        raise RuntimeError("Could not fetch draft for exact readback")
    raw = None
    for item in data or []:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            raw = bytes(item[1])
            break
    if raw is None:
        raise RuntimeError("IMAP readback did not return message bytes")
    return BytesParser(policy=SMTP).parsebytes(raw)


def plain_body(msg: EmailMessage) -> str:
    if msg.is_multipart():
        part = msg.get_body(preferencelist=("plain",))
        return _normalize_text(part.get_content() if part else "")
    return _normalize_text(msg.get_content())


def exact_message_matches(actual: EmailMessage, expected: EmailMessage) -> bool:
    return (
        _normalize_text(actual.get("To", "")) == _normalize_text(expected.get("To", ""))
        and _normalize_text(actual.get("Subject", "")) == _normalize_text(expected.get("Subject", ""))
        and plain_body(actual) == plain_body(expected)
    )


def verify_exact_readback(client, folder: str, expected: EmailMessage, lead_id: str) -> None:
    ids = find_lead_message_ids(client, folder, lead_id)
    if len(ids) != 1:
        raise RuntimeError(f"Expected exactly one draft for {lead_id}, found {len(ids)}")
    actual = fetch_message(client, ids[0])
    if not exact_message_matches(actual, expected):
        raise RuntimeError(f"Draft readback mismatch for {lead_id}")


def append_and_verify(client, folder: str, msg: EmailMessage, lead_id: str) -> None:
    existing = find_lead_message_ids(client, folder, lead_id)
    if existing:
        if len(existing) != 1:
            raise RuntimeError(f"Duplicate drafts already exist for {lead_id}")
        actual = fetch_message(client, existing[0])
        if not exact_message_matches(actual, msg):
            raise RuntimeError(f"Existing draft does not match selected lead {lead_id}")
        return

    raw = msg.as_bytes(policy=SMTP)
    status, _ = client.append(folder, "(\\Draft)", imaplib.Time2Internaldate(__import__("time").time()), raw)
    if status != "OK":
        raise RuntimeError(f"IMAP APPEND failed for {lead_id}")
    verify_exact_readback(client, folder, msg, lead_id)
