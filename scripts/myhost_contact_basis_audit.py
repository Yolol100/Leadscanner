from __future__ import annotations

import argparse
import hashlib
import imaplib
from copy import deepcopy
from email.message import EmailMessage

from myhost_draft import (
    LEAD_ID_RE,
    connect_imap,
    fetch_message,
    find_drafts_folder,
    find_message_ids,
    normalize_text,
    plain_body,
    select_folder,
)
from myhost_naturalize_drafts import _bulk_fetch_messages, _bulk_index_growth_headers, single_recipient

MAX_BATCH = 100
PASS_HEADER = "X-Webactueel-Contact-Basis"
PASS_SOURCE_HEADER = "X-Webactueel-Contact-Basis-Source"
REVIEW_HEADER = "X-Webactueel-Review-Required"


def email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().casefold().encode("utf-8")).hexdigest()


def validate_hashes(values: list[str]) -> set[str]:
    out: set[str] = set()
    for raw in values:
        value = str(raw or "").strip().casefold()
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("evidence hashes must be lowercase sha256 hex")
        out.add(value)
    return out


def growth_message_ids(client, folder: str) -> list[bytes]:
    select_folder(client, folder, readonly=True)
    status, data = client.search(None, "HEADER", "X-Webactueel-Lead-ID", '"growth-"')
    if status != "OK":
        raise RuntimeError("Could not inventory Growth drafts")
    return list((data[0] if data else b"").split())


def growth_index(client, folder: str) -> list[tuple[str, bytes]]:
    indexed = _bulk_index_growth_headers(client, growth_message_ids(client, folder))
    by_lead: dict[str, list[bytes]] = {}
    for lead_id, message_id in indexed:
        by_lead.setdefault(lead_id, []).append(message_id)
    duplicates = [lead_id for lead_id, ids in by_lead.items() if len(ids) != 1]
    if duplicates:
        raise RuntimeError(f"Duplicate Growth draft detected for {duplicates[0]}")
    indexed.sort(key=lambda item: item[0])
    return indexed


def is_ready(msg: EmailMessage) -> bool:
    return (
        normalize_text(msg.get(REVIEW_HEADER, "")) == ""
        and normalize_text(msg.get(PASS_HEADER, "")) == "pass"
    )


def is_review(msg: EmailMessage) -> bool:
    return normalize_text(msg.get(REVIEW_HEADER, "")) == "contact-basis"


def make_ready(msg: EmailMessage) -> EmailMessage:
    expected = deepcopy(msg)
    if expected.get(REVIEW_HEADER) is not None:
        del expected[REVIEW_HEADER]
    if expected.get(PASS_HEADER) is not None:
        expected.replace_header(PASS_HEADER, "pass")
    else:
        expected[PASS_HEADER] = "pass"
    if expected.get(PASS_SOURCE_HEADER) is not None:
        expected.replace_header(PASS_SOURCE_HEADER, "registry-approved-official-web")
    else:
        expected[PASS_SOURCE_HEADER] = "registry-approved-official-web"
    return expected


def make_review(msg: EmailMessage) -> EmailMessage:
    expected = deepcopy(msg)
    if expected.get(PASS_HEADER) is not None:
        del expected[PASS_HEADER]
    if expected.get(PASS_SOURCE_HEADER) is not None:
        del expected[PASS_SOURCE_HEADER]
    if expected.get(REVIEW_HEADER) is not None:
        expected.replace_header(REVIEW_HEADER, "contact-basis")
    else:
        expected[REVIEW_HEADER] = "contact-basis"
    return expected


def message_matches(actual: EmailMessage, expected: EmailMessage) -> bool:
    return (
        normalize_text(actual.get("To", "")) == normalize_text(expected.get("To", ""))
        and normalize_text(actual.get("Subject", "")) == normalize_text(expected.get("Subject", ""))
        and normalize_text(actual.get("X-Webactueel-Lead-ID", "")) == normalize_text(expected.get("X-Webactueel-Lead-ID", ""))
        and normalize_text(actual.get(REVIEW_HEADER, "")) == normalize_text(expected.get(REVIEW_HEADER, ""))
        and normalize_text(actual.get(PASS_HEADER, "")) == normalize_text(expected.get(PASS_HEADER, ""))
        and normalize_text(actual.get(PASS_SOURCE_HEADER, "")) == normalize_text(expected.get(PASS_SOURCE_HEADER, ""))
        and plain_body(actual) == plain_body(expected)
    )


def replace_and_verify(client, folder: str, lead_id: str, old_id: bytes, expected: EmailMessage) -> None:
    select_folder(client, folder, readonly=False)
    status, _ = client.append(
        folder,
        "(\\Draft)",
        imaplib.Time2Internaldate(None),
        expected.as_bytes(),
    )
    if status != "OK":
        raise RuntimeError(f"IMAP APPEND failed for {lead_id}")

    select_folder(client, folder, readonly=True)
    ids = find_message_ids(client, folder, lead_id, ensure_selected=False)
    new_ids = [message_id for message_id in ids if message_id != old_id]
    if len(ids) != 2 or len(new_ids) != 1:
        raise RuntimeError(f"Expected old+new draft for {lead_id}")
    appended = fetch_message(client, new_ids[0])
    if not message_matches(appended, expected):
        raise RuntimeError(f"Appended contact-basis readback mismatch for {lead_id}")

    select_folder(client, folder, readonly=False)
    status, _ = client.store(old_id, "+FLAGS", "(\\Deleted)")
    if status != "OK" or client.expunge()[0] != "OK":
        raise RuntimeError(f"Could not remove old draft for {lead_id}")

    select_folder(client, folder, readonly=True)
    final_ids = find_message_ids(client, folder, lead_id, ensure_selected=False)
    if len(final_ids) != 1:
        raise RuntimeError(f"Expected one final draft for {lead_id}, found {len(final_ids)}")
    final_msg = fetch_message(client, final_ids[0])
    if not message_matches(final_msg, expected):
        raise RuntimeError(f"Final contact-basis readback mismatch for {lead_id}")


def remove_and_verify(client, folder: str, lead_id: str, message_id: bytes) -> None:
    select_folder(client, folder, readonly=False)
    status, _ = client.store(message_id, "+FLAGS", "(\\Deleted)")
    if status != "OK" or client.expunge()[0] != "OK":
        raise RuntimeError(f"Could not suppress draft for {lead_id}")
    select_folder(client, folder, readonly=True)
    if find_message_ids(client, folder, lead_id, ensure_selected=False):
        raise RuntimeError(f"Suppressed draft still exists for {lead_id}")


def run_audit_slice(offset: int, limit: int, approved_hashes: set[str], suppressed_hashes: set[str]) -> dict:
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if not 1 <= limit <= MAX_BATCH:
        raise ValueError(f"limit must be 1-{MAX_BATCH}")
    overlap = approved_hashes & suppressed_hashes
    if overlap:
        raise RuntimeError("suppression and approval evidence overlap")

    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        indexed = growth_index(client, folder)
        selected_pairs = indexed[offset: offset + limit]
        selected_ids = [message_id for _, message_id in selected_pairs]
        originals = _bulk_fetch_messages(client, selected_ids) if selected_ids else {}

        promoted = 0
        demoted = 0
        removed_suppressed = 0
        ready_existing = 0
        review_existing = 0

        for lead_id, message_id in selected_pairs:
            msg = originals[message_id]
            if normalize_text(msg.get("X-Webactueel-Lead-ID", "")) != lead_id or not LEAD_ID_RE.fullmatch(lead_id):
                raise RuntimeError(f"Growth identity mismatch for {lead_id}")
            digest = email_hash(single_recipient(msg))

            if digest in suppressed_hashes:
                remove_and_verify(client, folder, lead_id, message_id)
                removed_suppressed += 1
                continue

            if digest in approved_hashes:
                if is_ready(msg):
                    ready_existing += 1
                else:
                    if not is_review(msg):
                        raise RuntimeError(f"Unsupported Growth draft state for {lead_id}")
                    replace_and_verify(client, folder, lead_id, message_id, make_ready(msg))
                    promoted += 1
                continue

            if is_review(msg):
                review_existing += 1
            elif is_ready(msg):
                replace_and_verify(client, folder, lead_id, message_id, make_review(msg))
                demoted += 1
            else:
                raise RuntimeError(f"Unsupported Growth draft state for {lead_id}")

        final_index = growth_index(client, folder)
        return {
            "mode": "contact_basis_slice",
            "growth_total": len(final_index),
            "selected_count": len(selected_pairs),
            "promoted_count": promoted,
            "demoted_count": demoted,
            "removed_suppressed_count": removed_suppressed,
            "ready_existing_count": ready_existing,
            "review_existing_count": review_existing,
            "created_count": 0,
            "smtp_send": "not_available",
            "read_only": False,
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


def run_inventory() -> dict:
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        indexed = growth_index(client, folder)
        messages = _bulk_fetch_messages(client, [message_id for _, message_id in indexed]) if indexed else {}
        ready = 0
        review = 0
        other = 0
        for _, message_id in indexed:
            msg = messages[message_id]
            if is_ready(msg):
                ready += 1
            elif is_review(msg):
                review += 1
            else:
                other += 1
        if other:
            raise RuntimeError(f"Found {other} Growth drafts in unsupported state")
        return {
            "mode": "contact_basis_inventory",
            "growth_total": len(indexed),
            "ready_count": ready,
            "review_count": review,
            "created_count": 0,
            "smtp_send": "not_available",
            "read_only": True,
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("audit_slice", "inventory"), required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--approved-hash", action="append", default=[])
    parser.add_argument("--suppressed-hash", action="append", default=[])
    args = parser.parse_args()

    approved = validate_hashes(args.approved_hash)
    suppressed = validate_hashes(args.suppressed_hash)

    if args.mode == "inventory":
        result = run_inventory()
        print(
            "MYHOST_CONTACT_BASIS=green "
            f"mode={result['mode']} total={result['growth_total']} "
            f"ready={result['ready_count']} review={result['review_count']} "
            "created=0 smtp_send=not_available"
        )
    else:
        result = run_audit_slice(args.offset, args.limit, approved, suppressed)
        print(
            "MYHOST_CONTACT_BASIS=green "
            f"mode={result['mode']} total={result['growth_total']} "
            f"selected={result['selected_count']} promoted={result['promoted_count']} "
            f"demoted={result['demoted_count']} suppressed_removed={result['removed_suppressed_count']} "
            f"ready_existing={result['ready_existing_count']} review_existing={result['review_existing_count']} "
            "created=0 smtp_send=not_available"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
