from __future__ import annotations

import imaplib
import ssl
import time
from typing import Callable

from outreach_imap_draft import DraftReceipt, build_draft_message, detect_drafts_folder


def _search_test_id(imap, folder: str, test_id: str) -> tuple[str, ...]:
    status, _ = imap.select(folder, readonly=True)
    if status != "OK":
        raise RuntimeError(f"failed to select draft folder for readback: {folder}")
    status, data = imap.search(None, "HEADER", "X-Webactueel-Draft-Test-ID", f'"{test_id}"')
    if status != "OK":
        raise RuntimeError("draft readback search failed")
    if not data or not data[0]:
        return ()
    return tuple(
        part.decode("ascii", errors="replace") if isinstance(part, bytes) else str(part)
        for part in data[0].split()
    )


def ensure_verified_draft(
    mailbox,
    *,
    recipient: str,
    subject: str,
    body: str,
    test_id: str,
    explicit_folder: str = "",
    imap_factory: Callable = imaplib.IMAP4_SSL,
    retries: int = 3,
    delay_seconds: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> DraftReceipt:
    """Converge on exactly one draft carrying test_id.

    A retry after a successful APPEND but failed downstream state write reuses the
    already-created draft. More than one matching draft is treated as corruption
    and fails closed instead of creating or deleting anything automatically.
    """
    if not getattr(mailbox, "mail_password", ""):
        raise RuntimeError("OUTREACH_MAIL_PASSWORD is required for IMAP draft creation")

    msg = build_draft_message(
        sender_name=mailbox.sender_name,
        sender_email=mailbox.sender_email,
        recipient=recipient,
        subject=subject,
        body=body,
        test_id=test_id,
    )

    imap = imap_factory(
        mailbox.imap_host,
        mailbox.imap_port,
        ssl_context=ssl.create_default_context(),
    )
    try:
        status, _ = imap.login(mailbox.mail_user, mailbox.mail_password)
        if status != "OK":
            raise RuntimeError("IMAP authentication failed")
        status, rows = imap.list()
        if status != "OK":
            raise RuntimeError("IMAP LIST failed")
        folder = detect_drafts_folder(rows or (), explicit_folder=explicit_folder)

        existing = _search_test_id(imap, folder, test_id)
        if len(existing) > 1:
            raise RuntimeError("multiple drafts already exist for the same idempotency key")
        if len(existing) == 1:
            return DraftReceipt(mailbox.mailbox_id, folder, test_id, existing)

        status, _ = imap.append(
            folder,
            r"(\Draft)",
            imaplib.Time2Internaldate(time.time()),
            msg.as_bytes(),
        )
        if status != "OK":
            raise RuntimeError(f"IMAP APPEND failed for draft folder: {folder}")

        attempts = max(1, min(int(retries), 10))
        delay = max(0.0, min(float(delay_seconds), 5.0))
        found: tuple[str, ...] = ()
        for attempt in range(attempts):
            found = _search_test_id(imap, folder, test_id)
            if found:
                break
            if attempt + 1 < attempts:
                sleep(delay)
        if len(found) != 1:
            if not found:
                raise RuntimeError("draft append succeeded but exact readback failed")
            raise RuntimeError("exact readback found multiple drafts for one idempotency key")
        return DraftReceipt(mailbox.mailbox_id, folder, test_id, found)
    finally:
        try:
            imap.logout()
        except Exception:
            pass
