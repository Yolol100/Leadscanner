from __future__ import annotations

import argparse
import imaplib
import json
import os
import re
import ssl
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default
from email.utils import formatdate, make_msgid
from pathlib import Path


MAX_DRAFTS_PER_RUN = 100
LEAD_ID_RE = re.compile(r"^growth-[0-9a-f]{20}$")


def normalize_text(value: object) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def stable_lead_id(row: dict) -> str:
    existing = normalize_text(row.get("lead_id"))
    if not LEAD_ID_RE.fullmatch(existing):
        raise RuntimeError("mijn.host requires a canonical reviewed growth-<20 hex> lead_id")
    return existing


def build_message(row: dict) -> tuple[str, EmailMessage]:
    if row.get("status") != "draft_ready":
        raise RuntimeError("Only draft_ready rows may enter mijn.host")
    if row.get("contact_basis_status") != "pass":
        raise RuntimeError("Contact basis must be pass before mijn.host draft creation")

    email = normalize_text(row.get("email"))
    subject = normalize_text(row.get("subject"))
    body = normalize_text(row.get("body"))
    if not email or not subject or not body:
        raise RuntimeError("draft_ready row is missing email, subject or body")

    lead_id = stable_lead_id(row)
    sender_name = os.getenv("OUTREACH_SENDER_NAME", "Andrew Baeten").strip()
    sender_email = os.getenv("OUTREACH_SENDER_EMAIL", "info@andrewbaeten.nl").strip()

    msg = EmailMessage(policy=default)
    msg["From"] = f"{sender_name} <{sender_email}>"
    msg["To"] = email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender_email.split("@")[-1] if "@" in sender_email else None)
    msg["X-Webactueel-Lead-ID"] = lead_id
    msg.set_content(body)
    return lead_id, msg


def connect_imap():
    host = os.getenv("OUTREACH_IMAP_HOST", "mail.andrewbaeten.nl").strip()
    port = int(os.getenv("OUTREACH_IMAP_PORT", "993"))
    user = os.getenv("OUTREACH_MAIL_USER", "info@andrewbaeten.nl").strip()
    password = os.getenv("OUTREACH_MAIL_PASSWORD", "")
    if not password:
        raise RuntimeError("OUTREACH_MAIL_PASSWORD is required when drafts are ready")
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
        folder = match.group(1).replace('\\\"', '"') if match else text.split()[-1].strip('"')
        choices.append(folder)

    for folder in choices:
        low = folder.casefold()
        if "draft" in low or "concept" in low:
            return folder
    raise RuntimeError("No Drafts/Concepten IMAP folder found")


def select_folder(client, folder: str) -> None:
    if client.select(f'"{folder}"', readonly=True)[0] != "OK":
        raise RuntimeError("Could not open drafts folder")


def find_message_ids(client, folder: str, lead_id: str, *, ensure_selected: bool = True) -> list[bytes]:
    if ensure_selected:
        select_folder(client, folder)
    status, data = client.search(None, "HEADER", "X-Webactueel-Lead-ID", f'"{lead_id}"')
    if status != "OK":
        raise RuntimeError(f"Could not search draft readback for {lead_id}")
    return list((data[0] if data else b"").split())


def fetch_message(client, message_id: bytes) -> EmailMessage:
    status, data = client.fetch(message_id, "(RFC822)")
    if status != "OK":
        raise RuntimeError("Could not fetch draft for readback")
    for item in data or []:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            return BytesParser(policy=default).parsebytes(bytes(item[1]))
    raise RuntimeError("IMAP readback returned no message bytes")


def plain_body(msg: EmailMessage) -> str:
    if msg.is_multipart():
        part = msg.get_body(preferencelist=("plain",))
        return normalize_text(part.get_content() if part else "")
    return normalize_text(msg.get_content())


def exact_message_matches(actual: EmailMessage, expected: EmailMessage) -> bool:
    return (
        normalize_text(actual.get("To", "")) == normalize_text(expected.get("To", ""))
        and normalize_text(actual.get("Subject", "")) == normalize_text(expected.get("Subject", ""))
        and plain_body(actual) == plain_body(expected)
    )


def append_and_verify(client, folder: str, lead_id: str, msg: EmailMessage) -> str:
    existing = find_message_ids(client, folder, lead_id)
    if existing:
        if len(existing) != 1:
            raise RuntimeError(f"Expected one existing draft for {lead_id}, found {len(existing)}")
        actual = fetch_message(client, existing[0])
        if not exact_message_matches(actual, msg):
            raise RuntimeError(f"Existing draft differs for {lead_id}")
        return "existing"

    raw = msg.as_bytes(policy=default)
    status, _ = client.append(
        folder,
        "(\\Draft)",
        imaplib.Time2Internaldate(__import__("time").time()),
        raw,
    )
    if status != "OK":
        raise RuntimeError(f"IMAP APPEND failed for {lead_id}")

    ids = find_message_ids(client, folder, lead_id)
    if len(ids) != 1:
        raise RuntimeError(f"Expected one draft after append for {lead_id}, found {len(ids)}")
    actual = fetch_message(client, ids[0])
    if not exact_message_matches(actual, msg):
        raise RuntimeError(f"Draft readback mismatch for {lead_id}")
    return "created"


def create_drafts(batch: dict) -> dict:
    rows = [
        row
        for row in (batch.get("rows") or [])
        if row.get("status") == "draft_ready"
        and row.get("contact_basis_status") == "pass"
    ]
    if len(rows) > MAX_DRAFTS_PER_RUN:
        raise RuntimeError(f"At most {MAX_DRAFTS_PER_RUN} drafts may be created per run")

    if not rows:
        return {
            "eligible_count": 0,
            "created_count": 0,
            "existing_count": 0,
            "draft_folder": None,
            "smtp_send": "not_available",
        }

    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        created = 0
        existing = 0
        for row in rows:
            lead_id, msg = build_message(row)
            outcome = append_and_verify(client, folder, lead_id, msg)
            if outcome == "created":
                created += 1
            else:
                existing += 1
        return {
            "eligible_count": len(rows),
            "created_count": created,
            "existing_count": existing,
            "draft_folder": folder,
            "smtp_send": "not_available",
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    batch = json.loads(Path(args.batch).read_text(encoding="utf-8"))
    result = create_drafts(batch)
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "MYHOST_DRAFT_SYNC=green "
        f"eligible={result['eligible_count']} "
        f"created={result['created_count']} "
        f"existing={result['existing_count']} "
        "smtp_send=not_available"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
