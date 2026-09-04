from __future__ import annotations

import email
import imaplib
import json
import os
import re
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime, parseaddr
from hashlib import sha256
from html import unescape
from typing import Iterable
from zoneinfo import ZoneInfo

from outreach_mailboxes import (
    MailboxConfig,
    choose_initial_mailbox,
    count_mailbox_sends_today,
    enabled_mailboxes,
    last_mailbox_send_times,
    load_mailboxes_from_env,
    mailbox_is_available,
    mailbox_map,
)

QUEUE_SHEET = "OutreachQueue"
SUPPRESSION_SHEET = "Suppression"
LOG_SHEET = "OutreachLog"
QUEUE_HEADERS = [
    "lead_id", "company", "website", "email", "first_name", "subject", "body",
    "followup_subject", "followup_body", "followup_delay_days", "country",
    "compliance_status", "opt_out_mode", "status", "verification_status",
    "verification_checked_at", "stage", "next_send_at", "sent_at",
    "followup_sent_at", "message_id", "followup_message_id", "reply_at",
    "bounce_at", "last_error", "source", "sender_mailbox_id", "sender_email",
]
SUPPRESSION_HEADERS = ["email", "domain", "reason", "source", "created_at", "evidence"]
LOG_HEADERS = [
    "timestamp", "lead_id", "email", "event", "message_id", "detail",
    "mailbox_id", "sender_email",
]
SAFE_VERIFICATION = {"safe"}
MANUAL_REVIEW_VERIFICATION = {"catch_all", "unknown", "role_account", "inbox_full"}
BLOCKED_VERIFICATION = {"invalid", "disabled", "disposable", "spamtrap"}
STOP_STATUSES = {"replied", "bounced", "opted_out", "blocked", "manual_review"}
OPT_OUT_PHRASES = (
    "unsubscribe", "remove me", "stop emailing", "do not email", "don't email",
    "no more emails", "afmelden", "uitschrijven", "verwijder mij", "geen mails meer",
)
SHORT_OPT_OUT_REPLIES = {"nee", "nee bedankt", "geen interesse"}


@dataclass(frozen=True)
class Settings:
    spreadsheet_id: str
    mode: str
    timezone_name: str
    send_window_start: str
    send_window_end: str
    daily_send_limit: int
    max_sends_per_run: int
    verification_max_age_days: int
    smtp_host: str
    smtp_port: int
    imap_host: str
    imap_port: int
    mail_user: str
    mail_password: str
    sender_name: str
    sender_email: str

    @staticmethod
    def from_env() -> "Settings":
        mode = os.getenv("OUTREACH_MODE", "validate").strip().lower()
        if mode not in {"validate", "verify", "live"}:
            raise ValueError("OUTREACH_MODE must be validate, verify, or live")
        daily = int(os.getenv("OUTREACH_DAILY_LIMIT", "20"))
        per_run = int(os.getenv("OUTREACH_MAX_SENDS_PER_RUN", "2"))
        if daily < 1 or daily > 100:
            raise ValueError("OUTREACH_DAILY_LIMIT must be between 1 and 100")
        if per_run < 1 or per_run > 10:
            raise ValueError("OUTREACH_MAX_SENDS_PER_RUN must be between 1 and 10")
        return Settings(
            spreadsheet_id=os.environ["OUTREACH_SPREADSHEET_ID"],
            mode=mode,
            timezone_name=os.getenv("OUTREACH_TIMEZONE", "Europe/Amsterdam"),
            send_window_start=os.getenv("OUTREACH_SEND_WINDOW_START", "08:00"),
            send_window_end=os.getenv("OUTREACH_SEND_WINDOW_END", "18:00"),
            daily_send_limit=daily,
            max_sends_per_run=per_run,
            verification_max_age_days=int(os.getenv("OUTREACH_VERIFICATION_MAX_AGE_DAYS", "30")),
            smtp_host=os.getenv("OUTREACH_SMTP_HOST", ""),
            smtp_port=int(os.getenv("OUTREACH_SMTP_PORT", "587") or "587"),
            imap_host=os.getenv("OUTREACH_IMAP_HOST", ""),
            imap_port=int(os.getenv("OUTREACH_IMAP_PORT", "993") or "993"),
            mail_user=os.getenv("OUTREACH_MAIL_USER", ""),
            mail_password=os.getenv("OUTREACH_MAIL_PASSWORD", ""),
            sender_name=os.getenv("OUTREACH_SENDER_NAME", ""),
            sender_email=os.getenv("OUTREACH_SENDER_EMAIL", ""),
        )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def within_send_window(now: datetime, tz_name: str, start: str, end: str) -> bool:
    local = now.astimezone(ZoneInfo(tz_name))
    if local.weekday() >= 5:
        return False
    sh, sm = map(int, start.split(":", 1))
    eh, em = map(int, end.split(":", 1))
    current = local.hour * 60 + local.minute
    return sh * 60 + sm <= current < eh * 60 + em


def count_sends_today(rows: Iterable[dict[str, str]], now: datetime, tz_name: str) -> int:
    tz = ZoneInfo(tz_name)
    today = now.astimezone(tz).date()
    total = 0
    for row in rows:
        for key in ("sent_at", "followup_sent_at"):
            dt = parse_dt(row.get(key, ""))
            if dt and dt.astimezone(tz).date() == today:
                total += 1
    return total


def verification_decision(result: dict) -> str:
    status = str(result.get("status", "")).strip().lower()
    if status in SAFE_VERIFICATION and bool(result.get("is_safe_to_send")):
        return "safe"
    if status in BLOCKED_VERIFICATION:
        return "blocked"
    return "manual_review"


def verification_is_fresh(row: dict[str, str], now: datetime, max_age_days: int) -> bool:
    if row.get("verification_status", "").strip().lower() != "safe":
        return False
    checked = parse_dt(row.get("verification_checked_at", ""))
    return bool(checked and now - checked <= timedelta(days=max_age_days))


def normalize_address(value: str) -> str:
    return parseaddr(value or "")[1].strip().lower()


def domain_of(address: str) -> str:
    address = normalize_address(address)
    return address.rsplit("@", 1)[1] if "@" in address else ""


def _short_reply(value: str) -> str:
    value = re.sub(r"\s+", " ", value.lower()).strip()
    return value.strip(" .,!?:;\"'")


def message_has_optout(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", (text or "").lower())
    if any(phrase in normalized for phrase in OPT_OUT_PHRASES):
        return True
    for line in (text or "").splitlines():
        candidate = _short_reply(line)
        if not candidate:
            continue
        return candidate in SHORT_OPT_OUT_REPLIES
    return False


def html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value or "")
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(value)).strip()


def message_text(msg) -> str:
    parts: list[str] = []
    walk = msg.walk() if msg.is_multipart() else [msg]
    for part in walk:
        if part.get_content_maintype() == "multipart":
            continue
        ctype = part.get_content_type()
        if ctype not in {"text/plain", "text/html"}:
            continue
        try:
            content = part.get_content()
        except Exception:
            raw = part.get_payload(decode=True) or b""
            content = raw.decode(part.get_content_charset() or "utf-8", errors="replace")
        parts.append(content if ctype == "text/plain" else html_to_text(content))
    return "\n".join(parts)


def extract_bounced_recipient(msg) -> str:
    for part in msg.walk():
        if part.get_content_type() == "message/delivery-status":
            payload = part.get_payload()
            if isinstance(payload, list):
                for block in payload:
                    for key in ("Final-Recipient", "Original-Recipient"):
                        value = block.get(key)
                        if value:
                            candidate = value.split(";", 1)[-1].strip().lower()
                            if "@" in candidate:
                                return candidate
    match = re.search(
        r"(?im)^(?:Final-Recipient|Original-Recipient):\s*(?:rfc822;)?\s*([^\s<>]+@[^\s<>]+)",
        msg.as_string(),
    )
    return match.group(1).strip().lower() if match else ""


def deterministic_message_id(lead_id: str, stage: int, sender_email: str) -> str:
    domain = domain_of(sender_email) or "localhost"
    digest = sha256(f"{lead_id}:{stage}".encode()).hexdigest()[:32]
    return f"<{digest}.{stage}@{domain}>"


def build_message(row: dict[str, str], mailbox: MailboxConfig, stage: int) -> EmailMessage:
    if stage == 1:
        subject, body = row.get("subject", "").strip(), row.get("body", "").strip()
    else:
        subject = row.get("followup_subject", "").strip() or "Re: " + row.get("subject", "").strip()
        body = row.get("followup_body", "").strip()
    if not subject or not body:
        raise ValueError("subject/body missing for requested stage")
    msg = EmailMessage()
    msg["From"] = f"{mailbox.sender_name} <{mailbox.sender_email}>" if mailbox.sender_name else mailbox.sender_email
    msg["To"] = row["email"]
    msg["Subject"] = subject
    msg["Date"] = format_datetime(utcnow())
    msg["Message-ID"] = deterministic_message_id(row["lead_id"], stage, mailbox.sender_email)
    if stage == 2 and row.get("message_id"):
        msg["In-Reply-To"] = row["message_id"]
        msg["References"] = row["message_id"]
    msg.set_content(body)
    return msg


def smtp_send(msg: EmailMessage, mailbox: MailboxConfig) -> None:
    if not mailbox.smtp_host or not mailbox.mail_user or not mailbox.mail_password:
        raise RuntimeError("SMTP settings are incomplete")
    context = ssl.create_default_context()
    if mailbox.smtp_port == 465:
        with smtplib.SMTP_SSL(mailbox.smtp_host, mailbox.smtp_port, context=context, timeout=30) as smtp:
            smtp.login(mailbox.mail_user, mailbox.mail_password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(mailbox.smtp_host, mailbox.smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(mailbox.mail_user, mailbox.mail_password)
            smtp.send_message(msg)


def next_action(row: dict[str, str], now: datetime) -> str | None:
    status = row.get("status", "").strip().lower()
    if status in STOP_STATUSES or status in {"sending", "error", "followup_sent"}:
        return None
    if status == "approved":
        return "initial"
    if status == "sent" and row.get("followup_body", "").strip():
        due = parse_dt(row.get("next_send_at", ""))
        if due and due <= now:
            return "followup"
    return None


def suppression_match(address: str, suppressed_emails: set[str], suppressed_domains: set[str]) -> bool:
    address = normalize_address(address)
    return address in suppressed_emails or domain_of(address) in suppressed_domains


def validate_row(row: dict[str, str], action: str) -> list[str]:
    required = ["lead_id", "email", "compliance_status", "opt_out_mode"]
    required += ["subject", "body"] if action == "initial" else ["followup_body", "message_id"]
    errors = [f"missing {key}" for key in required if not row.get(key, "").strip()]
    if row.get("compliance_status", "").strip().lower() != "approved":
        errors.append("compliance_status is not approved")
    if row.get("opt_out_mode", "").strip().lower() != "reply_optout":
        errors.append("direct SMTP route requires reply_optout; provider_required needs a provider with the required unsubscribe mechanism")
    if "@" not in normalize_address(row.get("email", "")):
        errors.append("invalid email syntax")
    return errors


def rows_from_values(values: list[list[str]]) -> tuple[list[str], list[dict[str, str]]]:
    if not values:
        return [], []
    headers = [str(v).strip() for v in values[0]]
    rows = []
    for raw in values[1:]:
        padded = list(raw) + [""] * max(0, len(headers) - len(raw))
        rows.append({headers[i]: str(padded[i]) for i in range(len(headers))})
    return headers, rows


def column_name(index: int) -> str:
    if index < 1:
        raise ValueError("index must be >= 1")
    result = ""
    while index:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result


def build_sheets_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def get_values(service, spreadsheet_id: str, sheet_name: str) -> list[list[str]]:
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=f"'{sheet_name}'!A:AZ"
    ).execute()
    return result.get("values", [])


def update_row(service, spreadsheet_id: str, sheet_name: str, row_number: int, headers: list[str], row: dict[str, str]) -> None:
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'!A{row_number}:{column_name(len(headers))}{row_number}",
        valueInputOption="RAW",
        body={"values": [[row.get(header, "") for header in headers]]},
    ).execute()


def append_row(service, spreadsheet_id: str, sheet_name: str, headers: list[str], row: dict[str, str]) -> None:
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'!A:AZ",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [[row.get(header, "") for header in headers]]},
    ).execute()


def ensure_expected_headers(headers: list[str], expected: list[str], sheet_name: str) -> None:
    missing = [h for h in expected if h not in headers]
    if missing:
        raise RuntimeError(f"{sheet_name} missing headers: {', '.join(missing)}")


def suppression_sets(rows: Iterable[dict[str, str]]) -> tuple[set[str], set[str]]:
    emails, domains = set(), set()
    for row in rows:
        address = normalize_address(row.get("email", ""))
        domain = row.get("domain", "").strip().lower()
        if address:
            emails.add(address)
        if domain:
            domains.add(domain)
    return emails, domains


def add_suppression(
    service,
    settings: Settings,
    address: str,
    reason: str,
    evidence: str = "",
    mailbox: MailboxConfig | None = None,
) -> None:
    source = "imap" if mailbox is None else f"imap:{mailbox.mailbox_id}"
    append_row(service, settings.spreadsheet_id, SUPPRESSION_SHEET, SUPPRESSION_HEADERS, {
        "email": normalize_address(address), "domain": "", "reason": reason,
        "source": source, "created_at": iso(utcnow()), "evidence": evidence[:500],
    })


def log_event(
    service,
    settings: Settings,
    row: dict[str, str],
    event: str,
    message_id: str = "",
    detail: str = "",
    mailbox: MailboxConfig | None = None,
) -> None:
    append_row(service, settings.spreadsheet_id, LOG_SHEET, LOG_HEADERS, {
        "timestamp": iso(utcnow()), "lead_id": row.get("lead_id", ""),
        "email": row.get("email", ""), "event": event, "message_id": message_id,
        "detail": detail[:500],
        "mailbox_id": "" if mailbox is None else mailbox.mailbox_id,
        "sender_email": "" if mailbox is None else mailbox.sender_email,
    })


def sync_inbox_for_mailbox(
    service,
    settings: Settings,
    headers: list[str],
    rows: list[dict[str, str]],
    mailbox: MailboxConfig,
) -> None:
    if settings.mode != "live":
        return
    if not mailbox.imap_host or not mailbox.mail_user or not mailbox.mail_password:
        raise RuntimeError(f"IMAP settings are incomplete for mailbox {mailbox.mailbox_id}")
    email_index = {normalize_address(row.get("email", "")): i for i, row in enumerate(rows) if row.get("email")}
    since = (utcnow() - timedelta(days=14)).strftime("%d-%b-%Y")
    with imaplib.IMAP4_SSL(mailbox.imap_host, mailbox.imap_port, ssl_context=ssl.create_default_context()) as imap:
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
            sender = normalize_address(msg.get("From", ""))
            bounced = extract_bounced_recipient(msg)
            if bounced in email_index:
                idx, row = email_index[bounced], rows[email_index[bounced]]
                if row.get("status", "").lower() != "bounced":
                    row.update(status="bounced", bounce_at=iso(utcnow()), last_error="delivery status notification")
                    update_row(service, settings.spreadsheet_id, QUEUE_SHEET, idx + 2, headers, row)
                    add_suppression(service, settings, bounced, "bounce", msg.get("Subject", ""), mailbox)
                    log_event(service, settings, row, "bounced", detail=msg.get("Subject", ""), mailbox=mailbox)
                continue
            if sender not in email_index:
                continue
            idx, row = email_index[sender], rows[email_index[sender]]
            text = message_text(msg)
            if message_has_optout(text):
                if row.get("status", "").lower() != "opted_out":
                    row.update(status="opted_out", reply_at=iso(utcnow()))
                    update_row(service, settings.spreadsheet_id, QUEUE_SHEET, idx + 2, headers, row)
                    add_suppression(service, settings, sender, "opt_out", msg.get("Subject", ""), mailbox)
                    log_event(service, settings, row, "opted_out", detail=msg.get("Subject", ""), mailbox=mailbox)
                continue
            if row.get("status", "").lower() in STOP_STATUSES:
                continue
            row.update(status="replied", reply_at=iso(utcnow()))
            update_row(service, settings.spreadsheet_id, QUEUE_SHEET, idx + 2, headers, row)
            log_event(service, settings, row, "replied", detail=msg.get("Subject", ""), mailbox=mailbox)


def sync_inboxes(
    service,
    settings: Settings,
    headers: list[str],
    rows: list[dict[str, str]],
    mailboxes: Iterable[MailboxConfig],
) -> None:
    for mailbox in mailboxes:
        sync_inbox_for_mailbox(service, settings, headers, rows, mailbox)


def _defer_followup(
    service,
    settings: Settings,
    headers: list[str],
    row_number: int,
    row: dict[str, str],
    reason: str,
) -> None:
    if row.get("last_error", "") == reason:
        return
    row["last_error"] = reason[:500]
    update_row(service, settings.spreadsheet_id, QUEUE_SHEET, row_number, headers, row)
    log_event(service, settings, row, "followup_deferred", detail=reason)


def resolve_followup_mailbox(
    row: dict[str, str],
    *,
    configured: dict[str, MailboxConfig],
    enabled: list[MailboxConfig],
) -> tuple[MailboxConfig | None, str]:
    mailbox_id = (row.get("sender_mailbox_id", "") or "").strip()
    if not mailbox_id:
        if len(enabled) == 1:
            mailbox = enabled[0]
        else:
            return None, "follow-up requires sender_mailbox_id because multiple sending mailboxes are configured"
    else:
        mailbox = configured.get(mailbox_id)
        if mailbox is None:
            return None, f"assigned mailbox {mailbox_id} is no longer configured"
        if not mailbox.enabled:
            return None, f"assigned mailbox {mailbox_id} is disabled; follow-up remains paused"

    stored_sender = normalize_address(row.get("sender_email", ""))
    if stored_sender and stored_sender != normalize_address(mailbox.sender_email):
        return None, "assigned mailbox sender_email changed; manual reconciliation required before follow-up"
    return mailbox, ""


def process() -> int:
    settings = Settings.from_env()
    mailboxes = load_mailboxes_from_env(mode=settings.mode, default_daily_limit=settings.daily_send_limit)
    active_mailboxes = enabled_mailboxes(mailboxes)
    configured_mailboxes = mailbox_map(mailboxes)

    service = build_sheets_service()
    queue_headers, rows = rows_from_values(get_values(service, settings.spreadsheet_id, QUEUE_SHEET))
    ensure_expected_headers(queue_headers, QUEUE_HEADERS, QUEUE_SHEET)
    suppression_headers, suppression_rows = rows_from_values(get_values(service, settings.spreadsheet_id, SUPPRESSION_SHEET))
    ensure_expected_headers(suppression_headers, SUPPRESSION_HEADERS, SUPPRESSION_SHEET)
    log_headers, _ = rows_from_values(get_values(service, settings.spreadsheet_id, LOG_SHEET))
    ensure_expected_headers(log_headers, LOG_HEADERS, LOG_SHEET)

    sync_inboxes(service, settings, queue_headers, rows, active_mailboxes)
    if settings.mode == "live":
        queue_headers, rows = rows_from_values(get_values(service, settings.spreadsheet_id, QUEUE_SHEET))
        _, suppression_rows = rows_from_values(get_values(service, settings.spreadsheet_id, SUPPRESSION_SHEET))

    suppressed_emails, suppressed_domains = suppression_sets(suppression_rows)
    now = utcnow()
    send_count = count_sends_today(rows, now, settings.timezone_name)
    mailbox_counts = count_mailbox_sends_today(
        rows, now=now, timezone_name=settings.timezone_name, parse_dt=parse_dt
    )
    mailbox_last_sent = last_mailbox_send_times(rows, parse_dt=parse_dt)
    sends_this_run = 0
    if settings.mode == "live" and not within_send_window(now, settings.timezone_name, settings.send_window_start, settings.send_window_end):
        print("Outside configured send window; inbox sync completed, no outbound mail sent.")
        return 0

    for idx, row in enumerate(rows):
        action = next_action(row, now)
        if not action:
            continue
        errors = validate_row(row, action)
        if suppression_match(row.get("email", ""), suppressed_emails, suppressed_domains):
            errors.append("recipient is suppressed")
        if errors:
            if settings.mode == "validate":
                print(f"{row.get('lead_id', idx + 2)}: {'; '.join(errors)}")
            else:
                row.update(status="blocked", last_error="; ".join(errors)[:500])
                update_row(service, settings.spreadsheet_id, QUEUE_SHEET, idx + 2, queue_headers, row)
                log_event(service, settings, row, "blocked", detail=row["last_error"])
            continue

        if action == "initial" and not verification_is_fresh(row, now, settings.verification_max_age_days):
            if settings.mode == "validate":
                print(f"{row.get('lead_id')}: verification required")
            else:
                row.update(status="verification_pending", last_error="fresh verifier readback required")
                update_row(service, settings.spreadsheet_id, QUEUE_SHEET, idx + 2, queue_headers, row)
                log_event(service, settings, row, "verification_pending", detail=row["last_error"])
            continue

        if settings.mode != "live":
            continue
        if send_count >= settings.daily_send_limit or sends_this_run >= settings.max_sends_per_run:
            break

        if action == "initial":
            mailbox = choose_initial_mailbox(
                active_mailboxes,
                sent_today=mailbox_counts,
                last_sent_at=mailbox_last_sent,
                now=utcnow(),
                lead_id=row.get("lead_id", ""),
            )
            if mailbox is None:
                print(f"{row.get('lead_id')}: no sending mailbox currently has available capacity")
                continue
        else:
            mailbox, reason = resolve_followup_mailbox(
                row,
                configured=configured_mailboxes,
                enabled=active_mailboxes,
            )
            if mailbox is None:
                _defer_followup(service, settings, queue_headers, idx + 2, row, reason)
                continue
            if not mailbox_is_available(
                mailbox,
                sent_today=mailbox_counts.get(mailbox.mailbox_id, 0),
                last_sent_at=mailbox_last_sent.get(mailbox.mailbox_id),
                now=utcnow(),
            ):
                continue

        stage = 1 if action == "initial" else 2
        row.update(
            status="sending",
            stage=str(stage),
            last_error="",
            sender_mailbox_id=mailbox.mailbox_id,
            sender_email=mailbox.sender_email,
        )
        update_row(service, settings.spreadsheet_id, QUEUE_SHEET, idx + 2, queue_headers, row)
        try:
            msg = build_message(row, mailbox, stage)
            smtp_send(msg, mailbox)
            sent_time = utcnow()
            message_id = str(msg["Message-ID"])
            if stage == 1:
                row.update(status="sent", sent_at=iso(sent_time), message_id=message_id)
                if row.get("followup_body", "").strip():
                    delay = int(row.get("followup_delay_days", "3") or "3")
                    row["next_send_at"] = iso(sent_time + timedelta(days=max(1, delay)))
            else:
                row.update(status="followup_sent", followup_sent_at=iso(sent_time), followup_message_id=message_id, next_send_at="")
            update_row(service, settings.spreadsheet_id, QUEUE_SHEET, idx + 2, queue_headers, row)
            log_event(service, settings, row, row["status"], message_id=message_id, mailbox=mailbox)
            send_count += 1
            sends_this_run += 1
            mailbox_counts[mailbox.mailbox_id] = mailbox_counts.get(mailbox.mailbox_id, 0) + 1
            mailbox_last_sent[mailbox.mailbox_id] = sent_time
        except Exception as exc:
            row.update(status="error", last_error=f"{type(exc).__name__}: {exc}"[:500])
            update_row(service, settings.spreadsheet_id, QUEUE_SHEET, idx + 2, queue_headers, row)
            log_event(service, settings, row, "send_error", detail=row["last_error"], mailbox=mailbox)

    mailbox_summary = ",".join(
        f"{mailbox.mailbox_id}:{mailbox_counts.get(mailbox.mailbox_id, 0)}/{mailbox.daily_limit}"
        for mailbox in active_mailboxes
    )
    print(
        f"mode={settings.mode} rows={len(rows)} sends_this_run={sends_this_run} "
        f"sends_today={send_count} mailboxes={mailbox_summary}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(process())
