from __future__ import annotations

import email
import imaplib
import os
import re
import ssl
from datetime import timedelta
from hashlib import sha256
from typing import Iterable

from outreach_mailboxes import MailboxConfig
from outreach_optout import message_has_optout
from outreach_sender import (
    QUEUE_SHEET,
    Settings,
    add_suppression,
    append_row,
    extract_bounced_recipient,
    iso,
    log_event,
    message_text,
    normalize_address,
    update_row,
    utcnow,
)

REPLY_SHEET = "ReplyInbox"
REPLY_HEADERS = [
    "reply_id",
    "received_at",
    "lead_id",
    "company",
    "email",
    "mailbox_id",
    "mailbox_email",
    "subject",
    "preview",
    "classification",
    "triage_status",
    "owner_label",
    "notes",
    "message_id",
    "in_reply_to",
    "source",
]


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _lookback_days() -> int:
    try:
        value = int(os.getenv("OUTREACH_REPLY_LOOKBACK_DAYS", "14") or "14")
    except ValueError:
        value = 14
    return max(1, min(value, 90))


def _compact_preview(text: str, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:limit]


def reply_id_for_message(mailbox_id: str, uid: bytes, msg) -> str:
    message_id = str(msg.get("Message-ID", "")).strip().lower()
    if message_id:
        basis = f"message-id|{message_id}"
    else:
        basis = "|".join(
            [
                "fallback",
                mailbox_id,
                uid.decode("utf-8", errors="replace"),
                normalize_address(msg.get("From", "")),
                str(msg.get("Date", "")),
                str(msg.get("Subject", "")),
            ]
        )
    return sha256(basis.encode("utf-8")).hexdigest()[:32]


def _append_reply(
    service,
    settings: Settings,
    *,
    reply_id: str,
    mailbox: MailboxConfig,
    lead_row: dict[str, str] | None,
    email_address: str,
    msg,
    classification: str,
    text: str,
) -> None:
    triage = "new" if classification in {"reply", "other"} else "closed"
    append_row(
        service,
        settings.spreadsheet_id,
        REPLY_SHEET,
        REPLY_HEADERS,
        {
            "reply_id": reply_id,
            "received_at": iso(utcnow()),
            "lead_id": "" if lead_row is None else lead_row.get("lead_id", ""),
            "company": "" if lead_row is None else lead_row.get("company", ""),
            "email": normalize_address(email_address),
            "mailbox_id": mailbox.mailbox_id,
            "mailbox_email": mailbox.sender_email,
            "subject": str(msg.get("Subject", ""))[:500],
            "preview": _compact_preview(text),
            "classification": classification,
            "triage_status": triage,
            "owner_label": "",
            "notes": "",
            "message_id": str(msg.get("Message-ID", ""))[:500],
            "in_reply_to": str(msg.get("In-Reply-To", ""))[:500],
            "source": f"imap:{mailbox.mailbox_id}",
        },
    )


def sync_replyhub_for_mailbox(
    service,
    settings: Settings,
    queue_headers: list[str],
    queue_rows: list[dict[str, str]],
    reply_rows: list[dict[str, str]],
    mailbox: MailboxConfig,
) -> int:
    if settings.mode != "live":
        return 0
    if not mailbox.imap_host or not mailbox.mail_user or not mailbox.mail_password:
        raise RuntimeError(f"IMAP settings are incomplete for mailbox {mailbox.mailbox_id}")

    capture_others = _bool_env("OUTREACH_CAPTURE_OTHER_MAIL", False)
    existing_ids = {str(row.get("reply_id", "")).strip() for row in reply_rows if row.get("reply_id")}
    lead_index = {
        normalize_address(row.get("email", "")): i
        for i, row in enumerate(queue_rows)
        if normalize_address(row.get("email", ""))
    }
    since = (utcnow() - timedelta(days=_lookback_days())).strftime("%d-%b-%Y")
    appended = 0

    with imaplib.IMAP4_SSL(
        mailbox.imap_host,
        mailbox.imap_port,
        ssl_context=ssl.create_default_context(),
    ) as imap:
        imap.login(mailbox.mail_user, mailbox.mail_password)
        imap.select("INBOX", readonly=True)
        status, data = imap.search(None, "SINCE", since)
        if status != "OK":
            raise RuntimeError(f"IMAP search failed for mailbox {mailbox.mailbox_id}")
        for uid in data[0].split():
            status, payload = imap.fetch(uid, "(RFC822)")
            if status != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            msg = email.message_from_bytes(payload[0][1], policy=email.policy.default)
            reply_id = reply_id_for_message(mailbox.mailbox_id, uid, msg)
            if reply_id in existing_ids:
                continue

            text = message_text(msg)
            sender = normalize_address(msg.get("From", ""))
            bounced = normalize_address(extract_bounced_recipient(msg))

            if bounced and bounced in lead_index:
                idx = lead_index[bounced]
                row = queue_rows[idx]
                _append_reply(
                    service,
                    settings,
                    reply_id=reply_id,
                    mailbox=mailbox,
                    lead_row=row,
                    email_address=bounced,
                    msg=msg,
                    classification="bounce",
                    text=text or str(msg.get("Subject", "")),
                )
                if row.get("status", "").strip().lower() != "bounced":
                    row.update(
                        status="bounced",
                        bounce_at=iso(utcnow()),
                        last_error="delivery status notification",
                    )
                    update_row(
                        service,
                        settings.spreadsheet_id,
                        QUEUE_SHEET,
                        idx + 2,
                        queue_headers,
                        row,
                    )
                    add_suppression(
                        service,
                        settings,
                        bounced,
                        "bounce",
                        str(msg.get("Subject", "")),
                        mailbox,
                    )
                    log_event(
                        service,
                        settings,
                        row,
                        "bounced",
                        detail=str(msg.get("Subject", "")),
                        mailbox=mailbox,
                    )
                existing_ids.add(reply_id)
                appended += 1
                continue

            if sender in lead_index:
                idx = lead_index[sender]
                row = queue_rows[idx]
                classification = "opt_out" if message_has_optout(text) else "reply"
                _append_reply(
                    service,
                    settings,
                    reply_id=reply_id,
                    mailbox=mailbox,
                    lead_row=row,
                    email_address=sender,
                    msg=msg,
                    classification=classification,
                    text=text,
                )
                if classification == "opt_out":
                    if row.get("status", "").strip().lower() != "opted_out":
                        row.update(status="opted_out", reply_at=iso(utcnow()))
                        update_row(
                            service,
                            settings.spreadsheet_id,
                            QUEUE_SHEET,
                            idx + 2,
                            queue_headers,
                            row,
                        )
                        add_suppression(
                            service,
                            settings,
                            sender,
                            "opt_out",
                            str(msg.get("Subject", "")),
                            mailbox,
                        )
                        log_event(
                            service,
                            settings,
                            row,
                            "opted_out",
                            detail=str(msg.get("Subject", "")),
                            mailbox=mailbox,
                        )
                else:
                    if row.get("status", "").strip().lower() not in {
                        "replied",
                        "opted_out",
                        "bounced",
                    }:
                        row.update(status="replied", reply_at=iso(utcnow()))
                        update_row(
                            service,
                            settings.spreadsheet_id,
                            QUEUE_SHEET,
                            idx + 2,
                            queue_headers,
                            row,
                        )
                        log_event(
                            service,
                            settings,
                            row,
                            "replied",
                            detail=str(msg.get("Subject", "")),
                            mailbox=mailbox,
                        )
                existing_ids.add(reply_id)
                appended += 1
                continue

            if capture_others and sender:
                _append_reply(
                    service,
                    settings,
                    reply_id=reply_id,
                    mailbox=mailbox,
                    lead_row=None,
                    email_address=sender,
                    msg=msg,
                    classification="other",
                    text=text,
                )
                existing_ids.add(reply_id)
                appended += 1

    return appended


def sync_replyhub(
    service,
    settings: Settings,
    queue_headers: list[str],
    queue_rows: list[dict[str, str]],
    reply_rows: list[dict[str, str]],
    mailboxes: Iterable[MailboxConfig],
) -> int:
    total = 0
    for mailbox in mailboxes:
        total += sync_replyhub_for_mailbox(
            service,
            settings,
            queue_headers,
            queue_rows,
            reply_rows,
            mailbox,
        )
    return total
