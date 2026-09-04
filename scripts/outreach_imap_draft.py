from __future__ import annotations

import imaplib
import os
import re
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate, make_msgid
from typing import Callable, Iterable

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off", ""}
COMMON_DRAFT_NAMES = {"draft", "drafts", "concept", "concepten"}
SAFE_TEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")


@dataclass(frozen=True)
class DraftReceipt:
    mailbox_id: str
    folder: str
    test_id: str
    message_ids: tuple[str, ...]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be true or false")


def _normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def choose_mailbox(mailboxes: Iterable, mailbox_id: str = ""):
    active = [mailbox for mailbox in mailboxes if getattr(mailbox, "enabled", True)]
    if not active:
        raise RuntimeError("no enabled mailbox configured")
    requested = (mailbox_id or "").strip().lower()
    if requested:
        matches = [mailbox for mailbox in active if mailbox.mailbox_id == requested]
        if len(matches) != 1:
            raise RuntimeError(f"requested mailbox not found: {requested}")
        return matches[0]
    if len(active) != 1:
        raise RuntimeError("OUTREACH_DRAFT_MAILBOX_ID is required when multiple mailboxes are enabled")
    return active[0]


def _unquote_mailbox_name(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1].replace(r'\"', '"').replace(r'\\', '\\')
    return value


def parse_list_line(raw: bytes | str) -> tuple[set[str], str]:
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    text = text.strip()
    match = re.match(r"^\((?P<flags>[^)]*)\)\s+(?P<delimiter>NIL|\"(?:\\.|[^\"])*\")\s+(?P<name>.+)$", text)
    if not match:
        raise ValueError(f"unsupported IMAP LIST response: {text!r}")
    flags = {part.casefold() for part in match.group("flags").split() if part}
    return flags, _unquote_mailbox_name(match.group("name"))


def _draft_name_score(name: str) -> int:
    normalized = name.strip().casefold()
    if normalized in COMMON_DRAFT_NAMES:
        return 30
    basename = re.split(r"[/.]", normalized)[-1]
    if basename in COMMON_DRAFT_NAMES:
        return 20
    if "draft" in basename or "concept" in basename:
        return 10
    return 0


def detect_drafts_folder(list_rows: Iterable[bytes | str], explicit_folder: str = "") -> str:
    parsed: list[tuple[set[str], str]] = []
    for row in list_rows:
        if row in (None, b"", ""):
            continue
        parsed.append(parse_list_line(row))
    if not parsed:
        raise RuntimeError("IMAP LIST returned no mail folders")

    explicit = (explicit_folder or "").strip()
    if explicit:
        matches = [name for _flags, name in parsed if name == explicit]
        if len(matches) != 1:
            raise RuntimeError(f"configured draft folder not found exactly once: {explicit}")
        return matches[0]

    special = [name for flags, name in parsed if r"\drafts" in flags]
    if len(special) == 1:
        return special[0]
    if len(special) > 1:
        raise RuntimeError("multiple IMAP folders advertise the \\Drafts special-use flag")

    scored = [(_draft_name_score(name), name) for _flags, name in parsed if _draft_name_score(name) > 0]
    if not scored:
        raise RuntimeError("no Drafts/Concepten IMAP folder could be detected")
    best = max(score for score, _name in scored)
    winners = [name for score, name in scored if score == best]
    if len(winners) != 1:
        raise RuntimeError("draft folder detection is ambiguous; set OUTREACH_DRAFT_FOLDER explicitly")
    return winners[0]


def build_draft_message(*, sender_name: str, sender_email: str, recipient: str, subject: str, body: str, test_id: str) -> EmailMessage:
    sender_email = _normalize_email(sender_email)
    recipient = _normalize_email(recipient)
    subject = (subject or "").strip()
    body = body or ""
    if "@" not in sender_email:
        raise ValueError("sender email is invalid")
    if "@" not in recipient:
        raise ValueError("draft recipient is invalid")
    if not subject or len(subject) > 200 or "\n" in subject or "\r" in subject:
        raise ValueError("draft subject must be 1-200 characters without newlines")
    if not body.strip() or len(body) > 20000:
        raise ValueError("draft body must be 1-20000 characters")
    if not SAFE_TEST_ID.fullmatch(test_id or ""):
        raise ValueError("draft test id contains unsupported characters")

    msg = EmailMessage(policy=SMTP)
    msg["From"] = f"{sender_name} <{sender_email}>" if sender_name.strip() else sender_email
    msg["To"] = recipient
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=sender_email.rsplit("@", 1)[1])
    msg["X-Webactueel-Draft-Test-ID"] = test_id
    msg["X-Webactueel-Transport"] = "imap-draft-only"
    msg.set_content(body)
    return msg


def _verify_draft(imap, folder: str, test_id: str, *, retries: int, delay_seconds: float, sleep: Callable[[float], None]) -> tuple[str, ...]:
    status, _ = imap.select(folder, readonly=True)
    if status != "OK":
        raise RuntimeError(f"failed to select draft folder for readback: {folder}")
    for attempt in range(retries):
        status, data = imap.search(None, "HEADER", "X-Webactueel-Draft-Test-ID", f'"{test_id}"')
        if status == "OK" and data and data[0]:
            ids = tuple(part.decode("ascii", errors="replace") if isinstance(part, bytes) else str(part) for part in data[0].split())
            if ids:
                return ids
        if attempt + 1 < retries:
            sleep(delay_seconds)
    raise RuntimeError("draft append succeeded but readback by unique test id failed")


def append_verified_draft(
    mailbox,
    *,
    recipient: str,
    subject: str,
    body: str,
    test_id: str,
    explicit_folder: str = "",
    self_only: bool = True,
    imap_factory: Callable = imaplib.IMAP4_SSL,
    retries: int = 3,
    delay_seconds: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> DraftReceipt:
    if not getattr(mailbox, "mail_password", ""):
        raise RuntimeError("OUTREACH_MAIL_PASSWORD is required for IMAP draft creation")
    recipient = _normalize_email(recipient)
    if self_only and recipient != _normalize_email(mailbox.sender_email):
        raise RuntimeError("draft test is self-only; recipient must equal OUTREACH_SENDER_EMAIL")

    msg = build_draft_message(
        sender_name=mailbox.sender_name,
        sender_email=mailbox.sender_email,
        recipient=recipient,
        subject=subject,
        body=body,
        test_id=test_id,
    )
    context = ssl.create_default_context()
    imap = imap_factory(mailbox.imap_host, mailbox.imap_port, ssl_context=context)
    try:
        status, _ = imap.login(mailbox.mail_user, mailbox.mail_password)
        if status != "OK":
            raise RuntimeError("IMAP authentication failed")
        status, rows = imap.list()
        if status != "OK":
            raise RuntimeError("IMAP LIST failed")
        folder = detect_drafts_folder(rows or (), explicit_folder=explicit_folder)
        status, _ = imap.append(folder, r"(\Draft)", imaplib.Time2Internaldate(time.time()), msg.as_bytes(policy=SMTP))
        if status != "OK":
            raise RuntimeError(f"IMAP APPEND failed for draft folder: {folder}")
        message_ids = _verify_draft(
            imap,
            folder,
            test_id,
            retries=max(1, min(int(retries), 10)),
            delay_seconds=max(0.0, min(float(delay_seconds), 5.0)),
            sleep=sleep,
        )
        return DraftReceipt(mailbox.mailbox_id, folder, test_id, message_ids)
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def run_from_env() -> DraftReceipt:
    if not _env_bool("OUTREACH_DRAFT_CONFIRM", False):
        raise RuntimeError("OUTREACH_DRAFT_CONFIRM=true is required")
    from outreach_mailboxes import enabled_mailboxes, load_mailboxes_from_env

    daily_limit = int(os.getenv("OUTREACH_DAILY_LIMIT", "20") or "20")
    mailboxes = enabled_mailboxes(load_mailboxes_from_env(mode="validate", default_daily_limit=daily_limit))
    mailbox = choose_mailbox(mailboxes, os.getenv("OUTREACH_DRAFT_MAILBOX_ID", ""))
    recipient = os.getenv("OUTREACH_DRAFT_TO", mailbox.sender_email)
    test_id = os.getenv("OUTREACH_DRAFT_TEST_ID", "").strip()
    subject = os.getenv("OUTREACH_DRAFT_SUBJECT", "").strip()
    body = os.getenv("OUTREACH_DRAFT_BODY", "")
    explicit_folder = os.getenv("OUTREACH_DRAFT_FOLDER", "")
    self_only = _env_bool("OUTREACH_DRAFT_SELF_ONLY", True)
    retries = int(os.getenv("OUTREACH_DRAFT_VERIFY_RETRIES", "3") or "3")
    delay = float(os.getenv("OUTREACH_DRAFT_VERIFY_DELAY_SECONDS", "1") or "1")
    return append_verified_draft(
        mailbox,
        recipient=recipient,
        subject=subject,
        body=body,
        test_id=test_id,
        explicit_folder=explicit_folder,
        self_only=self_only,
        retries=retries,
        delay_seconds=delay,
    )


def main() -> int:
    try:
        receipt = run_from_env()
    except (RuntimeError, ValueError, OSError, imaplib.IMAP4.error) as exc:
        print(f"MYHOST_DRAFT=blocked detail={exc}")
        return 2
    print(
        "MYHOST_DRAFT=green "
        f"mailbox={receipt.mailbox_id} folder={receipt.folder} test_id={receipt.test_id} "
        f"readback_count={len(receipt.message_ids)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
