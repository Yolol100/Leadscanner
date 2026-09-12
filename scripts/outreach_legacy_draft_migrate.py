from __future__ import annotations

import argparse
import os
import ssl

import outreach_queue_imap_draft_sync as sync
from outreach_imap_draft import SAFE_TEST_ID, choose_mailbox, detect_drafts_folder
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

ALLOWED_DRAFT_COMPLIANCE = {"manual_review", "approved"}


def _validate_row(row: dict[str, str], mailbox, suppressed_emails: set[str], suppressed_domains: set[str]) -> None:
    compliance = row.get("compliance_status", "").strip().lower()
    errors = validate_queue_row(
        row,
        sender_email=mailbox.sender_email,
        suppressed_emails=suppressed_emails,
        suppressed_domains=suppressed_domains,
    )
    if compliance in ALLOWED_DRAFT_COMPLIANCE:
        errors = [error for error in errors if error != "compliance_status is not approved"]
    else:
        errors.append("compliance_status is not draft-edit eligible")
    if errors:
        raise RuntimeError("; ".join(sorted(set(errors))))


def migrate(*, lead_id: str, spreadsheet_id: str, test_id: str, apply: bool) -> dict[str, str | int]:
    if not spreadsheet_id.strip():
        raise RuntimeError("OUTREACH_SPREADSHEET_ID is required")
    if not SAFE_TEST_ID.fullmatch(test_id or ""):
        raise RuntimeError("OUTREACH_DRAFT_TEST_ID is missing or invalid")

    service = build_sheets_service()
    row = resolve_queue_row(get_values(service, spreadsheet_id, QUEUE_SHEET), lead_id)
    suppressed_emails, suppressed_domains = suppression_sets(get_values(service, spreadsheet_id, SUPPRESSION_SHEET))

    daily_limit = int(os.getenv("OUTREACH_DAILY_LIMIT", "100") or "100")
    mailboxes = enabled_mailboxes(load_mailboxes_from_env(mode="validate", default_daily_limit=daily_limit))
    mailbox = choose_mailbox(mailboxes, os.getenv("OUTREACH_DRAFT_MAILBOX_ID", ""))
    _validate_row(row, mailbox, suppressed_emails, suppressed_domains)

    if not getattr(mailbox, "mail_password", ""):
        raise RuntimeError("OUTREACH_MAIL_PASSWORD is required for IMAP draft migration")

    recipient = sync._normalize_email(row.get("email", ""))
    desired_body = inject_private_postal_for_draft(row, row.get("body", ""))
    context = ssl.create_default_context()
    imap = sync.imaplib.IMAP4_SSL(mailbox.imap_host, mailbox.imap_port, ssl_context=context)
    try:
        status, _ = imap.login(mailbox.mail_user, mailbox.mail_password)
        if status != "OK":
            raise RuntimeError("IMAP authentication failed")
        status, folders = imap.list()
        if status != "OK":
            raise RuntimeError("IMAP LIST failed")
        folder = detect_drafts_folder(folders or (), explicit_folder=os.getenv("OUTREACH_DRAFT_FOLDER", ""))
        status, _ = imap.select(folder, readonly=False)
        if status != "OK":
            raise RuntimeError(f"failed to select Drafts folder: {folder}")

        existing = sync._scan_sender_drafts(imap, mailbox.sender_email, {recipient}).get(recipient, [])
        if len(existing) != 1:
            raise RuntimeError(f"expected exactly one sender draft for recipient; found {len(existing)}")
        old = existing[0]
        if old.test_id and SAFE_TEST_ID.fullmatch(old.test_id):
            raise RuntimeError("existing draft already has a safe Webactueel draft test id; use normal sync")
        if old.transport not in {"", "imap-draft-only"}:
            raise RuntimeError("existing legacy draft has unexpected transport marker")
        if old.subject != row.get("subject", "").strip():
            raise RuntimeError("existing legacy draft subject does not match OutreachQueue")

        if not apply:
            return {
                "status": "preflight_green",
                "lead_id": lead_id,
                "recipient": recipient,
                "folder": folder,
                "legacy_uid": old.uid,
                "smtp_send": "not_invoked",
            }

        new_uid = sync._append(imap, folder, mailbox, row, desired_body, test_id)
        if not sync._message_matches_queue(imap, new_uid, row, desired_body):
            raise RuntimeError("new migrated draft content readback mismatch")

        sync._delete_uid(imap, old.uid)
        status, _ = imap.select(folder, readonly=False)
        if status != "OK":
            raise RuntimeError("failed to reselect Drafts folder after legacy delete")

        final = sync._scan_sender_drafts(imap, mailbox.sender_email, {recipient}).get(recipient, [])
        if len(final) != 1:
            raise RuntimeError(f"final sender-draft count is {len(final)}")
        if not final[0].test_id or not SAFE_TEST_ID.fullmatch(final[0].test_id):
            raise RuntimeError("final draft is missing a safe Webactueel draft test id")
        if not sync._message_matches_queue(imap, final[0].uid, row, desired_body):
            raise RuntimeError("final migrated draft content does not match OutreachQueue")

        return {
            "status": "green",
            "lead_id": lead_id,
            "recipient": recipient,
            "folder": folder,
            "final_readback": 1,
            "smtp_send": "not_invoked",
        }
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely migrate one legacy mijn.host draft to a verified Webactueel draft")
    parser.add_argument("--lead-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = migrate(
            lead_id=args.lead_id.strip(),
            spreadsheet_id=os.getenv("OUTREACH_SPREADSHEET_ID", ""),
            test_id=os.getenv("OUTREACH_DRAFT_TEST_ID", "").strip(),
            apply=args.apply,
        )
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"MYHOST_LEGACY_DRAFT_MIGRATION=blocked detail={exc} smtp_send=not_invoked")
        return 2

    marker = "green" if result["status"] == "green" else "preflight_green"
    suffix = f" final_readback={result.get('final_readback', 0)}" if marker == "green" else ""
    print(
        f"MYHOST_LEGACY_DRAFT_MIGRATION={marker} lead_id={result['lead_id']} "
        f"recipient={result['recipient']}{suffix} smtp_send=not_invoked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
