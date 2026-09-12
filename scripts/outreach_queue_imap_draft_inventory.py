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

ALLOWED_DRAFT_COMPLIANCE = {"manual_review", "approved"}


def _queue_index(rows: list[dict[str, str]], sender_email: str) -> dict[str, list[dict[str, str]]]:
    sender = _normalize_email(sender_email)
    index: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        lead_id = (row.get("lead_id") or "").strip()
        recipient = _normalize_email(row.get("email", ""))
        row_sender = _normalize_email(row.get("sender_email", ""))
        compliance = (row.get("compliance_status") or "").strip().lower()
        status = (row.get("status") or "").strip().lower()
        if not lead_id or not recipient:
            continue
        if row_sender and row_sender != sender:
            continue
        if compliance not in ALLOWED_DRAFT_COMPLIANCE:
            continue
        if status not in ALLOWED_DRAFT_COMPLIANCE:
            continue
        index.setdefault(recipient, []).append(
            {
                "lead_id": lead_id,
                "subject": (row.get("subject") or "").strip(),
            }
        )
    for recipient in index:
        unique = {(item["lead_id"], item["subject"]): item for item in index[recipient]}
        index[recipient] = sorted(unique.values(), key=lambda item: (item["subject"], item["lead_id"]))
    return index


def inventory_queue_drafts(*, spreadsheet_id: str, expected_count: int | None = None, report_path: str = "") -> dict:
    if not spreadsheet_id.strip():
        raise RuntimeError("OUTREACH_SPREADSHEET_ID is required")
    if expected_count is not None and (expected_count < 1 or expected_count > 500):
        raise RuntimeError("expected count must be between 1 and 500")

    service = build_sheets_service()
    queue_rows = rows_from_values(get_values(service, spreadsheet_id, QUEUE_SHEET))

    daily_limit = int(os.getenv("OUTREACH_DAILY_LIMIT", "20") or "20")
    mailboxes = enabled_mailboxes(load_mailboxes_from_env(mode="validate", default_daily_limit=daily_limit))
    mailbox = choose_mailbox(mailboxes, os.getenv("OUTREACH_DRAFT_MAILBOX_ID", ""))
    if not getattr(mailbox, "mail_password", ""):
        raise RuntimeError("OUTREACH_MAIL_PASSWORD is required for IMAP draft inventory")
    queue_index = _queue_index(queue_rows, mailbox.sender_email)

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

            recipient_candidates: dict[str, dict[str, str]] = {}
            subject_candidates: dict[str, dict[str, str]] = {}
            for recipient in snapshot.recipients:
                recipient_counter[recipient] += 1
                for item in queue_index.get(recipient, []):
                    recipient_candidates[item["lead_id"]] = item
                    if item["subject"] == snapshot.subject:
                        subject_candidates[item["lead_id"]] = item

            chosen = subject_candidates if subject_candidates else recipient_candidates
            match_basis = "recipient_subject" if subject_candidates else ("recipient" if recipient_candidates else "none")
            candidate_ids = sorted(chosen)
            entries.append(
                {
                    "uid": snapshot.uid,
                    "recipients": list(snapshot.recipients),
                    "subject": snapshot.subject,
                    "test_id": snapshot.test_id,
                    "transport": snapshot.transport,
                    "match_basis": match_basis,
                    "candidate_lead_ids": candidate_ids,
                    "candidate_count": len(candidate_ids),
                    "recipient_candidate_count": len(recipient_candidates),
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
        blockers: list[str] = []
        if expected_count is not None and sender_count != expected_count:
            blockers.append(f"expected {expected_count} sender drafts; found {sender_count}")
        if blockers:
            report["status"] = "blocked"
            report["blockers"] = blockers
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
