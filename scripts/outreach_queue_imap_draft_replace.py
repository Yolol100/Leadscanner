from __future__ import annotations

import argparse
import imaplib
import os
import ssl
import time
from dataclasses import dataclass
from email.policy import SMTP
from typing import Callable

from outreach_imap_draft import SAFE_TEST_ID, build_draft_message, choose_mailbox, detect_drafts_folder
from outreach_mailboxes import enabled_mailboxes, load_mailboxes_from_env
from outreach_queue_imap_draft import (
    QUEUE_SHEET,
    SUPPRESSION_SHEET,
    build_sheets_service,
    get_values,
    inject_private_postal_for_draft,
    resolve_queue_row,
    suppression_sets,
    validate_queue_row,
)


@dataclass(frozen=True)
class DraftReplacementReceipt:
    mailbox_id: str
    folder: str
    old_test_id: str
    new_test_id: str
    new_message_ids: tuple[str, ...]


def _search_ids(imap, header: str, value: str) -> tuple[str, ...]:
    status, data = imap.search(None, "HEADER", header, f'"{value}"')
    if status != "OK":
        raise RuntimeError(f"IMAP search failed for {header}")
    if not data or not data[0]:
        return ()
    return tuple(part.decode("ascii", errors="replace") if isinstance(part, bytes) else str(part) for part in data[0].split())


def replace_verified_draft(
    mailbox,
    *,
    recipient: str,
    subject: str,
    body: str,
    old_test_id: str,
    new_test_id: str,
    explicit_folder: str = "",
    imap_factory: Callable = imaplib.IMAP4_SSL,
) -> DraftReplacementReceipt:
    if not getattr(mailbox, "mail_password", ""):
        raise RuntimeError("OUTREACH_MAIL_PASSWORD is required for IMAP draft replacement")
    if not SAFE_TEST_ID.fullmatch(old_test_id or "") or not SAFE_TEST_ID.fullmatch(new_test_id or ""):
        raise ValueError("draft test id contains unsupported characters")
    if old_test_id == new_test_id:
        raise ValueError("old and new draft test IDs must differ")

    msg = build_draft_message(
        sender_name=mailbox.sender_name,
        sender_email=mailbox.sender_email,
        recipient=recipient,
        subject=subject,
        body=body,
        test_id=new_test_id,
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
        status, _ = imap.select(folder, readonly=False)
        if status != "OK":
            raise RuntimeError(f"failed to select draft folder: {folder}")

        old_ids = _search_ids(imap, "X-Webactueel-Draft-Test-ID", old_test_id)
        if len(old_ids) != 1:
            raise RuntimeError(f"expected exactly one old draft by unique test id; found {len(old_ids)}")
        if _search_ids(imap, "X-Webactueel-Draft-Test-ID", new_test_id):
            raise RuntimeError("new draft test id already exists; refusing duplicate append")

        status, _ = imap.append(folder, r"(\Draft)", imaplib.Time2Internaldate(time.time()), msg.as_bytes(policy=SMTP))
        if status != "OK":
            raise RuntimeError("IMAP APPEND failed for replacement draft")
        status, _ = imap.select(folder, readonly=False)
        if status != "OK":
            raise RuntimeError("failed to reselect draft folder after replacement append")
        new_ids = _search_ids(imap, "X-Webactueel-Draft-Test-ID", new_test_id)
        if len(new_ids) != 1:
            raise RuntimeError(f"replacement append readback expected one new draft; found {len(new_ids)}")

        status, _ = imap.store(old_ids[0], "+FLAGS", r"(\Deleted)")
        if status != "OK":
            raise RuntimeError("replacement draft is verified but old draft could not be marked deleted")
        status, _ = imap.expunge()
        if status != "OK":
            raise RuntimeError("replacement draft is verified but old draft expunge failed")
        status, _ = imap.select(folder, readonly=True)
        if status != "OK":
            raise RuntimeError("failed to select draft folder for final replacement readback")
        if _search_ids(imap, "X-Webactueel-Draft-Test-ID", old_test_id):
            raise RuntimeError("old draft still exists after replacement cleanup")
        final_new_ids = _search_ids(imap, "X-Webactueel-Draft-Test-ID", new_test_id)
        if len(final_new_ids) != 1:
            raise RuntimeError("new replacement draft missing or duplicated after cleanup")
        return DraftReplacementReceipt(mailbox.mailbox_id, folder, old_test_id, new_test_id, final_new_ids)
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def replace_queue_draft(*, lead_id: str, old_test_id: str, new_test_id: str, spreadsheet_id: str):
    if not spreadsheet_id.strip():
        raise RuntimeError("OUTREACH_SPREADSHEET_ID is required")
    service = build_sheets_service()
    row = resolve_queue_row(get_values(service, spreadsheet_id, QUEUE_SHEET), lead_id)
    suppressed_emails, suppressed_domains = suppression_sets(get_values(service, spreadsheet_id, SUPPRESSION_SHEET))
    daily_limit = int(os.getenv("OUTREACH_DAILY_LIMIT", "20") or "20")
    mailboxes = enabled_mailboxes(load_mailboxes_from_env(mode="validate", default_daily_limit=daily_limit))
    mailbox = choose_mailbox(mailboxes, os.getenv("OUTREACH_DRAFT_MAILBOX_ID", ""))
    errors = validate_queue_row(
        row,
        sender_email=mailbox.sender_email,
        suppressed_emails=suppressed_emails,
        suppressed_domains=suppressed_domains,
    )
    # Replacement is a draft-only edit, not a send authorization. Existing
    # manual-review drafts must remain editable without changing their
    # compliance state to approved. All other queue/suppression gates remain.
    if row.get("compliance_status", "").strip().lower() == "manual_review":
        errors = [error for error in errors if error != "compliance_status is not approved"]
    if errors:
        raise RuntimeError("; ".join(errors))
    body = inject_private_postal_for_draft(row, row["body"])
    return replace_verified_draft(
        mailbox,
        recipient=row["email"],
        subject=row["subject"],
        body=body,
        old_test_id=old_test_id,
        new_test_id=new_test_id,
        explicit_folder=os.getenv("OUTREACH_DRAFT_FOLDER", ""),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Replace exactly one verified mijn.host queue draft without SMTP")
    parser.add_argument("--lead-id", required=True)
    parser.add_argument("--replace-test-id", required=True)
    args = parser.parse_args()
    try:
        receipt = replace_queue_draft(
            lead_id=args.lead_id.strip(),
            old_test_id=args.replace_test_id.strip(),
            new_test_id=os.getenv("OUTREACH_DRAFT_TEST_ID", "").strip(),
            spreadsheet_id=os.getenv("OUTREACH_SPREADSHEET_ID", ""),
        )
    except (RuntimeError, ValueError, OSError, imaplib.IMAP4.error) as exc:
        print(f"MYHOST_QUEUE_DRAFT_REPLACE=blocked detail={exc}")
        return 2
    print(
        "MYHOST_QUEUE_DRAFT_REPLACE=green "
        f"lead_id={args.lead_id.strip()} mailbox={receipt.mailbox_id} folder={receipt.folder} "
        f"old_test_id={receipt.old_test_id} new_test_id={receipt.new_test_id} "
        f"readback_count={len(receipt.new_message_ids)} smtp_send=not_invoked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())