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
    address = " ".join(str(postal_address or "").split()).strip()
    if not address:
        raise RuntimeError("OUTREACH_POSTAL_ADDRESS is required for commercial draft")
    if address.casefold() not in body.casefold():
        body = body + "\n\nPostadres: " + address

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


def _select_drafts_folder(client, folder: str) -> None:
    if client.select(f'"{folder}"', readonly=True)[0] != "OK":
        raise RuntimeError("Could not open drafts folder")


def find_lead_message_ids(client, folder: str, lead_id: str, *, ensure_selected: bool = True) -> list[bytes]:
    if ensure_selected:
        _select_drafts_folder(client, folder)
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


def verify_exact_readback(
    client,
    folder: str,
    expected: EmailMessage,
    lead_id: str,
    *,
    ensure_selected: bool = True,
) -> None:
    ids = find_lead_message_ids(client, folder, lead_id, ensure_selected=ensure_selected)
    if len(ids) != 1:
        raise RuntimeError(f"Expected exactly one draft for {lead_id}, found {len(ids)}")
    actual = fetch_message(client, ids[0])
    if not exact_message_matches(actual, expected):
        raise RuntimeError(f"Draft readback mismatch for {lead_id}")


def _append_uid(data) -> str | None:
    for item in data or []:
        text = item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item)
        match = re.search(r"APPENDUID\s+\d+\s+(\d+)", text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _append_message(client, folder: str, msg: EmailMessage, lead_id: str) -> str | None:
    raw = msg.as_bytes(policy=SMTP)
    status, data = client.append(
        folder,
        "(\\Draft)",
        imaplib.Time2Internaldate(__import__("time").time()),
        raw,
    )
    if status != "OK":
        raise RuntimeError(f"IMAP APPEND failed for {lead_id}")
    return _append_uid(data)


def fetch_messages_by_uid(client, uids: list[str]) -> dict[str, EmailMessage]:
    if not uids:
        return {}
    message_set = ",".join(uids)
    status, data = client.uid("fetch", message_set, "(RFC822)")
    if status != "OK":
        raise RuntimeError("Could not fetch appended drafts by UID for exact readback")

    messages: dict[str, EmailMessage] = {}
    for item in data or []:
        if not (isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray))):
            continue
        msg = BytesParser(policy=SMTP).parsebytes(bytes(item[1]))
        lead_id = _normalize_text(msg.get("X-Webactueel-Lead-ID", ""))
        if not lead_id:
            raise RuntimeError("UID readback returned a draft without X-Webactueel-Lead-ID")
        if lead_id in messages:
            raise RuntimeError(f"UID readback returned duplicate draft for {lead_id}")
        messages[lead_id] = msg

    if len(messages) != len(uids):
        raise RuntimeError(
            f"UID readback returned {len(messages)} messages for {len(uids)} appended drafts"
        )
    return messages


def append_and_verify(
    client,
    folder: str,
    msg: EmailMessage,
    lead_id: str,
    *,
    already_selected: bool = False,
) -> None:
    existing = find_lead_message_ids(client, folder, lead_id, ensure_selected=not already_selected)
    if existing:
        if len(existing) != 1:
            raise RuntimeError(f"Duplicate drafts already exist for {lead_id}")
        actual = fetch_message(client, existing[0])
        if not exact_message_matches(actual, msg):
            raise RuntimeError(f"Existing draft does not match selected lead {lead_id}")
        return

    uid = _append_message(client, folder, msg, lead_id)
    if uid:
        actual = fetch_messages_by_uid(client, [uid]).get(lead_id)
        if actual is None or not exact_message_matches(actual, msg):
            raise RuntimeError(f"Draft readback mismatch for {lead_id}")
        return
    verify_exact_readback(client, folder, msg, lead_id)


def append_many_and_verify(client, folder: str, messages: list[tuple[str, EmailMessage]]) -> None:
    """Create/read back a selected batch while reusing mailbox state and APPENDUID.

    Existing drafts keep the same per-lead duplicate/idempotency check. New appends
    use server-returned APPENDUID values when available, then perform one bulk UID
    fetch for exact To/Subject/body readback. Servers without APPENDUID retain the
    previous search-based readback path.
    """
    _select_drafts_folder(client, folder)
    appended: list[tuple[str, EmailMessage, str]] = []

    for lead_id, msg in messages:
        existing = find_lead_message_ids(
            client,
            folder,
            lead_id,
            ensure_selected=False,
        )
        if existing:
            if len(existing) != 1:
                raise RuntimeError(f"Duplicate drafts already exist for {lead_id}")
            actual = fetch_message(client, existing[0])
            if not exact_message_matches(actual, msg):
                raise RuntimeError(f"Existing draft does not match selected lead {lead_id}")
            continue

        uid = _append_message(client, folder, msg, lead_id)
        if uid:
            appended.append((lead_id, msg, uid))
        else:
            verify_exact_readback(
                client,
                folder,
                msg,
                lead_id,
                ensure_selected=False,
            )

    if appended:
        actual_by_lead = fetch_messages_by_uid(
            client,
            [uid for _, _, uid in appended],
        )
        for lead_id, expected, _ in appended:
            actual = actual_by_lead.get(lead_id)
            if actual is None:
                raise RuntimeError(f"UID readback missing draft for {lead_id}")
            if not exact_message_matches(actual, expected):
                raise RuntimeError(f"Draft readback mismatch for {lead_id}")
