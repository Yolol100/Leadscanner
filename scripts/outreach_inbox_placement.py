from __future__ import annotations

import imaplib
import json
import os
import re
import ssl
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from typing import Callable, Iterable

from outreach_mailboxes import enabled_mailboxes, load_mailboxes_from_env
from outreach_reporting import replace_sheet_rows
from outreach_sender import build_sheets_service, ensure_expected_headers, get_values, rows_from_values, smtp_send

PLACEMENT_SHEET = "InboxPlacement"
PLACEMENT_HEADERS = [
    "generated_at", "test_id", "seed_id", "recipient_email", "recipient_domain",
    "result", "checked_folders", "note",
]
HARD_MAX_SEEDS = 5
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off", ""}


class PlacementError(RuntimeError):
    pass


@dataclass(frozen=True)
class SeedInbox:
    seed_id: str
    email: str
    imap_host: str
    imap_port: int
    username: str
    password: str
    spam_folders: tuple[str, ...] = ("Junk", "Spam")


def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise PlacementError(f"{name} must be true or false")


def _valid_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", (value or "").strip().lower()))


def load_seeds(raw: str | None = None, *, require_credentials: bool = False) -> list[SeedInbox]:
    raw = raw if raw is not None else os.getenv("OUTREACH_SEED_INBOXES_JSON", "")
    if not (raw or "").strip():
        if require_credentials:
            raise PlacementError("OUTREACH_SEED_INBOXES_JSON is required for placement test mode")
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PlacementError("OUTREACH_SEED_INBOXES_JSON must be valid JSON") from exc
    if not isinstance(parsed, list):
        raise PlacementError("OUTREACH_SEED_INBOXES_JSON must be a JSON array")
    if not 1 <= len(parsed) <= HARD_MAX_SEEDS:
        raise PlacementError(f"seed inbox count must be between 1 and {HARD_MAX_SEEDS}")
    output: list[SeedInbox] = []
    seen_ids: set[str] = set()
    seen_emails: set[str] = set()
    for index, item in enumerate(parsed, 1):
        if not isinstance(item, dict):
            raise PlacementError(f"seed item {index} must be an object")
        seed_id = str(item.get("seed_id") or f"seed-{index}").strip()
        address = str(item.get("email") or "").strip().lower()
        host = str(item.get("imap_host") or "").strip()
        username = str(item.get("username") or item.get("mail_user") or address).strip()
        password = str(item.get("password") or "")
        try:
            port = int(item.get("imap_port") or 993)
        except (TypeError, ValueError) as exc:
            raise PlacementError(f"seed {seed_id}: invalid imap_port") from exc
        spam = item.get("spam_folders") or [item.get("spam_folder") or "Junk", "Spam"]
        if isinstance(spam, str):
            spam = [spam]
        spam_folders = tuple(str(value).strip() for value in spam if str(value).strip())[:4]
        if not seed_id or seed_id in seen_ids:
            raise PlacementError("seed_id values must be unique and non-empty")
        if not _valid_email(address) or address in seen_emails:
            raise PlacementError("seed email values must be unique valid addresses")
        if port != 993:
            raise PlacementError(f"seed {seed_id}: imap_port must be 993")
        if require_credentials and (not host or not username or not password):
            raise PlacementError(f"seed {seed_id}: imap_host, username and password are required in test mode")
        seen_ids.add(seed_id)
        seen_emails.add(address)
        output.append(SeedInbox(seed_id, address, host, port, username, password, spam_folders))
    return output


def build_probe(sender_email: str, sender_name: str, seed: SeedInbox, test_id: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"{sender_name} <{sender_email}>" if sender_name else sender_email
    msg["To"] = seed.email
    msg["Subject"] = f"Webactueel placement probe {test_id[:8]}"
    msg["Date"] = format_datetime(datetime.now(timezone.utc))
    msg["X-Webactueel-Placement-ID"] = test_id
    msg.set_content("Controlled Webactueel inbox-placement probe. This message is sent only to a configured seed inbox.\n" f"Placement-ID: {test_id}\n")
    return msg


def _decode_header_value(value: bytes | str | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def _folder_contains_token(imap, folder: str, test_id: str) -> bool:
    status, _ = imap.select(f'"{folder}"', readonly=True)
    if status != "OK":
        return False
    status, data = imap.search(None, "HEADER", "X-Webactueel-Placement-ID", f'"{test_id}"')
    if status == "OK" and data and data[0].strip():
        return True
    status, ids = imap.search(None, "ALL")
    if status != "OK" or not ids or not ids[0]:
        return False
    recent = ids[0].split()[-25:]
    for message_id in reversed(recent):
        status, payload = imap.fetch(message_id, "(BODY.PEEK[HEADER.FIELDS (X-Webactueel-Placement-ID)])")
        if status != "OK":
            continue
        for part in payload or []:
            if isinstance(part, tuple) and test_id in _decode_header_value(part[1]):
                return True
    return False


def locate_seed_message(seed: SeedInbox, test_id: str, *, imap_factory: Callable = imaplib.IMAP4_SSL) -> tuple[str, str]:
    context = ssl.create_default_context()
    with imap_factory(seed.imap_host, seed.imap_port, ssl_context=context) as imap:
        imap.login(seed.username, seed.password)
        if _folder_contains_token(imap, "INBOX", test_id):
            return "inbox", "INBOX"
        checked = ["INBOX"]
        for folder in seed.spam_folders:
            if not folder or folder.upper() == "INBOX":
                continue
            checked.append(folder)
            if _folder_contains_token(imap, folder, test_id):
                return "spam", ",".join(checked)
        return "missing", ",".join(checked)


def _test_rows(seeds: Iterable[SeedInbox], mailbox, *, test_id: str, poll_seconds: int, max_wait_seconds: int, send: Callable = smtp_send, locator: Callable[[SeedInbox, str], tuple[str, str]] = locate_seed_message) -> list[dict[str, str]]:
    seeds = list(seeds)
    for seed in seeds:
        send(build_probe(mailbox.sender_email, mailbox.sender_name, seed, test_id), mailbox)
    unresolved = {seed.seed_id: seed for seed in seeds}
    results: dict[str, tuple[str, str, str]] = {}
    deadline = time.monotonic() + max_wait_seconds
    while unresolved:
        for seed_id, seed in list(unresolved.items()):
            try:
                result, folders = locator(seed, test_id)
            except Exception as exc:
                if time.monotonic() >= deadline:
                    results[seed_id] = ("error", "", f"IMAP placement readback failed: {type(exc).__name__}: {exc}")
                    unresolved.pop(seed_id, None)
                continue
            if result in {"inbox", "spam"}:
                results[seed_id] = (result, folders, "seed message located")
                unresolved.pop(seed_id, None)
            elif time.monotonic() >= deadline:
                results[seed_id] = ("missing", folders, "seed message not located before bounded timeout")
                unresolved.pop(seed_id, None)
        if unresolved and time.monotonic() < deadline:
            time.sleep(poll_seconds)
    generated_at = utc_iso()
    rows: list[dict[str, str]] = []
    for seed in seeds:
        result, folders, note = results[seed.seed_id]
        rows.append({
            "generated_at": generated_at, "test_id": test_id, "seed_id": seed.seed_id,
            "recipient_email": seed.email, "recipient_domain": seed.email.rsplit("@", 1)[1],
            "result": result, "checked_folders": folders, "note": note,
        })
    return rows


def run(mode: str | None = None) -> list[dict[str, str]]:
    mode = (mode or os.getenv("OUTREACH_PLACEMENT_MODE", "validate")).strip().lower()
    if mode not in {"validate", "test"}:
        raise PlacementError("OUTREACH_PLACEMENT_MODE must be validate or test")
    spreadsheet_id = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        raise PlacementError("OUTREACH_SPREADSHEET_ID is required")
    if not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise PlacementError("GOOGLE_SERVICE_ACCOUNT_JSON is required")
    seeds = load_seeds(require_credentials=(mode == "test"))
    service = build_sheets_service()
    headers, _ = rows_from_values(get_values(service, spreadsheet_id, PLACEMENT_SHEET))
    ensure_expected_headers(headers, PLACEMENT_HEADERS, PLACEMENT_SHEET)
    if mode == "validate":
        print(f"INBOX_PLACEMENT=validated configured_seeds={len(seeds)} no_message_sent=true")
        return []
    if not env_bool("OUTREACH_PLACEMENT_TEST_ENABLED", False):
        raise PlacementError("OUTREACH_PLACEMENT_TEST_ENABLED=true is required for controlled seed test mode")
    daily_limit = int(os.getenv("OUTREACH_DAILY_LIMIT", "20") or "20")
    mailboxes = enabled_mailboxes(load_mailboxes_from_env(mode="live", default_daily_limit=daily_limit))
    if len(mailboxes) != 1:
        raise PlacementError("placement test requires exactly one enabled sender mailbox")
    mailbox = mailboxes[0]
    poll_seconds = max(2, min(int(os.getenv("OUTREACH_PLACEMENT_POLL_SECONDS", "10") or "10"), 30))
    max_wait = max(10, min(int(os.getenv("OUTREACH_PLACEMENT_MAX_WAIT_SECONDS", "60") or "60"), 180))
    test_id = "placement-" + uuid.uuid4().hex
    rows = _test_rows(seeds, mailbox, test_id=test_id, poll_seconds=poll_seconds, max_wait_seconds=max_wait)
    replace_sheet_rows(service, spreadsheet_id, PLACEMENT_SHEET, PLACEMENT_HEADERS, rows)
    inbox = sum(1 for row in rows if row["result"] == "inbox")
    spam = sum(1 for row in rows if row["result"] == "spam")
    missing = sum(1 for row in rows if row["result"] == "missing")
    errors = sum(1 for row in rows if row["result"] == "error")
    print(f"INBOX_PLACEMENT=complete seeds={len(rows)} inbox={inbox} spam={spam} missing={missing} errors={errors}")
    return rows


def main() -> int:
    try:
        run()
    except (PlacementError, RuntimeError, ValueError) as exc:
        print(f"INBOX_PLACEMENT=blocked detail={exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
