from __future__ import annotations

import argparse
import json
import os
import re
from typing import Iterable

from outreach_imap_draft import append_verified_draft, choose_mailbox
from outreach_mailboxes import enabled_mailboxes, load_mailboxes_from_env

QUEUE_SHEET = "OutreachQueue"
SUPPRESSION_SHEET = "Suppression"
SAFE_LEAD_ID = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
ALLOWED_DRAFT_STATUSES = {"prepared", "manual_review", "approved"}
TERMINAL_FIELDS = (
    "sent_at",
    "followup_sent_at",
    "message_id",
    "followup_message_id",
    "reply_at",
    "bounce_at",
)


def _normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def _domain_of(value: str) -> str:
    address = _normalize_email(value)
    return address.rsplit("@", 1)[1] if "@" in address else ""


def rows_from_values(values: list[list[str]]) -> list[dict[str, str]]:
    if not values:
        return []
    headers = [str(value).strip() for value in values[0]]
    rows: list[dict[str, str]] = []
    for raw in values[1:]:
        padded = list(raw) + [""] * max(0, len(headers) - len(raw))
        rows.append({headers[index]: str(padded[index]) for index in range(len(headers))})
    return rows


def resolve_queue_row(values: list[list[str]], lead_id: str) -> dict[str, str]:
    if not SAFE_LEAD_ID.fullmatch(lead_id or ""):
        raise ValueError("lead_id contains unsupported characters")
    matches = [row for row in rows_from_values(values) if row.get("lead_id", "").strip() == lead_id]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one OutreachQueue row for lead_id; found {len(matches)}")
    return matches[0]


def suppression_sets(values: list[list[str]]) -> tuple[set[str], set[str]]:
    emails: set[str] = set()
    domains: set[str] = set()
    for row in rows_from_values(values):
        email = _normalize_email(row.get("email", ""))
        domain = (row.get("domain", "") or "").strip().lower()
        if email:
            emails.add(email)
        if domain:
            domains.add(domain)
    return emails, domains


def validate_queue_row(
    row: dict[str, str],
    *,
    sender_email: str,
    suppressed_emails: Iterable[str] = (),
    suppressed_domains: Iterable[str] = (),
) -> list[str]:
    errors: list[str] = []
    recipient = _normalize_email(row.get("email", ""))
    sender = _normalize_email(sender_email)
    status = row.get("status", "").strip().lower()
    compliance = row.get("compliance_status", "").strip().lower()
    stage = row.get("stage", "").strip()

    if status not in ALLOWED_DRAFT_STATUSES:
        errors.append("queue status is not draft-eligible")
    if compliance != "approved":
        errors.append("compliance_status is not approved")
    if stage not in {"", "1"}:
        errors.append("only the initial stage can be drafted")
    if "@" not in recipient:
        errors.append("recipient email is invalid")
    if not row.get("subject", "").strip():
        errors.append("subject is missing")
    if not row.get("body", "").strip():
        errors.append("body is missing")
    if any(row.get(field, "").strip() for field in TERMINAL_FIELDS):
        errors.append("queue row already has send/reply/bounce evidence")
    configured_sender = _normalize_email(row.get("sender_email", ""))
    if configured_sender and sender and configured_sender != sender:
        errors.append("queue sender does not match configured mailbox sender")

    suppressed_email_set = {_normalize_email(value) for value in suppressed_emails if value}
    suppressed_domain_set = {(value or "").strip().lower() for value in suppressed_domains if value}
    if recipient in suppressed_email_set or _domain_of(recipient) in suppressed_domain_set:
        errors.append("recipient is suppressed")
    return errors


def build_sheets_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def get_values(service, spreadsheet_id: str, sheet_name: str) -> list[list[str]]:
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'!A:AZ",
    ).execute()
    return result.get("values", [])


def create_queue_draft(*, lead_id: str, spreadsheet_id: str, test_id: str):
    if not spreadsheet_id.strip():
        raise RuntimeError("OUTREACH_SPREADSHEET_ID is required")
    if not test_id.strip():
        raise RuntimeError("OUTREACH_DRAFT_TEST_ID is required")

    service = build_sheets_service()
    row = resolve_queue_row(get_values(service, spreadsheet_id, QUEUE_SHEET), lead_id)
    suppressed_emails, suppressed_domains = suppression_sets(
        get_values(service, spreadsheet_id, SUPPRESSION_SHEET)
    )

    daily_limit = int(os.getenv("OUTREACH_DAILY_LIMIT", "20") or "20")
    mailboxes = enabled_mailboxes(load_mailboxes_from_env(mode="validate", default_daily_limit=daily_limit))
    mailbox = choose_mailbox(mailboxes, os.getenv("OUTREACH_DRAFT_MAILBOX_ID", ""))
    errors = validate_queue_row(
        row,
        sender_email=mailbox.sender_email,
        suppressed_emails=suppressed_emails,
        suppressed_domains=suppressed_domains,
    )
    if errors:
        raise RuntimeError("; ".join(errors))

    return append_verified_draft(
        mailbox,
        recipient=row["email"],
        subject=row["subject"],
        body=row["body"],
        test_id=test_id,
        explicit_folder=os.getenv("OUTREACH_DRAFT_FOLDER", ""),
        self_only=False,
        retries=int(os.getenv("OUTREACH_DRAFT_VERIFY_RETRIES", "3") or "3"),
        delay_seconds=float(os.getenv("OUTREACH_DRAFT_VERIFY_DELAY_SECONDS", "1") or "1"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Create one verified mijn.host IMAP draft from OutreachQueue")
    parser.add_argument("--lead-id", required=True)
    args = parser.parse_args()
    try:
        receipt = create_queue_draft(
            lead_id=args.lead_id.strip(),
            spreadsheet_id=os.getenv("OUTREACH_SPREADSHEET_ID", ""),
            test_id=os.getenv("OUTREACH_DRAFT_TEST_ID", "").strip(),
        )
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"MYHOST_QUEUE_DRAFT=blocked detail={exc}")
        return 2
    print(
        "MYHOST_QUEUE_DRAFT=green "
        f"lead_id={args.lead_id.strip()} mailbox={receipt.mailbox_id} "
        f"folder={receipt.folder} readback_count={len(receipt.message_ids)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
