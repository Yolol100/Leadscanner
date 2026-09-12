from __future__ import annotations

import argparse
import imaplib
import json
import os
import ssl

from outreach_imap_draft import SAFE_TEST_ID, choose_mailbox, detect_drafts_folder
from outreach_mailboxes import enabled_mailboxes, load_mailboxes_from_env
from outreach_queue_imap_draft_sync import _delete_uid, _fetch_payload, _normalize_email, _snapshot_from_header, _uid_search


def delete_exact_draft(*, test_id: str, recipient: str, apply: bool, report_path: str = "") -> dict:
    if not SAFE_TEST_ID.fullmatch(test_id or ""):
        raise RuntimeError("test id is invalid")
    expected_recipient = _normalize_email(recipient)
    if not expected_recipient or "@" not in expected_recipient:
        raise RuntimeError("expected recipient is invalid")

    daily_limit = int(os.getenv("OUTREACH_DAILY_LIMIT", "20") or "20")
    mailboxes = enabled_mailboxes(load_mailboxes_from_env(mode="validate", default_daily_limit=daily_limit))
    mailbox = choose_mailbox(mailboxes, os.getenv("OUTREACH_DRAFT_MAILBOX_ID", ""))
    if not getattr(mailbox, "mail_password", ""):
        raise RuntimeError("OUTREACH_MAIL_PASSWORD is required for IMAP draft deletion")

    context = ssl.create_default_context()
    imap = imaplib.IMAP4_SSL(mailbox.imap_host, mailbox.imap_port, ssl_context=context)
    report = {
        "status": "blocked",
        "mode": "apply" if apply else "dry_run",
        "test_id": test_id,
        "recipient": expected_recipient,
        "mailbox_id": mailbox.mailbox_id,
        "sender_email": mailbox.sender_email,
        "smtp_send": "not_invoked",
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
        status, _ = imap.select(folder, readonly=not apply)
        if status != "OK":
            raise RuntimeError(f"failed to select Drafts folder: {folder}")

        ids = _uid_search(imap, "HEADER", "X-Webactueel-Draft-Test-ID", f'"{test_id}"')
        if len(ids) != 1:
            raise RuntimeError(f"expected exactly one draft for test id; found {len(ids)}")
        uid = ids[0]
        raw = _fetch_payload(imap, uid, "(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT X-Webactueel-Draft-Test-ID X-Webactueel-Transport)])")
        snapshot = _snapshot_from_header(uid, raw)
        if snapshot.sender != _normalize_email(mailbox.sender_email):
            raise RuntimeError("draft sender does not match configured sender")
        if snapshot.recipients != (expected_recipient,):
            raise RuntimeError("draft recipient does not exactly match expected recipient")
        if snapshot.test_id != test_id:
            raise RuntimeError("draft test id readback mismatch")
        if snapshot.transport not in {"", "imap-draft-only"}:
            raise RuntimeError("draft has unexpected transport marker")

        report["uid"] = uid
        report["subject"] = snapshot.subject
        if not apply:
            report["status"] = "preflight_green"
            return report

        _delete_uid(imap, uid)
        status, _ = imap.select(folder, readonly=False)
        if status != "OK":
            raise RuntimeError("failed to reselect Drafts folder after delete")
        remaining = _uid_search(imap, "HEADER", "X-Webactueel-Draft-Test-ID", f'"{test_id}"')
        if remaining:
            raise RuntimeError(f"delete readback expected zero drafts for test id; found {len(remaining)}")
        report["status"] = "green"
        report["final_test_id_count"] = 0
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
    parser = argparse.ArgumentParser(description="Delete one exact mijn.host draft by safe Webactueel test ID")
    parser.add_argument("--test-id", required=True)
    parser.add_argument("--recipient", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    try:
        result = delete_exact_draft(
            test_id=args.test_id,
            recipient=args.recipient,
            apply=args.apply,
            report_path=args.report,
        )
    except (RuntimeError, ValueError, OSError, imaplib.IMAP4.error) as exc:
        print(f"MYHOST_DRAFT_DELETE=blocked detail={exc} smtp_send=not_invoked")
        return 2

    marker = result.get("status", "blocked")
    print(
        f"MYHOST_DRAFT_DELETE={marker} test_id={args.test_id} recipient={_normalize_email(args.recipient)} "
        f"final_test_id_count={result.get('final_test_id_count', 1)} smtp_send=not_invoked"
    )
    return 0 if marker in {"green", "preflight_green"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
