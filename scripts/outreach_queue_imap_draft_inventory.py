from __future__ import annotations

import argparse
import imaplib
import json
import os
import ssl
from collections import Counter

from outreach_imap_draft import choose_mailbox, detect_drafts_folder
from outreach_mailboxes import enabled_mailboxes, load_mailboxes_from_env
from outreach_queue_imap_draft import QUEUE_SHEET, build_sheets_service, get_values, rows_from_values
from outreach_queue_imap_draft_sync import (
    _fetch_payload,
    _normalize_email,
    _snapshot_from_header,
    _uid_search,
)


def _queue_index(rows: list[dict[str, str]]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for row in rows:
        lead_id = (row.get("lead_id") or "").strip()
        recipient = _normalize_email(row.get("email", ""))
        if not lead_id or not recipient:
            continue
        index.setdefault(recipient, []).append(lead_id)
    for recipient in index:
        index[recipient] = sorted(set(index[recipient]))
    return index


def inventory_queue_drafts(*, spreadsheet_id: str, expected_count: int | None = None, report_path: str = "") -> dict:
    if not spreadsheet_id.strip():
        raise RuntimeError("OUTREACH_SPREADSHEET_ID is required")
    if expected_count is not None and (expected_count < 1 or expected_count > 500):
        raise RuntimeError("expected count must be between 1 and 500")

    service = build_sheets_service()
    queue_rows = rows_from_values(get_values(service, spreadsheet_id, QUEUE_SHEET))
    queue_index = _queue_index(queue_rows)

    daily_limit = int(os.getenv("OUTREACH_DAILY_LIMIT", "20") or "20")
    mailboxes = enabled_mailboxes(load_mailboxes_from_env(mode="validate", default_daily_limit=daily_limit))
    mailbox = choose_mailbox(mailboxes, os.getenv("OUTREACH_DRAFT_MAILBOX_ID", ""))
    if not getattr(mailbox, "mail_password", ""):
        raise RuntimeError("OUTREACH_MAIL_PASSWORD is required for IMAP draft inventory")

    context = ssl.create_default_context()
    imap = imaplib.IMAP4_SSL(mailbox.imap_host, mailbox.imap_port, ssl_context=context)
    report: dict = {
        "status": "blocked",
        "mode": "read_only_inventory",
        "expected_count": expected_count,
        "mailbox_id": mailbox.mailbox_id,
        "sender_email": mailbox.sender_email,
        "smtp_send": "not_invoked",
        "drafts": [],
    }
    try:
        status, _ = imap.login(mailbox.mail_user, mailbox.mail_password)
        if status != "OK":
            raise RuntimeError("IMAP authentication failed")
        status, folders = imap.list()
        if status != "OK":
            raise RuntimeError("IMAP LIST failed")
        folder = detect_drafts_folder(folders or (), explicit_folder=os.getenv("OUTREACH_DRAFT_FOLDER", ""))
        report["folder"] = folder
        status, _ = imap.select(folder, readonly=True)
        if status != "OK":
            raise RuntimeError(f"failed to select Drafts folder read-only: {folder}")

        header_query = "(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT X-Webactueel-Draft-Test-ID X-Webactueel-Transport)])"
        entries: list[dict] = []
        recipient_counter: Counter[str] = Counter()
        sender_email = _normalize_email(mailbox.sender_email)
        for uid in _uid_search(imap, "ALL"):
            snapshot = _snapshot_from_header(uid, _fetch_payload(imap, uid, header_query))
            if snapshot.sender != sender_email:
                continue
            candidate_ids: set[str] = set()
            for recipient in snapshot.recipients:
                recipient_counter[recipient] += 1
                candidate_ids.update(queue_index.get(recipient, []))
            entries.append(
                {
                    "uid": snapshot.uid,
                    "recipients": list(snapshot.recipients),
                    "subject": snapshot.subject,
                    "test_id": snapshot.test_id,
                    "transport": snapshot.transport,
                    "candidate_lead_ids": sorted(candidate_ids),
                    "candidate_count": len(candidate_ids),
                }
            )

        entries.sort(key=lambda item: ((item.get("recipients") or [""])[0], item.get("subject", ""), item.get("uid", "")))
        sender_count = len(entries)
        mapped_one = sum(item["candidate_count"] == 1 for item in entries)
        ambiguous = sum(item["candidate_count"] > 1 for item in entries)
        unmapped = sum(item["candidate_count"] == 0 for item in entries)
        duplicate_recipients = {recipient: count for recipient, count in sorted(recipient_counter.items()) if count > 1}

        report["drafts"] = entries
        report["duplicate_recipients"] = duplicate_recipients
        report["counts"] = {
            "sender_drafts": sender_count,
            "mapped_one": mapped_one,
            "ambiguous": ambiguous,
            "unmapped": unmapped,
            "duplicate_recipients": len(duplicate_recipients),
        }
        if expected_count is not None and sender_count != expected_count:
            report["status"] = "blocked"
            report["blockers"] = [f"expected {expected_count} sender drafts; found {sender_count}"]
        else:
            report["status"] = "green"
        return report
    finally:
        try:
            imap.logout()
        except Exception:
            pass
        if report_path:
            with open(report_path, "w", encoding="utf-8") as handle:
                json.dump(report, handle, ensure_ascii=False, indent=2)
                handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only inventory of mijn.host IMAP drafts and OutreachQueue mappings")
    parser.add_argument("--expected-count", type=int, default=None)
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    try:
        result = inventory_queue_drafts(
            spreadsheet_id=os.getenv("OUTREACH_SPREADSHEET_ID", ""),
            expected_count=args.expected_count,
            report_path=args.report,
        )
    except (RuntimeError, ValueError, OSError, imaplib.IMAP4.error) as exc:
        print(f"MYHOST_DRAFT_INVENTORY=blocked detail={exc} smtp_send=not_invoked")
        return 2

    counts = result.get("counts", {})
    marker = result.get("status", "blocked")
    print(
        f"MYHOST_DRAFT_INVENTORY={marker} "
        f"sender_drafts={counts.get('sender_drafts', 0)} mapped_one={counts.get('mapped_one', 0)} "
        f"ambiguous={counts.get('ambiguous', 0)} unmapped={counts.get('unmapped', 0)} "
        f"duplicate_recipients={counts.get('duplicate_recipients', 0)} smtp_send=not_invoked"
    )
    return 0 if marker == "green" else 2


if __name__ == "__main__":
    raise SystemExit(main())
