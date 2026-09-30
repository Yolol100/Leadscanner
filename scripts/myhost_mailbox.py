from __future__ import annotations

import base64
import imaplib
import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default
from email.utils import formatdate, make_msgid

SEND_ENABLE_ENV = "OUTREACH_SMTP_SEND_ENABLED"


def normalize_text(value: object) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


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


def connect_smtp():
    host = os.getenv("OUTREACH_SMTP_HOST", os.getenv("OUTREACH_IMAP_HOST", "mail.andrewbaeten.nl")).strip()
    mode = os.getenv("OUTREACH_SMTP_MODE", "starttls").strip().casefold()
    port = int(os.getenv("OUTREACH_SMTP_PORT", "465" if mode == "ssl" else "587"))
    user = os.getenv("OUTREACH_MAIL_USER", "info@andrewbaeten.nl").strip()
    password = os.getenv("OUTREACH_SMTP_PASSWORD", os.getenv("OUTREACH_MAIL_PASSWORD", ""))
    if not password:
        raise RuntimeError("OUTREACH_SMTP_PASSWORD or OUTREACH_MAIL_PASSWORD is required")
    context = ssl.create_default_context()
    if mode == "ssl":
        client = smtplib.SMTP_SSL(host, port, context=context, timeout=30)
    elif mode == "starttls":
        client = smtplib.SMTP(host, port, timeout=30)
        client.ehlo()
        client.starttls(context=context)
        client.ehlo()
    else:
        raise RuntimeError("OUTREACH_SMTP_MODE must be starttls or ssl")
    client.login(user, password)
    return client


def decode_folder(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    if '"' in text:
        end = text.rfind('"')
        start = text.rfind('"', 0, end)
        if start >= 0:
            return text[start + 1:end].replace('\\"', '"')
    return text.split()[-1].strip('"')


def list_folders(client) -> list[str]:
    status, rows = client.list()
    if status != "OK":
        raise RuntimeError("Could not list IMAP folders")
    return [decode_folder(row) for row in (rows or [])]


def select_folder(client, folder: str, *, readonly: bool = True) -> int:
    status, data = client.select(f'"{folder}"', readonly=readonly)
    if status != "OK":
        raise RuntimeError(f"Could not open folder: {folder}")
    try:
        return int((data or [b"0"])[0] or 0)
    except (TypeError, ValueError):
        return 0


def _uid(client, command: str, *args):
    status, data = client.uid(command, *args)
    if status != "OK":
        raise RuntimeError(f"IMAP UID {command} failed")
    return data


def list_message_uids(client, folder: str, *, unread_only: bool = False, limit: int = 50) -> list[str]:
    if limit < 1 or limit > 500:
        raise ValueError("limit must be 1-500")
    select_folder(client, folder, readonly=True)
    data = _uid(client, "search", None, "UNSEEN" if unread_only else "ALL")
    uids = (data[0] if data else b"").split()
    return [uid.decode() for uid in uids[-limit:]][::-1]


def fetch_message(client, folder: str, uid: str, *, readonly: bool = True) -> EmailMessage:
    select_folder(client, folder, readonly=readonly)
    data = _uid(client, "fetch", str(uid), "(RFC822)")
    for item in data or []:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            return BytesParser(policy=default).parsebytes(bytes(item[1]))
    raise RuntimeError(f"No message bytes returned for UID {uid}")


def _body_parts(msg: EmailMessage) -> tuple[str, str | None]:
    plain = ""
    html = None
    if msg.is_multipart():
        plain_part = msg.get_body(preferencelist=("plain",))
        html_part = msg.get_body(preferencelist=("html",))
        if plain_part:
            plain = normalize_text(plain_part.get_content())
        if html_part:
            html = normalize_text(html_part.get_content())
    else:
        content = msg.get_content()
        if msg.get_content_type() == "text/html":
            html = normalize_text(content)
        else:
            plain = normalize_text(content)
    return plain, html


def serialize_message(msg: EmailMessage, *, include_attachments: bool = True) -> dict:
    plain, html = _body_parts(msg)
    attachments = []
    if include_attachments:
        for part in msg.iter_attachments():
            payload = part.get_payload(decode=True) or b""
            attachments.append({
                "filename": part.get_filename(),
                "content_type": part.get_content_type(),
                "size": len(payload),
                "content_base64": base64.b64encode(payload).decode("ascii"),
            })
    return {
        "message_id": normalize_text(msg.get("Message-ID", "")) or None,
        "from": normalize_text(msg.get("From", "")),
        "to": normalize_text(msg.get("To", "")),
        "cc": normalize_text(msg.get("Cc", "")) or None,
        "bcc": normalize_text(msg.get("Bcc", "")) or None,
        "subject": normalize_text(msg.get("Subject", "")),
        "date": normalize_text(msg.get("Date", "")) or None,
        "in_reply_to": normalize_text(msg.get("In-Reply-To", "")) or None,
        "references": normalize_text(msg.get("References", "")) or None,
        "body_text": plain,
        "body_html": html,
        "attachments": attachments,
    }


def search_messages(client, folder: str, *, from_text: str | None = None, to_text: str | None = None,
                    subject_text: str | None = None, body_text: str | None = None,
                    unread_only: bool = False, limit: int = 50) -> list[str]:
    if limit < 1 or limit > 500:
        raise ValueError("limit must be 1-500")
    select_folder(client, folder, readonly=True)
    criteria: list[str] = []
    if unread_only:
        criteria.append("UNSEEN")
    for key, value in (("FROM", from_text), ("TO", to_text), ("SUBJECT", subject_text), ("BODY", body_text)):
        value = normalize_text(value)
        if value:
            criteria.extend([key, f'"{value.replace(chr(34), "")}"'])
    if not criteria:
        criteria = ["ALL"]
    data = _uid(client, "search", None, *criteria)
    uids = (data[0] if data else b"").split()
    return [uid.decode() for uid in uids[-limit:]][::-1]


def create_folder(client, folder: str) -> None:
    if not normalize_text(folder):
        raise ValueError("folder is required")
    status, _ = client.create(folder)
    if status != "OK":
        raise RuntimeError(f"Could not create folder: {folder}")


def rename_folder(client, old_folder: str, new_folder: str) -> None:
    status, _ = client.rename(old_folder, new_folder)
    if status != "OK":
        raise RuntimeError(f"Could not rename folder: {old_folder}")


def delete_folder(client, folder: str) -> None:
    status, _ = client.delete(folder)
    if status != "OK":
        raise RuntimeError(f"Could not delete folder: {folder}")


def set_flag(client, folder: str, uid: str, flag: str, *, enabled: bool) -> None:
    select_folder(client, folder, readonly=False)
    _uid(client, "store", str(uid), "+FLAGS.SILENT" if enabled else "-FLAGS.SILENT", f"({flag})")


def copy_message(client, source_folder: str, uid: str, destination_folder: str) -> None:
    select_folder(client, source_folder, readonly=False)
    _uid(client, "copy", str(uid), destination_folder)


def delete_message(client, folder: str, uid: str) -> None:
    select_folder(client, folder, readonly=False)
    _uid(client, "store", str(uid), "+FLAGS.SILENT", "(\\Deleted)")
    _uid(client, "expunge", str(uid))


def move_message(client, source_folder: str, uid: str, destination_folder: str) -> None:
    copy_message(client, source_folder, uid, destination_folder)
    delete_message(client, source_folder, uid)


def _addresses(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(normalize_text(x) for x in value if normalize_text(x))
    return normalize_text(value)


def build_message(payload: dict, *, include_bcc: bool = True) -> EmailMessage:
    sender_name = os.getenv("OUTREACH_SENDER_NAME", "Andrew Baeten").strip()
    sender_email = os.getenv("OUTREACH_SENDER_EMAIL", os.getenv("OUTREACH_MAIL_USER", "info@andrewbaeten.nl")).strip()
    to = _addresses(payload.get("to"))
    subject = normalize_text(payload.get("subject"))
    body_text = normalize_text(payload.get("body_text"))
    body_html = normalize_text(payload.get("body_html"))
    if not to or not subject or (not body_text and not body_html):
        raise ValueError("to, subject and body_text or body_html are required")

    msg = EmailMessage(policy=default)
    msg["From"] = f"{sender_name} <{sender_email}>"
    msg["To"] = to
    cc = _addresses(payload.get("cc"))
    bcc = _addresses(payload.get("bcc"))
    if cc:
        msg["Cc"] = cc
    if include_bcc and bcc:
        msg["Bcc"] = bcc
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender_email.split("@")[-1] if "@" in sender_email else None)
    if normalize_text(payload.get("in_reply_to")):
        msg["In-Reply-To"] = normalize_text(payload["in_reply_to"])
    if normalize_text(payload.get("references")):
        msg["References"] = normalize_text(payload["references"])

    if body_html:
        msg.set_content(body_text or "HTML email")
        msg.add_alternative(body_html, subtype="html")
    else:
        msg.set_content(body_text)

    attachments = payload.get("attachments") or []
    if len(attachments) > 20:
        raise ValueError("at most 20 attachments are allowed")
    total_attachment_bytes = 0
    for attachment in attachments:
        raw = base64.b64decode(str(attachment.get("content_base64") or ""), validate=True)
        total_attachment_bytes += len(raw)
        if total_attachment_bytes > 25 * 1024 * 1024:
            raise ValueError("attachments exceed 25 MiB")
        content_type = normalize_text(attachment.get("content_type")) or "application/octet-stream"
        maintype, _, subtype = content_type.partition("/")
        if not subtype:
            maintype, subtype = "application", "octet-stream"
        msg.add_attachment(raw, maintype=maintype, subtype=subtype, filename=normalize_text(attachment.get("filename")) or None)
    return msg


def append_draft(client, folder: str, payload: dict) -> str:
    msg = build_message(payload)
    status, data = client.append(folder, "(\\Draft)", imaplib.Time2Internaldate(__import__("time").time()), msg.as_bytes(policy=default))
    if status != "OK":
        raise RuntimeError("IMAP APPEND failed")
    value = (data or [b""])[0]
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace").strip()
    return normalize_text(value)


def replace_draft(client, folder: str, uid: str, payload: dict) -> None:
    append_draft(client, folder, payload)
    delete_message(client, folder, uid)


def send_message(payload: dict, *, confirm_send: bool = False, smtp_factory=connect_smtp) -> dict:
    enabled = os.getenv(SEND_ENABLE_ENV, "").strip().casefold() in {"1", "true", "yes", "on"}
    if not confirm_send or not enabled:
        raise RuntimeError("Sending requires confirm_send=true and OUTREACH_SMTP_SEND_ENABLED=true")
    msg = build_message(payload, include_bcc=True)
    smtp = smtp_factory()
    try:
        smtp.send_message(msg)
    finally:
        try:
            smtp.quit()
        except Exception:
            pass
    return {
        "message_id": normalize_text(msg.get("Message-ID", "")),
        "to": normalize_text(msg.get("To", "")),
        "subject": normalize_text(msg.get("Subject", "")),
        "sent": True,
    }


def reply_payload(source: EmailMessage, body_text: str, *, reply_all: bool = False) -> dict:
    reply_to = normalize_text(source.get("Reply-To", "")) or normalize_text(source.get("From", ""))
    subject = normalize_text(source.get("Subject", ""))
    if not subject.casefold().startswith("re:"):
        subject = f"Re: {subject}"
    cc: list[str] = []
    if reply_all:
        for header in ("To", "Cc"):
            value = normalize_text(source.get(header, ""))
            if value:
                cc.append(value)
    refs = normalize_text(source.get("References", ""))
    source_id = normalize_text(source.get("Message-ID", ""))
    references = " ".join(x for x in (refs, source_id) if x)
    return {
        "to": [reply_to],
        "cc": cc,
        "subject": subject,
        "body_text": normalize_text(body_text),
        "in_reply_to": source_id or None,
        "references": references or None,
    }


def forward_payload(source: EmailMessage, to: object, note: str = "") -> dict:
    original = serialize_message(source, include_attachments=True)
    subject = original["subject"]
    if not subject.casefold().startswith("fwd:"):
        subject = f"Fwd: {subject}"
    body = normalize_text(note)
    forwarded = (f"{body}\n\n" if body else "") + (
        f"---------- Forwarded message ----------\n"
        f"From: {original['from']}\nTo: {original['to']}\n"
        f"Subject: {original['subject']}\nDate: {original['date'] or ''}\n\n"
        f"{original['body_text']}"
    )
    return {"to": to, "subject": subject, "body_text": forwarded, "attachments": original["attachments"]}


def execute(request: dict) -> dict:
    action = normalize_text(request.get("action"))
    if action == "send":
        return send_message(request.get("message") or {}, confirm_send=bool(request.get("confirm_send")))

    client = connect_imap()
    try:
        if action == "list_folders":
            return {"folders": list_folders(client)}
        if action == "create_folder":
            create_folder(client, normalize_text(request.get("folder")))
            return {"ok": True}
        if action == "rename_folder":
            rename_folder(client, normalize_text(request.get("folder")), normalize_text(request.get("destination")))
            return {"ok": True}
        if action == "delete_folder":
            if not request.get("confirm"):
                raise RuntimeError("delete_folder requires confirm=true")
            delete_folder(client, normalize_text(request.get("folder")))
            return {"ok": True}
        if action == "list_messages":
            return {"uids": list_message_uids(client, normalize_text(request.get("folder")), unread_only=bool(request.get("unread_only")), limit=int(request.get("limit") or 50))}
        if action == "search":
            return {"uids": search_messages(client, normalize_text(request.get("folder")), from_text=request.get("from"), to_text=request.get("to"), subject_text=request.get("subject"), body_text=request.get("body"), unread_only=bool(request.get("unread_only")), limit=int(request.get("limit") or 50))}
        if action == "read":
            msg = fetch_message(client, normalize_text(request.get("folder")), str(request.get("uid")))
            return {"message": serialize_message(msg, include_attachments=bool(request.get("include_attachments", True)))}
        if action == "mark_read":
            set_flag(client, normalize_text(request.get("folder")), str(request.get("uid")), "\\Seen", enabled=True)
            return {"ok": True}
        if action == "mark_unread":
            set_flag(client, normalize_text(request.get("folder")), str(request.get("uid")), "\\Seen", enabled=False)
            return {"ok": True}
        if action == "flag":
            set_flag(client, normalize_text(request.get("folder")), str(request.get("uid")), "\\Flagged", enabled=True)
            return {"ok": True}
        if action == "unflag":
            set_flag(client, normalize_text(request.get("folder")), str(request.get("uid")), "\\Flagged", enabled=False)
            return {"ok": True}
        if action == "copy":
            copy_message(client, normalize_text(request.get("folder")), str(request.get("uid")), normalize_text(request.get("destination")))
            return {"ok": True}
        if action == "move":
            move_message(client, normalize_text(request.get("folder")), str(request.get("uid")), normalize_text(request.get("destination")))
            return {"ok": True}
        if action == "delete":
            if not request.get("confirm"):
                raise RuntimeError("delete requires confirm=true")
            delete_message(client, normalize_text(request.get("folder")), str(request.get("uid")))
            return {"ok": True}
        if action == "create_draft":
            return {"append_result": append_draft(client, normalize_text(request.get("folder")), request.get("message") or {})}
        if action == "replace_draft":
            if not request.get("confirm"):
                raise RuntimeError("replace_draft requires confirm=true")
            replace_draft(client, normalize_text(request.get("folder")), str(request.get("uid")), request.get("message") or {})
            return {"ok": True}
        raise ValueError(f"Unknown action: {action}")
    finally:
        try:
            client.logout()
        except Exception:
            pass


def main() -> int:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    result = execute(request)
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"MYHOST_MAILBOX=green action={normalize_text(request.get('action'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
