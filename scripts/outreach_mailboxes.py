from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Iterable
from zoneinfo import ZoneInfo


MAILBOX_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off", ""}


@dataclass(frozen=True)
class MailboxConfig:
    mailbox_id: str
    enabled: bool
    smtp_host: str
    smtp_port: int
    imap_host: str
    imap_port: int
    mail_user: str
    mail_password: str
    sender_name: str
    sender_email: str
    daily_limit: int
    min_wait_minutes: int
    dkim_selector: str
    required_spf_token: str


def _parse_bool(value, *, default: bool = True, name: str = "enabled") -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be true or false")


def _normalize_email(value: str) -> str:
    value = (value or "").strip().lower()
    return value


def _domain_of(address: str) -> str:
    address = _normalize_email(address)
    return address.rsplit("@", 1)[1] if "@" in address else ""


def _int_value(value, *, default: int, name: str, minimum: int, maximum: int) -> int:
    parsed = default if value in (None, "") else int(value)
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _mailbox_from_mapping(
    item: dict,
    *,
    mode: str,
    default_daily_limit: int,
    default_sender_name: str,
    default_dkim_selector: str,
    default_spf_token: str,
) -> MailboxConfig:
    mailbox_id = str(item.get("id", item.get("mailbox_id", ""))).strip().lower()
    if not MAILBOX_ID_RE.fullmatch(mailbox_id):
        raise ValueError("mailbox id must match [a-z0-9][a-z0-9._-]{0,63}")

    sender_email = _normalize_email(str(item.get("sender_email", item.get("mail_user", ""))))
    mail_user = _normalize_email(str(item.get("mail_user", sender_email)))
    smtp_host = str(item.get("smtp_host", "")).strip()
    imap_host = str(item.get("imap_host", smtp_host)).strip()
    password = str(item.get("password", item.get("mail_password", "")))
    sender_name = str(item.get("sender_name", default_sender_name)).strip()
    enabled = _parse_bool(item.get("enabled"), default=True, name=f"mailbox {mailbox_id} enabled")
    smtp_port = _int_value(item.get("smtp_port"), default=587, name=f"mailbox {mailbox_id} smtp_port", minimum=1, maximum=65535)
    imap_port = _int_value(item.get("imap_port"), default=993, name=f"mailbox {mailbox_id} imap_port", minimum=1, maximum=65535)
    daily_limit = _int_value(
        item.get("daily_limit"),
        default=min(default_daily_limit, 30),
        name=f"mailbox {mailbox_id} daily_limit",
        minimum=1,
        maximum=100,
    )
    min_wait_minutes = _int_value(
        item.get("min_wait_minutes"),
        default=1,
        name=f"mailbox {mailbox_id} min_wait_minutes",
        minimum=1,
        maximum=120,
    )
    dkim_selector = str(item.get("dkim_selector", default_dkim_selector)).strip()
    required_spf_token = str(item.get("required_spf_token", default_spf_token)).strip()

    errors: list[str] = []
    if "@" not in sender_email:
        errors.append("sender_email must be a valid email address")
    if "@" not in mail_user:
        errors.append("mail_user must be a valid email address")
    if sender_email and mail_user and _domain_of(sender_email) != _domain_of(mail_user):
        errors.append("sender_email and mail_user must use the same domain")
    if not sender_name:
        errors.append("sender_name is required")
    if not smtp_host:
        errors.append("smtp_host is required")
    if smtp_port not in {465, 587}:
        errors.append("smtp_port must be 465 or 587")
    if not imap_host:
        errors.append("imap_host is required")
    if imap_port != 993:
        errors.append("imap_port must be 993")
    if mode == "live" and enabled and not password:
        errors.append("password is required for an enabled mailbox in live mode")
    if mode == "live" and enabled and not dkim_selector:
        errors.append("dkim_selector is required for an enabled mailbox in live mode")
    if required_spf_token and any(ch.isspace() for ch in required_spf_token):
        errors.append("required_spf_token must be one SPF token without whitespace")
    if errors:
        raise ValueError(f"mailbox {mailbox_id}: " + "; ".join(errors))

    return MailboxConfig(
        mailbox_id=mailbox_id,
        enabled=enabled,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        imap_host=imap_host,
        imap_port=imap_port,
        mail_user=mail_user,
        mail_password=password,
        sender_name=sender_name,
        sender_email=sender_email,
        daily_limit=daily_limit,
        min_wait_minutes=min_wait_minutes,
        dkim_selector=dkim_selector,
        required_spf_token=required_spf_token,
    )


def _legacy_mailbox(*, mode: str, default_daily_limit: int) -> MailboxConfig:
    return _mailbox_from_mapping(
        {
            "id": os.getenv("OUTREACH_MAILBOX_ID", "primary"),
            "enabled": True,
            "smtp_host": os.getenv("OUTREACH_SMTP_HOST", ""),
            "smtp_port": os.getenv("OUTREACH_SMTP_PORT", "587"),
            "imap_host": os.getenv("OUTREACH_IMAP_HOST", ""),
            "imap_port": os.getenv("OUTREACH_IMAP_PORT", "993"),
            "mail_user": os.getenv("OUTREACH_MAIL_USER", ""),
            "password": os.getenv("OUTREACH_MAIL_PASSWORD", ""),
            "sender_name": os.getenv("OUTREACH_SENDER_NAME", ""),
            "sender_email": os.getenv("OUTREACH_SENDER_EMAIL", ""),
            "daily_limit": os.getenv("OUTREACH_MAILBOX_DAILY_LIMIT", str(min(default_daily_limit, 30))),
            "min_wait_minutes": os.getenv("OUTREACH_MAILBOX_MIN_WAIT_MINUTES", "1"),
            "dkim_selector": os.getenv("OUTREACH_DKIM_SELECTOR", ""),
            "required_spf_token": os.getenv("OUTREACH_REQUIRED_SPF_TOKEN", ""),
        },
        mode=mode,
        default_daily_limit=default_daily_limit,
        default_sender_name=os.getenv("OUTREACH_SENDER_NAME", ""),
        default_dkim_selector=os.getenv("OUTREACH_DKIM_SELECTOR", ""),
        default_spf_token=os.getenv("OUTREACH_REQUIRED_SPF_TOKEN", ""),
    )


def load_mailboxes_from_env(*, mode: str, default_daily_limit: int) -> list[MailboxConfig]:
    raw = os.getenv("OUTREACH_MAILBOXES_JSON", "").strip()
    if not raw:
        mailboxes = [_legacy_mailbox(mode=mode, default_daily_limit=default_daily_limit)]
    else:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("OUTREACH_MAILBOXES_JSON must contain valid JSON") from exc
        if isinstance(payload, dict):
            payload = payload.get("mailboxes")
        if not isinstance(payload, list) or not payload:
            raise ValueError("OUTREACH_MAILBOXES_JSON must be a non-empty array or an object with a non-empty mailboxes array")
        defaults = {
            "default_sender_name": os.getenv("OUTREACH_SENDER_NAME", ""),
            "default_dkim_selector": os.getenv("OUTREACH_DKIM_SELECTOR", ""),
            "default_spf_token": os.getenv("OUTREACH_REQUIRED_SPF_TOKEN", ""),
        }
        mailboxes = [
            _mailbox_from_mapping(
                item,
                mode=mode,
                default_daily_limit=default_daily_limit,
                **defaults,
            )
            for item in payload
            if isinstance(item, dict)
        ]
        if len(mailboxes) != len(payload):
            raise ValueError("every mailbox entry must be a JSON object")

    ids: set[str] = set()
    senders: set[str] = set()
    users: set[str] = set()
    enabled_count = 0
    for mailbox in mailboxes:
        if mailbox.mailbox_id in ids:
            raise ValueError(f"duplicate mailbox id: {mailbox.mailbox_id}")
        ids.add(mailbox.mailbox_id)
        if mailbox.sender_email in senders:
            raise ValueError(f"duplicate sender_email: {mailbox.sender_email}")
        senders.add(mailbox.sender_email)
        if mailbox.mail_user in users:
            raise ValueError(f"duplicate mail_user: {mailbox.mail_user}")
        users.add(mailbox.mail_user)
        if mailbox.enabled:
            enabled_count += 1
    if enabled_count == 0:
        raise ValueError("at least one mailbox must be enabled")
    return mailboxes


def enabled_mailboxes(mailboxes: Iterable[MailboxConfig]) -> list[MailboxConfig]:
    return [mailbox for mailbox in mailboxes if mailbox.enabled]


def mailbox_map(mailboxes: Iterable[MailboxConfig]) -> dict[str, MailboxConfig]:
    return {mailbox.mailbox_id: mailbox for mailbox in mailboxes}


def mailbox_is_available(
    mailbox: MailboxConfig,
    *,
    sent_today: int,
    last_sent_at: datetime | None,
    now: datetime,
) -> bool:
    if not mailbox.enabled or sent_today >= mailbox.daily_limit:
        return False
    if last_sent_at is None:
        return True
    return now - last_sent_at >= timedelta(minutes=mailbox.min_wait_minutes)


def choose_initial_mailbox(
    mailboxes: Iterable[MailboxConfig],
    *,
    sent_today: dict[str, int],
    last_sent_at: dict[str, datetime | None],
    now: datetime,
    lead_id: str,
) -> MailboxConfig | None:
    candidates = [
        mailbox
        for mailbox in mailboxes
        if mailbox_is_available(
            mailbox,
            sent_today=sent_today.get(mailbox.mailbox_id, 0),
            last_sent_at=last_sent_at.get(mailbox.mailbox_id),
            now=now,
        )
    ]
    if not candidates:
        return None

    def key(mailbox: MailboxConfig):
        count = sent_today.get(mailbox.mailbox_id, 0)
        utilization = count / mailbox.daily_limit
        last = last_sent_at.get(mailbox.mailbox_id) or datetime.min.replace(tzinfo=timezone.utc)
        tie = sha256(f"{lead_id}:{mailbox.mailbox_id}".encode("utf-8")).hexdigest()
        return (utilization, count, last, tie)

    return min(candidates, key=key)


def count_mailbox_sends_today(
    rows: Iterable[dict[str, str]],
    *,
    now: datetime,
    timezone_name: str,
    parse_dt,
) -> dict[str, int]:
    tz = ZoneInfo(timezone_name)
    today = now.astimezone(tz).date()
    counts: dict[str, int] = {}
    for row in rows:
        mailbox_id = (row.get("sender_mailbox_id", "") or "").strip()
        if not mailbox_id:
            continue
        for key in ("sent_at", "followup_sent_at"):
            dt = parse_dt(row.get(key, ""))
            if dt and dt.astimezone(tz).date() == today:
                counts[mailbox_id] = counts.get(mailbox_id, 0) + 1
    return counts


def last_mailbox_send_times(rows: Iterable[dict[str, str]], *, parse_dt) -> dict[str, datetime | None]:
    latest: dict[str, datetime | None] = {}
    for row in rows:
        mailbox_id = (row.get("sender_mailbox_id", "") or "").strip()
        if not mailbox_id:
            continue
        for key in ("sent_at", "followup_sent_at"):
            dt = parse_dt(row.get(key, ""))
            if dt and (latest.get(mailbox_id) is None or dt > latest[mailbox_id]):
                latest[mailbox_id] = dt
    return latest
