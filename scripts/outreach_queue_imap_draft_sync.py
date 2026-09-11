from __future__ import annotations

import argparse
import hashlib
import imaplib
import json
import os
import ssl
import time
from dataclasses import asdict, dataclass
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from typing import Iterable

from outreach_imap_draft import SAFE_TEST_ID, build_draft_message, choose_mailbox, detect_drafts_folder
from outreach_mailboxes import enabled_mailboxes, load_mailboxes_from_env
from outreach_queue_imap_draft import (
    QUEUE_SHEET,
    SUPPRESSION_SHEET,
    build_sheets_service,
    get_values,
    inject_private_postal_for_draft,
    rows_from_values,
    suppression_sets,
    validate_queue_row,
)

ALLOWED_DRAFT_COMPLIANCE = {"manual_review", "approved"}


@dataclass(frozen=True)
class DraftSnapshot:
    uid: str
    sender: str
    recipients: tuple[str, ...]
    subject: str
    test_id: str
    transport: str


@dataclass(frozen=True)
class PlannedAction:
    lead_id: str
    recipient: str
    action: str
    old_uid: str
    new_test_id: str


def _normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def _normalize_text(value: str) -> str:
    return (value or "").replace("\r\n", "\n").replace("\r", "\n").rstrip()


def _first_address(values: Iterable[str]) -> str:
    addresses = [_normalize_email(address) for _name, address in getaddresses(list(values)) if address]
    return addresses[0] if addresses else ""


def _all_addresses(values: Iterable[str]) -> tuple[str, ...]:
    addresses = {_normalize_email(address) for _name, address in getaddresses(list(values)) if address}
    return tuple(sorted(addresses))


def _uid_list(data) -> tuple[str, ...]:
    if not data or not data[0]:
        return ()
    return tuple(part.decode("ascii", errors="replace") if isinstance(part, bytes) else str(part) for part in data[0].split())


def _uid_search(imap, *criteria: str) -> tuple[str, ...]:
    status, data = imap.uid("search", None, *criteria)
    if status != "OK":
        raise RuntimeError("IMAP UID SEARCH failed")
    return _uid_list(data)


def _fetch_payload(imap, uid: str, query: str) -> bytes:
    status, data = imap.uid("fetch", uid, query)
    if status != "OK":
        raise RuntimeError(f"IMAP UID FETCH failed for uid={uid}")
    for item in data or ():
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            return bytes(item[1])
    raise RuntimeError(f"IMAP UID FETCH returned no payload for uid={uid}")


def _snapshot_from_header(uid: str, raw: bytes) -> DraftSnapshot:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    return DraftSnapshot(
        uid=uid,
        sender=_first_address(msg.get_all("From", [])),
        recipients=_all_addresses(msg.get_all("To", [])),
        subject=str(msg.get("Subject", "")).strip(),
        test_id=str(msg.get("X-Webactueel-Draft-Test-ID", "")).strip(),
        transport=str(msg.get("X-Webactueel-Transport", "")).strip().lower(),
    )


def _plain_body(raw: bytes) -> tuple[str, str]:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    subject = str(msg.get("Subject", "")).strip()
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and part.get_content_disposition() != "attachment":
                content = part.get_content()
                return subject, str(content)
        return subject, ""
    content = msg.get_content()
    return subject, str(content)


def _target_rows(values: list[list[str]], prefix: str, expected_count: int) -> list[dict[str, str]]:
    rows = [row for row in rows_from_values(values) if row.get("lead_id", "").strip().startswith(prefix)]
    rows.sort(key=lambda row: row.get("lead_id", ""))
    if len(rows) != expected_count:
        raise RuntimeError(f"expected {expected_count} queue rows for prefix; found {len(rows)}")
    lead_ids = [row.get("lead_id", "").strip() for row in rows]
    if len(set(lead_ids)) != len(lead_ids):
        raise RuntimeError("selected queue rows contain duplicate lead_id values")
    recipients = [_normalize_email(row.get("email", "")) for row in rows]
    if len(set(recipients)) != len(recipients):
        raise RuntimeError("selected queue rows contain duplicate recipient emails")
    return rows


def _sync_test_id(row: dict[str, str], body: str) -> str:
    material = "|".join(
        [
            row.get("lead_id", "").strip(),
            _normalize_email(row.get("email", "")),
            row.get("subject", "").strip(),
            _normalize_text(body),
        ]
    )
    return "sync-lead-draft-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _validate_rows(rows: list[dict[str, str]], mailbox, suppressed_emails: set[str], suppressed_domains: set[str]) -> None:
    failures: list[str] = []
    for row in rows:
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
            failures.append(f"{row.get('lead_id', '').strip()}: {'; '.join(sorted(set(errors)))}")
    if failures:
        raise RuntimeError("queue validation failed: " + " | ".join(failures))


def _scan_sender_drafts(imap, sender_email: str, target_recipients: set[str]) -> dict[str, list[DraftSnapshot]]:
    header_query = "(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT X-Webactueel-Draft-Test-ID X-Webactueel-Transport)])"
    matches = {recipient: [] for recipient in target_recipients}
    for uid in _uid_search(imap, "ALL"):
        snapshot = _snapshot_from_header(uid, _fetch_payload(imap, uid, header_query))
        if snapshot.sender != _normalize_email(sender_email):
            continue
        for recipient in snapshot.recipients:
            if recipient in matches:
                matches[recipient].append(snapshot)
    return matches


def _message_matches_queue(imap, uid: str, row: dict[str, str], desired_body: str) -> bool:
    subject, body = _plain_body(_fetch_payload(imap, uid, "(BODY.PEEK[])") )
    return subject == row.get("subject", "").strip() and _normalize_text(body) == _normalize_text(desired_body)


def _append(imap, folder: str, mailbox, row: dict[str, str], body: str, test_id: str) -> str:
    if not SAFE_TEST_ID.fullmatch(test_id):
        raise RuntimeError("generated sync test id is invalid")
    if _uid_search(imap, "HEADER", "X-Webactueel-Draft-Test-ID", f'"{test_id}"'):
        raise RuntimeError(f"sync test id already exists before append: {test_id}")
    msg = build_draft_message(
        sender_name=mailbox.sender_name,
        sender_email=mailbox.sender_email,
        recipient=row["email"],
        subject=row["subject"],
        body=body,
        test_id=test_id,
    )
    status, _ = imap.append(folder, r"(\Draft)", imaplib.Time2Internaldate(time.time()), msg.as_bytes(policy=policy.SMTP))
    if status != "OK":
        raise RuntimeError(f"IMAP APPEND failed for {row.get('lead_id', '')}")
    status, _ = imap.select(folder, readonly=False)
    if status != "OK":
        raise RuntimeError("failed to reselect Drafts folder after append")
    ids = _uid_search(imap, "HEADER", "X-Webactueel-Draft-Test-ID", f'"{test_id}"')
    if len(ids) != 1:
        raise RuntimeError(f"append readback expected one draft for {test_id}; found {len(ids)}")
    return ids[0]


def _delete_uid(imap, uid: str) -> None:
    status, _ = imap.uid("store", uid, "+FLAGS", r"(\Deleted)")
    if status != "OK":
        raise RuntimeError(f"failed to mark old draft deleted for uid={uid}")
    status, _ = imap.expunge()
    if status != "OK":
        raise RuntimeError(f"failed to expunge old draft uid={uid}")


def sync_queue_drafts(*, lead_prefix: str, expected_count: int, spreadsheet_id: str, apply: bool, report_path: str = "") -> dict:
    if not lead_prefix or len(lead_prefix) > 160:
        raise RuntimeError("lead prefix is required and must be <=160 characters")
    if expected_count < 1 or expected_count > 100:
        raise RuntimeError("expected count must be between 1 and 100")
    if not spreadsheet_id.strip():
        raise RuntimeError("OUTREACH_SPREADSHEET_ID is required")

    service = build_sheets_service()
    rows = _target_rows(get_values(service, spreadsheet_id, QUEUE_SHEET), lead_prefix, expected_count)
    suppressed_emails, suppressed_domains = suppression_sets(get_values(service, spreadsheet_id, SUPPRESSION_SHEET))

    daily_limit = int(os.getenv("OUTREACH_DAILY_LIMIT", "20") or "20")
    mailboxes = enabled_mailboxes(load_mailboxes_from_env(mode="validate", default_daily_limit=daily_limit))
    mailbox = choose_mailbox(mailboxes, os.getenv("OUTREACH_DRAFT_MAILBOX_ID", ""))
    _validate_rows(rows, mailbox, suppressed_emails, suppressed_domains)

    if not getattr(mailbox, "mail_password", ""):
        raise RuntimeError("OUTREACH_MAIL_PASSWORD is required for IMAP draft synchronization")

    desired_bodies = {
        row["lead_id"].strip(): inject_private_postal_for_draft(row, row["body"])
        for row in rows
    }
    targets = {_normalize_email(row["email"]) for row in rows}
    context = ssl.create_default_context()
    imap = imaplib.IMAP4_SSL(mailbox.imap_host, mailbox.imap_port, ssl_context=context)
    report: dict = {
        "mode": "apply" if apply else "dry_run",
        "lead_prefix": lead_prefix,
        "expected_count": expected_count,
        "mailbox_id": mailbox.mailbox_id,
        "sender_email": mailbox.sender_email,
        "smtp_send": "not_invoked",
        "actions": [],
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
        status, _ = imap.select(folder, readonly=False)
        if status != "OK":
            raise RuntimeError(f"failed to select Drafts folder: {folder}")

        existing = _scan_sender_drafts(imap, mailbox.sender_email, targets)
        plan: list[PlannedAction] = []
        blockers: list[str] = []
        for row in rows:
            lead_id = row["lead_id"].strip()
            recipient = _normalize_email(row["email"])
            snapshots = existing.get(recipient, [])
            test_id = _sync_test_id(row, desired_bodies[lead_id])
            if len(snapshots) > 1:
                blockers.append(f"{lead_id}: multiple sender drafts for recipient ({len(snapshots)})")
                continue
            if len(snapshots) == 0:
                plan.append(PlannedAction(lead_id, recipient, "create", "", test_id))
                continue
            snapshot = snapshots[0]
            if not snapshot.test_id or not SAFE_TEST_ID.fullmatch(snapshot.test_id):
                blockers.append(f"{lead_id}: existing sender draft lacks a safe Webactueel draft test id")
                continue
            if snapshot.transport not in {"", "imap-draft-only"}:
                blockers.append(f"{lead_id}: existing sender draft has unexpected transport marker")
                continue
            if _message_matches_queue(imap, snapshot.uid, row, desired_bodies[lead_id]):
                plan.append(PlannedAction(lead_id, recipient, "unchanged", snapshot.uid, snapshot.test_id))
            else:
                plan.append(PlannedAction(lead_id, recipient, "replace", snapshot.uid, test_id))

        if blockers:
            report["status"] = "blocked"
            report["blockers"] = blockers
            raise RuntimeError("preflight blocked: " + " | ".join(blockers))

        report["actions"] = [asdict(item) for item in plan]
        if not apply:
            report["status"] = "preflight_green"
            report["counts"] = {
                "target": len(plan),
                "create": sum(item.action == "create" for item in plan),
                "replace": sum(item.action == "replace" for item in plan),
                "unchanged": sum(item.action == "unchanged" for item in plan),
            }
            return report

        rows_by_id = {row["lead_id"].strip(): row for row in rows}
        for item in plan:
            if item.action == "unchanged":
                continue
            row = rows_by_id[item.lead_id]
            body = desired_bodies[item.lead_id]
            new_uid = _append(imap, folder, mailbox, row, body, item.new_test_id)
            if item.action == "replace":
                _delete_uid(imap, item.old_uid)
                status, _ = imap.select(folder, readonly=False)
                if status != "OK":
                    raise RuntimeError("failed to reselect Drafts folder after delete")
            if not _message_matches_queue(imap, new_uid, row, body):
                raise RuntimeError(f"new draft content readback mismatch for {item.lead_id}")

        final = _scan_sender_drafts(imap, mailbox.sender_email, targets)
        final_errors: list[str] = []
        for row in rows:
            lead_id = row["lead_id"].strip()
            recipient = _normalize_email(row["email"])
            snapshots = final.get(recipient, [])
            if len(snapshots) != 1:
                final_errors.append(f"{lead_id}: final sender-draft count is {len(snapshots)}")
                continue
            if not _message_matches_queue(imap, snapshots[0].uid, row, desired_bodies[lead_id]):
                final_errors.append(f"{lead_id}: final content does not match OutreachQueue")
        if final_errors:
            raise RuntimeError("final readback failed: " + " | ".join(final_errors))

        report["status"] = "green"
        report["counts"] = {
            "target": len(plan),
            "create": sum(item.action == "create" for item in plan),
            "replace": sum(item.action == "replace" for item in plan),
            "unchanged": sum(item.action == "unchanged" for item in plan),
            "final_readback": expected_count,
        }
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
    parser = argparse.ArgumentParser(description="Safely synchronize OutreachQueue rows to existing mijn.host IMAP drafts")
    parser.add_argument("--lead-prefix", required=True)
    parser.add_argument("--expected-count", required=True, type=int)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    try:
        result = sync_queue_drafts(
            lead_prefix=args.lead_prefix.strip(),
            expected_count=args.expected_count,
            spreadsheet_id=os.getenv("OUTREACH_SPREADSHEET_ID", ""),
            apply=args.apply,
            report_path=args.report,
        )
    except (RuntimeError, ValueError, OSError, imaplib.IMAP4.error) as exc:
        print(f"MYHOST_QUEUE_DRAFT_SYNC=blocked detail={exc} smtp_send=not_invoked")
        return 2

    counts = result.get("counts", {})
    marker = "green" if args.apply else "preflight_green"
    print(
        f"MYHOST_QUEUE_DRAFT_SYNC={marker} "
        f"target={counts.get('target', 0)} create={counts.get('create', 0)} "
        f"replace={counts.get('replace', 0)} unchanged={counts.get('unchanged', 0)} "
        f"final_readback={counts.get('final_readback', 0)} smtp_send=not_invoked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
