from __future__ import annotations

import imaplib
import os
import re
import ssl
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate, make_msgid


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


def lead_exists(client, folder: str, lead_id: str) -> bool:
    if client.select(f'"{folder}"', readonly=True)[0] != "OK":
        raise RuntimeError("Could not open drafts folder")
    status, data = client.search(None, "HEADER", "X-Webactueel-Lead-ID", f'"{lead_id}"')
    return status == "OK" and bool(data and data[0].strip())


def append_and_verify(client, folder: str, msg: EmailMessage, lead_id: str) -> None:
    if lead_exists(client, folder, lead_id):
        return
    raw = msg.as_bytes(policy=SMTP)
    status, _ = client.append(folder, "(\\Draft)", imaplib.Time2Internaldate(__import__("time").time()), raw)
    if status != "OK":
        raise RuntimeError(f"IMAP APPEND failed for {lead_id}")
    if not lead_exists(client, folder, lead_id):
        raise RuntimeError(f"Draft readback failed for {lead_id}")
