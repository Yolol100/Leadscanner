from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from outreach_idempotent_imap_draft import ensure_verified_draft
from outreach_mailboxes import enabled_mailboxes, load_mailboxes_from_env
from outreach_replyhub import REPLY_HEADERS, REPLY_SHEET, sync_replyhub
from outreach_sender import (
    QUEUE_HEADERS,
    QUEUE_SHEET,
    Settings,
    build_sheets_service,
    ensure_expected_headers,
    get_values,
    normalize_address,
    rows_from_values,
    update_row,
)

PENDING = "drafted_pending_notify"
DONE = "handled_notified"
POSITIVE = "positive_interest"
SAFE_REPLY_ID = re.compile(r"^[0-9a-f]{32}$")


def draft_test_id(reply_id: str) -> str:
    value = (reply_id or "").strip().lower()
    if not SAFE_REPLY_ID.fullmatch(value):
        raise ValueError("reply_id is not a canonical 32-character hex id")
    return f"positive-reply-{value}"


def reply_subject(incoming_subject: str) -> str:
    subject = re.sub(r"[\r\n]+", " ", incoming_subject or "").strip()
    subject = re.sub(r"\s+", " ", subject)[:180]
    if not subject:
        return "Re: your reply"
    if subject.casefold().startswith("re:"):
        return subject
    return f"Re: {subject}"


def _original_language(original_body: str) -> str:
    text = str(original_body or "")
    if "Geen interesse?" in text or "Dit is een commercieel bericht." in text or "Met vriendelijke groet" in text:
        return "nl"
    return "en"


def followup_body(original_body: str = "") -> str:
    """Create one truthful, focused post-reply draft without claiming an artifact exists."""
    if _original_language(original_body) == "nl":
        return (
            "Bedankt voor je reactie.\n\n"
            "Welk onderdeel van het idee uit mijn eerste bericht zal ik als eerste concreet maken?\n\n"
            "Met vriendelijke groet,\nAndrew Baeten"
        )
    return (
        "Thanks for your reply.\n\n"
        "Which part of the idea from my first message would be most useful for me to make concrete first?\n\n"
        "Best regards,\nAndrew Baeten"
    )


def eligible_reply(row: dict[str, str]) -> bool:
    return (
        str(row.get("classification", "")).strip().lower() == "reply"
        and str(row.get("owner_label", "")).strip().lower() == POSITIVE
        and str(row.get("triage_status", "")).strip().lower() in {"new", PENDING}
    )


def _single_lead(queue_rows: list[dict[str, str]], reply: dict[str, str]) -> tuple[int, dict[str, str]]:
    lead_id = str(reply.get("lead_id", "")).strip()
    recipient = normalize_address(reply.get("email", ""))
    matches = [
        (idx, row)
        for idx, row in enumerate(queue_rows)
        if str(row.get("lead_id", "")).strip() == lead_id
        and normalize_address(row.get("email", "")) == recipient
    ]
    if len(matches) != 1:
        raise RuntimeError(f"positive reply must map to exactly one lead; found {len(matches)}")
    return matches[0]


def _mailbox_by_id(mailboxes, mailbox_id: str):
    matches = [m for m in mailboxes if m.mailbox_id == (mailbox_id or "").strip().lower()]
    if len(matches) != 1:
        raise RuntimeError("reply mailbox does not map to exactly one enabled mailbox")
    return matches[0]


def _append_note(existing: str, addition: str) -> str:
    existing = (existing or "").strip()
    if addition in existing:
        return existing
    return f"{existing}; {addition}".strip("; ")


def process_positive_replies(*, report_path: str = "") -> dict:
    settings = Settings.from_env()
    if settings.mode != "live":
        raise RuntimeError("positive reply handoff requires OUTREACH_MODE=live")
    service = build_sheets_service()
    queue_headers, queue_rows = rows_from_values(get_values(service, settings.spreadsheet_id, QUEUE_SHEET))
    reply_headers, reply_rows = rows_from_values(get_values(service, settings.spreadsheet_id, REPLY_SHEET))
    ensure_expected_headers(queue_headers, QUEUE_HEADERS, QUEUE_SHEET)
    ensure_expected_headers(reply_headers, REPLY_HEADERS, REPLY_SHEET)

    daily_limit = int(os.getenv("OUTREACH_DAILY_LIMIT", "100") or "100")
    mailboxes = enabled_mailboxes(load_mailboxes_from_env(mode="validate", default_daily_limit=daily_limit))
    sync_replyhub(service, settings, queue_headers, queue_rows, reply_rows, mailboxes)

    queue_headers, queue_rows = rows_from_values(get_values(service, settings.spreadsheet_id, QUEUE_SHEET))
    reply_headers, reply_rows = rows_from_values(get_values(service, settings.spreadsheet_id, REPLY_SHEET))
    ensure_expected_headers(queue_headers, QUEUE_HEADERS, QUEUE_SHEET)
    ensure_expected_headers(reply_headers, REPLY_HEADERS, REPLY_SHEET)

    entries: list[dict[str, str]] = []
    for reply_idx, reply in enumerate(reply_rows):
        if not eligible_reply(reply):
            continue
        _queue_idx, lead = _single_lead(queue_rows, reply)
        mailbox = _mailbox_by_id(mailboxes, reply.get("mailbox_id", ""))
        reply_id = str(reply.get("reply_id", "")).strip().lower()
        test_id = draft_test_id(reply_id)
        receipt = ensure_verified_draft(
            mailbox,
            recipient=reply["email"],
            subject=reply_subject(reply.get("subject", "")),
            body=followup_body(lead.get("body", "")),
            test_id=test_id,
            explicit_folder=os.getenv("OUTREACH_DRAFT_FOLDER", ""),
            retries=int(os.getenv("OUTREACH_DRAFT_VERIFY_RETRIES", "3") or "3"),
            delay_seconds=float(os.getenv("OUTREACH_DRAFT_VERIFY_DELAY_SECONDS", "1") or "1"),
        )
        if len(receipt.message_ids) != 1:
            raise RuntimeError("positive reply follow-up did not converge to exactly one draft")
        reply["triage_status"] = PENDING
        reply["notes"] = _append_note(reply.get("notes", ""), f"followup_draft_test_id={test_id}")
        update_row(
            service,
            settings.spreadsheet_id,
            REPLY_SHEET,
            reply_idx + 2,
            reply_headers,
            reply,
        )
        entries.append(
            {
                "reply_id": reply_id,
                "lead_id": str(lead.get("lead_id", "")),
                "company": str(lead.get("company", "")),
                "email": normalize_address(reply.get("email", "")),
                "mailbox_id": mailbox.mailbox_id,
                "draft_test_id": test_id,
                "draft_folder": receipt.folder,
                "draft_readback_count": str(len(receipt.message_ids)),
            }
        )

    result = {
        "status": "green",
        "positive_pending_notification": len(entries),
        "smtp_send": "not_invoked",
        "entries": entries,
    }
    if report_path:
        Path(report_path).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def acknowledge_notifications(path: str) -> dict:
    ids = {
        line.strip().lower()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    if any(not SAFE_REPLY_ID.fullmatch(value) for value in ids):
        raise ValueError("ack file contains invalid reply_id")
    if not ids:
        return {"status": "green", "acknowledged": 0, "smtp_send": "not_invoked"}

    settings = Settings.from_env()
    service = build_sheets_service()
    reply_headers, reply_rows = rows_from_values(get_values(service, settings.spreadsheet_id, REPLY_SHEET))
    ensure_expected_headers(reply_headers, REPLY_HEADERS, REPLY_SHEET)
    found: set[str] = set()
    for idx, row in enumerate(reply_rows):
        reply_id = str(row.get("reply_id", "")).strip().lower()
        if reply_id not in ids:
            continue
        if str(row.get("triage_status", "")).strip().lower() not in {PENDING, DONE}:
            raise RuntimeError(f"cannot acknowledge reply {reply_id} before a verified follow-up draft")
        row["triage_status"] = DONE
        row["notes"] = _append_note(row.get("notes", ""), "andrew_notified=github_issue")
        update_row(service, settings.spreadsheet_id, REPLY_SHEET, idx + 2, reply_headers, row)
        found.add(reply_id)
    missing = sorted(ids - found)
    if missing:
        raise RuntimeError("ack reply IDs missing from ReplyInbox: " + ", ".join(missing))
    return {"status": "green", "acknowledged": len(found), "smtp_send": "not_invoked"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Draft-only handoff for verified positive replies")
    parser.add_argument("--report", default="")
    parser.add_argument("--ack-file", default="")
    args = parser.parse_args()
    try:
        result = acknowledge_notifications(args.ack_file) if args.ack_file else process_positive_replies(report_path=args.report)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"POSITIVE_REPLY_HANDOFF=blocked detail={exc} smtp_send=not_invoked")
        return 2
    print(
        "POSITIVE_REPLY_HANDOFF=green "
        f"count={result.get('positive_pending_notification', result.get('acknowledged', 0))} "
        "smtp_send=not_invoked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
