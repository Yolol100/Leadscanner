from __future__ import annotations

import argparse
import json
import re
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default
from email.utils import getaddresses

from myhost_draft import (
    LEAD_ID_RE,
    connect_imap,
    create_drafts,
    fetch_message,
    find_drafts_folder,
    normalize_text,
    plain_body,
    select_folder,
)
from prepare_growth_batch import build_template_from_opening, naturalize_existing_opening


PRICE_MIN = 250
PRICE_MAX = 500
MAX_REWRITE = 100


def detect_language(subject: str, body: str) -> str:
    if subject.startswith("An idea for ") or body.lstrip().startswith("Hello,"):
        return "en"
    return "nl"


def extract_company_label(subject: str, body: str, language: str) -> str:
    if language == "en":
        match = re.search(
            r"Would you like me to make a no-obligation example design for (.+?)(?:, so|\?)",
            body,
        )
        if match:
            return match.group(1).strip()
        if subject.startswith("An idea for "):
            return subject[len("An idea for "):].strip()
    else:
        match = re.search(r"Zal ik vrijblijvend een voorbeeld design maken voor (.+?)\?", body)
        if match:
            return match.group(1).strip()
        if subject.startswith("Idee voor "):
            return subject[len("Idee voor "):].strip()
    raise RuntimeError("Could not recover company label from existing growth draft")


def extract_opening(body: str, language: str) -> str:
    paragraphs = [
        normalize_text(part)
        for part in re.split(r"\n\s*\n", normalize_text(body))
        if normalize_text(part)
    ]
    expected_greeting = "Hello," if language == "en" else "Goedendag,"
    if len(paragraphs) < 2 or paragraphs[0] != expected_greeting:
        raise RuntimeError("Existing growth draft has an unsupported greeting/layout")
    return naturalize_existing_opening(paragraphs[1], language)


def single_recipient(msg: EmailMessage) -> str:
    addresses = [address.strip() for _, address in getaddresses([str(msg.get("To", ""))]) if address.strip()]
    if len(addresses) != 1:
        raise RuntimeError("Existing growth draft must have exactly one recipient")
    return addresses[0]


def rewrite_row_from_message(msg: EmailMessage) -> dict:
    lead_id = normalize_text(msg.get("X-Webactueel-Lead-ID", ""))
    if not LEAD_ID_RE.fullmatch(lead_id):
        raise RuntimeError("Existing draft is missing a canonical growth lead id")
    if normalize_text(msg.get("X-Webactueel-Review-Required", "")) != "contact-basis":
        raise RuntimeError("Existing draft is not a review_required growth draft")

    subject = normalize_text(msg.get("Subject", ""))
    body = plain_body(msg)
    language = detect_language(subject, body)
    company = extract_company_label(subject, body, language)
    opening = extract_opening(body, language)
    new_body = build_template_from_opening(
        company,
        language,
        opening,
        price_min=PRICE_MIN,
        price_max=PRICE_MAX,
        variant_key=lead_id,
    )
    return {
        "lead_id": lead_id,
        "email": single_recipient(msg),
        "subject": subject,
        "body": new_body,
        "status": "review_draft",
        "contact_basis_status": "review_required",
        "language": language,
        "company": company,
        "_already_natural": normalize_text(new_body) == normalize_text(body),
    }


def _bulk_index_growth_headers(client, message_ids: list[bytes]) -> list[tuple[str, bytes]]:
    indexed: list[tuple[str, bytes]] = []
    for start in range(0, len(message_ids), 200):
        chunk = message_ids[start: start + 200]
        if not chunk:
            continue
        status, data = client.fetch(
            b",".join(chunk),
            "(BODY.PEEK[HEADER.FIELDS (X-Webactueel-Lead-ID)])",
        )
        if status != "OK":
            raise RuntimeError("Could not fetch growth lead-id headers")
        for item in data or []:
            if not (
                isinstance(item, tuple)
                and len(item) >= 2
                and isinstance(item[0], (bytes, bytearray))
                and isinstance(item[1], (bytes, bytearray))
            ):
                continue
            match = re.match(rb"^(\d+)", bytes(item[0]))
            if not match:
                continue
            header = BytesParser(policy=default).parsebytes(bytes(item[1]))
            lead_id = normalize_text(header.get("X-Webactueel-Lead-ID", ""))
            if LEAD_ID_RE.fullmatch(lead_id):
                indexed.append((lead_id, match.group(1)))
    return indexed


def read_review_growth_rows_slice(
    since_imap: str,
    offset: int,
    limit: int,
) -> tuple[str, int, list[dict]]:
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        select_folder(client, folder, readonly=True)
        status, data = client.search(
            None,
            "SINCE",
            since_imap,
            "HEADER",
            "X-Webactueel-Review-Required",
            '"contact-basis"',
        )
        if status != "OK":
            raise RuntimeError("Could not inventory mijn.host growth review drafts")

        message_ids = list((data[0] if data else b"").split())
        indexed = _bulk_index_growth_headers(client, message_ids)
        seen: set[str] = set()
        for lead_id, _ in indexed:
            if lead_id in seen:
                raise RuntimeError(f"Duplicate growth review draft detected for {lead_id}")
            seen.add(lead_id)

        indexed.sort(key=lambda item: item[0])
        selected_ids = indexed[offset: offset + limit]
        rows = [rewrite_row_from_message(fetch_message(client, message_id)) for _, message_id in selected_ids]
        return folder, len(indexed), rows
    finally:
        try:
            client.logout()
        except Exception:
            pass


def read_review_growth_rows(since_imap: str | None = None) -> tuple[str, list[dict]]:
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        select_folder(client, folder, readonly=True)
        criteria: list[str] = []
        if since_imap:
            criteria.extend(["SINCE", since_imap])
        criteria.extend([
            "HEADER",
            "X-Webactueel-Review-Required",
            '"contact-basis"',
        ])
        status, data = client.search(None, *criteria)
        if status != "OK":
            raise RuntimeError("Could not inventory mijn.host growth review drafts")

        rows: list[dict] = []
        seen: set[str] = set()
        for message_id in (data[0] if data else b"").split():
            msg = fetch_message(client, message_id)
            lead_id = normalize_text(msg.get("X-Webactueel-Lead-ID", ""))
            if not LEAD_ID_RE.fullmatch(lead_id):
                continue
            if normalize_text(msg.get("X-Webactueel-Review-Required", "")) != "contact-basis":
                continue
            if lead_id in seen:
                raise RuntimeError(f"Duplicate growth review draft detected for {lead_id}")
            seen.add(lead_id)
            rows.append(rewrite_row_from_message(msg))

        rows.sort(key=lambda row: row["lead_id"])
        return folder, rows
    finally:
        try:
            client.logout()
        except Exception:
            pass


def run_inventory() -> dict:
    folder, rows = read_review_growth_rows()
    natural = sum(1 for row in rows if row["_already_natural"])
    return {
        "mode": "inventory",
        "draft_folder": folder,
        "review_growth_total": len(rows),
        "naturalized_count": natural,
        "pending_count": len(rows) - natural,
        "selected_count": 0,
        "replaced_count": 0,
        "existing_count": 0,
        "created_count": 0,
        "smtp_send": "not_available",
        "read_only": True,
    }


def run_rewrite(offset: int, limit: int) -> dict:
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if not 1 <= limit <= MAX_REWRITE:
        raise ValueError(f"limit must be 1-{MAX_REWRITE}")

    folder, rows = read_review_growth_rows()
    selected = rows[offset: offset + limit]
    batch_rows = [{k: v for k, v in row.items() if not k.startswith("_")} for row in selected]
    batch = {"rows": batch_rows}

    if selected:
        result = create_drafts(batch, rewrite_existing_only=True)
    else:
        result = {
            "eligible_count": 0,
            "created_count": 0,
            "existing_count": 0,
            "replaced_count": 0,
            "review_required_count": 0,
            "smtp_send": "not_available",
        }

    if result.get("created_count") != 0:
        raise RuntimeError("rewrite-existing-only unexpectedly created a missing draft")
    if result.get("eligible_count") != len(selected):
        raise RuntimeError("rewrite eligible_count mismatch")
    if result.get("review_required_count") != len(selected):
        raise RuntimeError("rewrite review_required_count mismatch")
    if result.get("smtp_send") != "not_available":
        raise RuntimeError("SMTP/send boundary changed")

    _, final_rows = read_review_growth_rows()
    final_natural = sum(1 for row in final_rows if row["_already_natural"])
    if len(final_rows) != len(rows):
        raise RuntimeError("growth review draft count changed during rewrite")

    return {
        "mode": "rewrite",
        "draft_folder": folder,
        "review_growth_total": len(rows),
        "naturalized_count": final_natural,
        "pending_count": len(final_rows) - final_natural,
        "offset": offset,
        "limit": limit,
        "selected_count": len(selected),
        "replaced_count": int(result.get("replaced_count") or 0),
        "existing_count": int(result.get("existing_count") or 0),
        "created_count": 0,
        "smtp_send": "not_available",
        "read_only": False,
    }



def run_count_since(since_imap: str) -> dict:
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        select_folder(client, folder, readonly=True)
        status, data = client.search(
            None,
            "SINCE",
            since_imap,
            "HEADER",
            "X-Webactueel-Review-Required",
            '"contact-basis"',
        )
        if status != "OK":
            raise RuntimeError("Could not count mijn.host growth review drafts")
        total = len((data[0] if data else b"").split())
        return {
            "mode": "count_since",
            "draft_folder": folder,
            "review_growth_total": total,
            "naturalized_count": 0,
            "pending_count": total,
            "selected_count": 0,
            "replaced_count": 0,
            "existing_count": 0,
            "created_count": 0,
            "smtp_send": "not_available",
            "read_only": True,
            "since_imap": since_imap,
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass

def run_inventory_since(since_imap: str) -> dict:
    folder, rows = read_review_growth_rows(since_imap)
    natural = sum(1 for row in rows if row["_already_natural"])
    return {
        "mode": "inventory_since",
        "draft_folder": folder,
        "review_growth_total": len(rows),
        "naturalized_count": natural,
        "pending_count": len(rows) - natural,
        "selected_count": 0,
        "replaced_count": 0,
        "existing_count": 0,
        "created_count": 0,
        "smtp_send": "not_available",
        "read_only": True,
        "since_imap": since_imap,
    }


def run_rewrite_since(since_imap: str, offset: int, limit: int) -> dict:
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if not 1 <= limit <= MAX_REWRITE:
        raise ValueError(f"limit must be 1-{MAX_REWRITE}")

    folder, total, selected = read_review_growth_rows_slice(since_imap, offset, limit)
    batch_rows = [{k: v for k, v in row.items() if not k.startswith("_")} for row in selected]

    if selected:
        result = create_drafts({"rows": batch_rows}, rewrite_existing_only=True)
    else:
        result = {
            "eligible_count": 0,
            "created_count": 0,
            "existing_count": 0,
            "replaced_count": 0,
            "review_required_count": 0,
            "smtp_send": "not_available",
        }

    if result.get("created_count") != 0:
        raise RuntimeError("rewrite-existing-only unexpectedly created a missing draft")
    if result.get("eligible_count") != len(selected):
        raise RuntimeError("rewrite eligible_count mismatch")
    if result.get("review_required_count") != len(selected):
        raise RuntimeError("rewrite review_required_count mismatch")
    if result.get("smtp_send") != "not_available":
        raise RuntimeError("SMTP/send boundary changed")

    return {
        "mode": "rewrite_since",
        "draft_folder": folder,
        "review_growth_total": total,
        "naturalized_count": int(result.get("replaced_count") or 0) + int(result.get("existing_count") or 0),
        "pending_count": max(total - (offset + len(selected)), 0),
        "offset": offset,
        "limit": limit,
        "selected_count": len(selected),
        "replaced_count": int(result.get("replaced_count") or 0),
        "existing_count": int(result.get("existing_count") or 0),
        "created_count": 0,
        "smtp_send": "not_available",
        "read_only": False,
        "since_imap": since_imap,
    }

def run_rewrite_all() -> dict:
    folder, rows = read_review_growth_rows()
    total = len(rows)
    replaced = 0
    existing = 0

    for start in range(0, total, MAX_REWRITE):
        selected = rows[start: start + MAX_REWRITE]
        batch_rows = [{k: v for k, v in row.items() if not k.startswith("_")} for row in selected]
        result = create_drafts({"rows": batch_rows}, rewrite_existing_only=True)
        if result.get("created_count") != 0:
            raise RuntimeError("rewrite-existing-only unexpectedly created a missing draft")
        if result.get("eligible_count") != len(selected):
            raise RuntimeError("rewrite eligible_count mismatch")
        if result.get("review_required_count") != len(selected):
            raise RuntimeError("rewrite review_required_count mismatch")
        if result.get("smtp_send") != "not_available":
            raise RuntimeError("SMTP/send boundary changed")
        replaced += int(result.get("replaced_count") or 0)
        existing += int(result.get("existing_count") or 0)

    if replaced + existing != total:
        raise RuntimeError("rewrite-all outcome count mismatch")

    return {
        "mode": "rewrite_all",
        "draft_folder": folder,
        "review_growth_total": total,
        "naturalized_count": total,
        "pending_count": 0,
        "selected_count": total,
        "replaced_count": replaced,
        "existing_count": existing,
        "created_count": 0,
        "smtp_send": "not_available",
        "read_only": False,
    }

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("inventory", "rewrite", "rewrite_all", "count_since", "inventory_since", "rewrite_since"), required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--since-imap")
    args = parser.parse_args()

    if args.mode in {"count_since", "inventory_since", "rewrite_since"} and not args.since_imap:
        raise SystemExit("--since-imap is required for *_since modes")
    if args.mode == "inventory":
        result = run_inventory()
    elif args.mode == "count_since":
        result = run_count_since(args.since_imap)
    elif args.mode == "inventory_since":
        result = run_inventory_since(args.since_imap)
    elif args.mode == "rewrite_since":
        result = run_rewrite_since(args.since_imap, args.offset, args.limit)
    elif args.mode == "rewrite_all":
        result = run_rewrite_all()
    else:
        result = run_rewrite(args.offset, args.limit)
    print(
        "MYHOST_NATURALIZE=green "
        f"mode={result['mode']} "
        f"total={result['review_growth_total']} "
        f"naturalized={result['naturalized_count']} "
        f"pending={result['pending_count']} "
        f"selected={result['selected_count']} "
        f"replaced={result['replaced_count']} "
        f"existing={result['existing_count']} "
        "created=0 smtp_send=not_available"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
