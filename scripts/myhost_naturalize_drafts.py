from __future__ import annotations

import argparse
import imaplib
import json
import re
import time
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default
from email.utils import getaddresses

from myhost_draft import (
    LEAD_ID_RE,
    build_message,
    connect_imap,
    create_drafts,
    exact_message_matches,
    fetch_message,
    fetch_message_uid,
    find_drafts_folder,
    find_message_ids,
    normalize_text,
    plain_body,
    require_uidplus,
    select_folder,
    uid_expunge_only,
    uid_for_message_id,
)
from myhost_fast_mailbox import search_lead_uids
from prepare_growth_batch import build_template_from_opening, naturalize_existing_opening, subject_for_company, validate_short_first_touch


PRICE_MIN = 250
PRICE_MAX = 500
MAX_REWRITE = 100


def detect_language(subject: str, body: str) -> str:
    if subject.casefold().startswith("an idea for ") or body.lstrip().startswith("Hello,"):
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
        if subject.casefold().startswith("an idea for "):
            return subject[len("an idea for "):].strip()
    else:
        match = re.search(r"Zal ik vrijblijvend een voorbeeld design maken voor (.+?)\?", body)
        if match:
            return match.group(1).strip()
        if subject.casefold().startswith("idee voor "):
            return subject[len("idee voor "):].strip()
    raise RuntimeError("Could not recover company label from existing growth draft")


def extract_opening(body: str, language: str) -> str:
    paragraphs = [
        normalize_text(part)
        for part in re.split(r"\n\s*\n", normalize_text(body))
        if normalize_text(part)
    ]
    expected_greetings = {"Hello,"} if language == "en" else {"Goedendag,", "Hallo,"}
    if len(paragraphs) < 2 or paragraphs[0] not in expected_greetings:
        raise RuntimeError("Existing growth draft has an unsupported greeting/layout")

    opening = naturalize_existing_opening(paragraphs[1], language)
    generic_prefix = (
        "I looked through your website."
        if language == "en"
        else "Ik heb jullie website bekeken."
    )
    if opening == generic_prefix:
        return ""
    if opening.startswith(generic_prefix + " "):
        return opening[len(generic_prefix):].strip()
    return opening


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

    original_subject = normalize_text(msg.get("Subject", ""))
    body = plain_body(msg)
    language = detect_language(original_subject, body)

    short_subject = original_subject.casefold()
    try:
        validate_short_first_touch(short_subject, body)
    except ValueError:
        pass
    else:
        company = extract_company_label(original_subject, body, language)
        return {
            "lead_id": lead_id,
            "email": single_recipient(msg),
            "subject": short_subject,
            "body": body,
            "status": "review_draft",
            "contact_basis_status": "review_required",
            "language": language,
            "company": company,
            "_already_natural": normalize_text(original_subject) == short_subject,
        }

    company = extract_company_label(original_subject, body, language)
    opening = extract_opening(body, language)
    subject = subject_for_company(company, language)
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
        "_already_natural": (
            normalize_text(new_body) == normalize_text(body)
            and normalize_text(subject) == normalize_text(original_subject)
        ),
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


def _bulk_fetch_messages(client, message_ids: list[bytes]) -> dict[bytes, EmailMessage]:
    messages: dict[bytes, EmailMessage] = {}
    for start in range(0, len(message_ids), 100):
        chunk = message_ids[start: start + 100]
        if not chunk:
            continue
        status, data = client.fetch(b",".join(chunk), "(RFC822)")
        if status != "OK":
            raise RuntimeError("Could not bulk-fetch drafts for readback")
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
            messages[match.group(1)] = BytesParser(policy=default).parsebytes(bytes(item[1]))
    missing = [message_id for message_id in message_ids if message_id not in messages]
    if missing:
        raise RuntimeError(f"Bulk draft readback missed {len(missing)} messages")
    return messages


def _message_matches_rewrite_row(msg: EmailMessage, row: dict) -> bool:
    return (
        single_recipient(msg).casefold() == str(row.get("email") or "").strip().casefold()
        and normalize_text(msg.get("Subject", "")) == normalize_text(row.get("subject"))
        and normalize_text(msg.get("X-Webactueel-Review-Required", "")) == "contact-basis"
        and plain_body(msg) == normalize_text(row.get("body"))
    )


def _duplicate_growth_lead_ids_since(client, since_imap: str) -> list[str]:
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
    indexed = _bulk_index_growth_headers(
        client,
        list((data[0] if data else b"").split()),
    )
    counts: dict[str, int] = {}
    for lead_id, _ in indexed:
        counts[lead_id] = counts.get(lead_id, 0) + 1
    return sorted(lead_id for lead_id, count in counts.items() if count > 1)


def _collapse_same_lead_duplicate(client, folder: str, lead_id: str) -> int:
    ids = find_message_ids(client, folder, lead_id)
    if len(ids) <= 1:
        return 0

    messages = [fetch_message(client, message_id) for message_id in ids]
    rows = [rewrite_row_from_message(msg) for msg in messages]
    expected = rows[0]
    for row in rows[1:]:
        for key in ("email", "subject", "body", "contact_basis_status"):
            if normalize_text(row.get(key)) != normalize_text(expected.get(key)):
                raise RuntimeError(
                    f"Duplicate physical drafts disagree on canonical rewrite for {lead_id}: {key}"
                )

    matching = [
        message_id
        for message_id, msg in zip(ids, messages)
        if _message_matches_rewrite_row(msg, expected)
    ]
    keep_id = matching[-1] if matching else ids[-1]

    select_folder(client, folder, readonly=True)
    current_ids = find_message_ids(client, folder, lead_id, ensure_selected=False)
    if current_ids != ids:
        raise RuntimeError(f"Duplicate draft set changed during cleanup for {lead_id}")

    require_uidplus(client, f"duplicate physical draft cleanup for {lead_id}")
    remove_uids = [
        uid_for_message_id(client, message_id)
        for message_id in current_ids
        if message_id != keep_id
    ]
    for target_uid in remove_uids:
        uid_expunge_only(
            client,
            folder,
            target_uid,
            operation=f"duplicate physical draft cleanup for {lead_id}",
        )

    final_ids = find_message_ids(client, folder, lead_id)
    if len(final_ids) != 1:
        raise RuntimeError(
            f"Expected one physical draft after duplicate cleanup for {lead_id}, found {len(final_ids)}"
        )
    final_msg = fetch_message(client, final_ids[0])
    final_row = rewrite_row_from_message(final_msg)
    for key in ("email", "subject", "body", "contact_basis_status"):
        if normalize_text(final_row.get(key)) != normalize_text(expected.get(key)):
            raise RuntimeError(f"Duplicate cleanup readback mismatch for {lead_id}: {key}")
    return len(ids) - 1


def run_dedupe_same_id_since(since_imap: str, offset: int, limit: int) -> dict:
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if not 1 <= limit <= MAX_REWRITE:
        raise ValueError(f"limit must be 1-{MAX_REWRITE}")

    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        select_folder(client, folder, readonly=True)
        duplicate_ids = _duplicate_growth_lead_ids_since(client, since_imap)
        selected = duplicate_ids[offset: offset + limit]
        removed = 0
        for lead_id in selected:
            removed += _collapse_same_lead_duplicate(client, folder, lead_id)

        select_folder(client, folder, readonly=True)
        remaining = _duplicate_growth_lead_ids_since(client, since_imap)
        return {
            "mode": "dedupe_same_id_since",
            "draft_folder": folder,
            "review_growth_total": len(duplicate_ids),
            "naturalized_count": 0,
            "pending_count": len(remaining),
            "selected_count": len(selected),
            "replaced_count": 0,
            "existing_count": 0,
            "created_count": 0,
            "removed_duplicate_count": removed,
            "smtp_send": "not_available",
            "read_only": False,
            "since_imap": since_imap,
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


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



def read_review_growth_rows_slice_all(
    offset: int,
    limit: int,
) -> tuple[str, int, list[dict]]:
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        select_folder(client, folder, readonly=True)
        status, data = client.search(
            None,
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
        rows = [
            rewrite_row_from_message(fetch_message(client, message_id))
            for _, message_id in selected_ids
        ]
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


def run_inventory_slice(offset: int, limit: int) -> dict:
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if not 1 <= limit <= MAX_REWRITE:
        raise ValueError(f"limit must be 1-{MAX_REWRITE}")

    folder, total, rows = read_review_growth_rows_slice_all(offset, limit)
    natural = sum(1 for row in rows if row["_already_natural"])
    return {
        "mode": "inventory_slice",
        "draft_folder": folder,
        "review_growth_total": total,
        "naturalized_count": natural,
        "pending_count": len(rows) - natural,
        "offset": offset,
        "limit": limit,
        "selected_count": len(rows),
        "replaced_count": 0,
        "existing_count": natural,
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




def run_count_all() -> dict:
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        select_folder(client, folder, readonly=True)
        status, data = client.search(
            None,
            "HEADER",
            "X-Webactueel-Review-Required",
            '"contact-basis"',
        )
        if status != "OK":
            raise RuntimeError("Could not count mijn.host growth review drafts")
        indexed = _bulk_index_growth_headers(
            client,
            list((data[0] if data else b"").split()),
        )
        seen: set[str] = set()
        for lead_id, _ in indexed:
            if lead_id in seen:
                raise RuntimeError(f"Duplicate growth review draft detected for {lead_id}")
            seen.add(lead_id)
        total = len(indexed)
        return {
            "mode": "count_all",
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
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


def run_rewrite_slice(offset: int, limit: int) -> dict:
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if not 1 <= limit <= MAX_REWRITE:
        raise ValueError(f"limit must be 1-{MAX_REWRITE}")

    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        select_folder(client, folder, readonly=True)
        status, data = client.search(
            None,
            "HEADER",
            "X-Webactueel-Review-Required",
            '"contact-basis"',
        )
        if status != "OK":
            raise RuntimeError("Could not inventory mijn.host growth review drafts")

        indexed = _bulk_index_growth_headers(
            client,
            list((data[0] if data else b"").split()),
        )
        by_lead: dict[str, list[bytes]] = {}
        for lead_id, message_id in indexed:
            by_lead.setdefault(lead_id, []).append(message_id)
        duplicates = [lead_id for lead_id, ids in by_lead.items() if len(ids) != 1]
        if duplicates:
            raise RuntimeError(f"Duplicate growth review draft detected for {duplicates[0]}")

        indexed.sort(key=lambda item: item[0])
        selected_pairs = indexed[offset: offset + limit]
        selected_ids = [message_id for _, message_id in selected_pairs]
        originals = _bulk_fetch_messages(client, selected_ids)

        prepared: list[tuple[str, bytes, dict, EmailMessage]] = []
        skipped: list[tuple[str, bytes, EmailMessage]] = []
        existing_count = 0
        for lead_id, old_id in selected_pairs:
            try:
                row = rewrite_row_from_message(originals[old_id])
            except ValueError as exc:
                if str(exc) != "unsupported existing Dutch verified opening":
                    raise
                skipped.append((lead_id, old_id, originals[old_id]))
                continue
            expected_lead_id, expected = build_message(
                {k: v for k, v in row.items() if not k.startswith("_")}
            )
            if expected_lead_id != lead_id:
                raise RuntimeError(f"Rewrite lead-id mismatch for {lead_id}")
            if row.get("_already_natural"):
                if not exact_message_matches(originals[old_id], expected):
                    raise RuntimeError(f"Existing exact readback mismatch for {lead_id}")
                existing_count += 1
            else:
                prepared.append((lead_id, old_id, row, expected))

        appended_leads: list[str] = []
        old_uid_by_lead: dict[str, bytes] = {}
        new_uid_by_lead: dict[str, bytes] = {}
        old_removed_leads: set[str] = set()
        try:
            if prepared:
                require_uidplus(client, "naturalize rewrite slice")
                select_folder(client, folder, readonly=True)
                for lead_id, old_id, _, _ in prepared:
                    old_uid_by_lead[lead_id] = uid_for_message_id(client, old_id)

            for lead_id, _, _, expected in prepared:
                status, _ = client.append(
                    folder,
                    "(\\Draft)",
                    imaplib.Time2Internaldate(time.time()),
                    expected.as_bytes(policy=default),
                )
                if status != "OK":
                    raise RuntimeError(f"IMAP APPEND failed for {lead_id}")
                appended_leads.append(lead_id)

            for lead_id, old_id, _, expected in prepared:
                old_uid = old_uid_by_lead[lead_id]
                uids = search_lead_uids(client, folder, lead_id)
                candidates = [uid for uid in uids if uid != old_uid]
                if len(uids) != 2 or len(candidates) != 1:
                    raise RuntimeError(
                        f"Expected old+new draft after append for {lead_id}, found {len(uids)}"
                    )
                new_uid = candidates[0]
                new_uid_by_lead[lead_id] = new_uid
                appended = fetch_message_uid(client, new_uid)
                if not exact_message_matches(appended, expected):
                    raise RuntimeError(f"Appended draft exact readback mismatch for {lead_id}")

                current_old = fetch_message_uid(client, old_uid)
                if not exact_message_matches(current_old, originals[old_id]):
                    raise RuntimeError(f"Old draft changed before rewrite replacement for {lead_id}")

            for lead_id, _, _, _ in prepared:
                uid_expunge_only(
                    client,
                    folder,
                    old_uid_by_lead[lead_id],
                    operation=f"naturalize rewrite replacement for {lead_id}",
                )
                old_removed_leads.add(lead_id)
        except Exception as exc:
            rollback_errors: list[str] = []
            for lead_id in appended_leads:
                if lead_id in old_removed_leads:
                    continue
                new_uid = new_uid_by_lead.get(lead_id)
                if new_uid is None:
                    try:
                        old_uid = old_uid_by_lead.get(lead_id)
                        if old_uid is not None:
                            uids = search_lead_uids(client, folder, lead_id)
                            candidates = [uid for uid in uids if uid != old_uid]
                            if len(candidates) == 1:
                                new_uid = candidates[0]
                    except Exception as locate_exc:
                        rollback_errors.append(f"{lead_id}: locate rollback UID failed: {locate_exc}")
                        continue
                if new_uid is None:
                    rollback_errors.append(f"{lead_id}: rollback UID unavailable")
                    continue
                try:
                    uid_expunge_only(
                        client,
                        folder,
                        new_uid,
                        operation=f"rollback naturalize rewrite for {lead_id}",
                    )
                except Exception as rollback_exc:
                    rollback_errors.append(f"{lead_id}: {rollback_exc}")
            if rollback_errors:
                raise RuntimeError(
                    f"{exc}; rollback failures: {'; '.join(rollback_errors)}"
                ) from exc
            raise

        # Final exact readback after the old copies are gone. This verifies all
        # selected rows, including rows that were already exact before the run.
        select_folder(client, folder, readonly=True)
        status, data = client.search(
            None,
            "HEADER",
            "X-Webactueel-Review-Required",
            '"contact-basis"',
        )
        if status != "OK":
            raise RuntimeError("Could not perform final Growth draft inventory")
        final_index = _bulk_index_growth_headers(
            client,
            list((data[0] if data else b"").split()),
        )
        final_map: dict[str, list[bytes]] = {}
        for lead_id, message_id in final_index:
            final_map.setdefault(lead_id, []).append(message_id)

        final_ids: list[bytes] = []
        expected_by_final_id: dict[bytes, EmailMessage] = {}
        for lead_id, _, row, expected in prepared:
            ids = final_map.get(lead_id) or []
            if len(ids) != 1:
                raise RuntimeError(
                    f"Expected one final Growth draft for {lead_id}, found {len(ids)}"
                )
            final_ids.append(ids[0])
            expected_by_final_id[ids[0]] = expected

        skipped_leads = {lead_id for lead_id, _, _ in skipped}
        for lead_id, old_id in selected_pairs:
            if any(lead_id == pending_lead for pending_lead, _, _, _ in prepared):
                continue
            if lead_id in skipped_leads:
                continue
            row = rewrite_row_from_message(originals[old_id])
            expected_lead_id, expected = build_message(
                {k: v for k, v in row.items() if not k.startswith("_")}
            )
            if expected_lead_id != lead_id:
                raise RuntimeError(f"Final existing lead-id mismatch for {lead_id}")
            ids = final_map.get(lead_id) or []
            if len(ids) != 1:
                raise RuntimeError(
                    f"Expected one final existing Growth draft for {lead_id}, found {len(ids)}"
                )
            final_ids.append(ids[0])
            expected_by_final_id[ids[0]] = expected

        for lead_id, _, original in skipped:
            ids = final_map.get(lead_id) or []
            if len(ids) != 1:
                raise RuntimeError(
                    f"Expected one unchanged skipped Growth draft for {lead_id}, found {len(ids)}"
                )
            final_ids.append(ids[0])
            expected_by_final_id[ids[0]] = original

        finals = _bulk_fetch_messages(client, final_ids) if final_ids else {}
        for final_id, expected in expected_by_final_id.items():
            if not exact_message_matches(finals[final_id], expected):
                raise RuntimeError("Final Growth draft exact readback mismatch")

        selected_count = len(selected_pairs)
        replaced_count = len(prepared)
        skipped_count = len(skipped)
        if existing_count + replaced_count + skipped_count != selected_count:
            raise RuntimeError("rewrite selected outcome mismatch")

        return {
            "mode": "rewrite_slice",
            "draft_folder": folder,
            "review_growth_total": len(indexed),
            "naturalized_count": existing_count + replaced_count,
            "pending_count": max(len(indexed) - (offset + selected_count), 0),
            "offset": offset,
            "limit": limit,
            "selected_count": selected_count,
            "replaced_count": replaced_count,
            "existing_count": existing_count,
            "skipped_count": skipped_count,
            "created_count": 0,
            "smtp_send": "not_available",
            "read_only": False,
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass

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
    already_natural = [row for row in selected if row.get("_already_natural")]
    pending_rows = [row for row in selected if not row.get("_already_natural")]
    batch_rows = [{k: v for k, v in row.items() if not k.startswith("_")} for row in pending_rows]

    if pending_rows:
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
    if result.get("eligible_count") != len(pending_rows):
        raise RuntimeError("rewrite eligible_count mismatch")
    if result.get("review_required_count") != len(pending_rows):
        raise RuntimeError("rewrite review_required_count mismatch")
    if result.get("smtp_send") != "not_available":
        raise RuntimeError("SMTP/send boundary changed")

    existing_total = len(already_natural) + int(result.get("existing_count") or 0)
    replaced_total = int(result.get("replaced_count") or 0)
    if existing_total + replaced_total != len(selected):
        raise RuntimeError("rewrite selected outcome mismatch")

    return {
        "mode": "rewrite_since",
        "draft_folder": folder,
        "review_growth_total": total,
        "naturalized_count": len(selected),
        "pending_count": max(total - (offset + len(selected)), 0),
        "offset": offset,
        "limit": limit,
        "selected_count": len(selected),
        "replaced_count": replaced_total,
        "existing_count": existing_total,
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
    parser.add_argument("--mode", choices=("inventory", "inventory_slice", "rewrite", "rewrite_all", "count_all", "rewrite_slice", "count_since", "inventory_since", "rewrite_since", "dedupe_same_id_since"), required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--since-imap")
    args = parser.parse_args()

    if args.mode in {"count_since", "inventory_since", "rewrite_since", "dedupe_same_id_since"} and not args.since_imap:
        raise SystemExit("--since-imap is required for *_since modes")
    if args.mode == "inventory":
        result = run_inventory()
    elif args.mode == "inventory_slice":
        result = run_inventory_slice(args.offset, args.limit)
    elif args.mode == "count_all":
        result = run_count_all()
    elif args.mode == "rewrite_slice":
        result = run_rewrite_slice(args.offset, args.limit)
    elif args.mode == "count_since":
        result = run_count_since(args.since_imap)
    elif args.mode == "inventory_since":
        result = run_inventory_since(args.since_imap)
    elif args.mode == "rewrite_since":
        result = run_rewrite_since(args.since_imap, args.offset, args.limit)
    elif args.mode == "dedupe_same_id_since":
        result = run_dedupe_same_id_since(args.since_imap, args.offset, args.limit)
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
        f"skipped={result.get('skipped_count', 0)} "
        f"removed_duplicates={result.get('removed_duplicate_count', 0)} "
        "created=0 smtp_send=not_available"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
