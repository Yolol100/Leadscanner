#!/usr/bin/env python3
"""Read-only, privacy-safe audit of existing Leadscanner Draft copy.

This module never writes, moves, creates, replaces or sends mail. It checks
structure only, not the truth of page findings or legal permission to send.
No recipient addresses, message bodies, lead IDs or individual scores leave
memory. A green audit run is NOT approval to send.
"""
from __future__ import annotations

from collections import Counter
from email.parser import BytesParser
from email.policy import default
import json
import re

EXPECTED_TOTAL = 1173
EXPECTED_ACTIVE = 509
EXPECTED_HELD = 664
BATCH_SIZE = 50
ALLOWED_RESULTS = (
    "legacy_single_or_two_points",
    "three_to_six_points_missing",
    "points_not_sequential",
    "practical_fixes_missing",
    "generic_page_title_or_copy",
    "optout_or_signature_missing",
    "subject_count_mismatch",
    "structure_only_needs_source_and_human_review",
)


def classify_copy(subject: str, body: str) -> str:
    """One mutually exclusive reason, never text from the email itself."""
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    lowered = text.casefold()
    if (
        "op jullie website viel me dit detail op" in lowered
        or "i noticed one detail on your website" in lowered
        or re.search(r"reserveren\s*[-–—|]\s*[^\n]+?[-–—|]\s*[^\n]+", lowered)
    ):
        return "generic_page_title_or_copy"
    labels = [int(x) for x in re.findall(r"(?m)^\s*([1-9])\.\s+\S", text)]
    if len(labels) < 3:
        return "legacy_single_or_two_points"
    if len(labels) > 6:
        return "three_to_six_points_missing"
    if labels != list(range(1, len(labels) + 1)):
        return "points_not_sequential"
    fixes_nl = len(re.findall(r"(?im)^\s*verbeteridee\s*:", text))
    fixes_en = len(re.findall(r"(?im)^\s*suggested improvement\s*:", text))
    if (fixes_nl + fixes_en) != len(labels):
        return "practical_fixes_missing"
    if (
        not (
            "als je geen interesse hebt, hoef je niet te reageren." in lowered
            or "if you're not interested, there's no need to reply." in lowered
        )
        or not (
            text.strip().endswith("Met vriendelijke groeten,\nAndrew")
            or text.strip().endswith("Kind regards,\nAndrew")
        )
    ):
        return "optout_or_signature_missing"
    if not re.match(r"^[3-6]\s+", subject.casefold().strip()):
        return "subject_count_mismatch"
    if not subject.casefold().strip().startswith(str(len(labels)) + " "):
        return "subject_count_mismatch"
    return "structure_only_needs_source_and_human_review"


def batch_summaries(rows: list[tuple[str, str]], *, size: int = BATCH_SIZE) -> dict:
    if size != 50:
        raise ValueError("fixed_50_draft_batches_required")
    totals: Counter[str] = Counter()
    batches = []
    for start in range(0, len(rows), size):
        chunk = rows[start:start + size]
        per_batch: Counter[str] = Counter(
            classify_copy(subject, body) for subject, body in chunk
        )
        totals.update(per_batch)
        batches.append({
            "batch": (start // size) + 1,
            "checked": len(chunk),
            "counts": {key: per_batch.get(key, 0) for key in ALLOWED_RESULTS},
        })
    if sum(totals.values()) != len(rows):
        raise RuntimeError("quality_audit_accounting_mismatch")
    return {
        "checked": len(rows),
        "batches": batches,
        "counts": {key: totals.get(key, 0) for key in ALLOWED_RESULTS},
        "automatic_send": False,
        "mailbox_writes": False,
        "source_truth_verified": False,
        "send_approved": False,
    }


def fetch_existing_copy(client, folder: str, lead_id: str) -> tuple[str, str]:
    from myhost_draft import (
        find_message_ids, lead_id_from_message, select_folder,
    )
    select_folder(client, folder, readonly=True)
    matches = find_message_ids(client, folder, lead_id, ensure_selected=False)
    if len(matches) != 1:
        raise RuntimeError("quality_audit_target_not_unique")
    # BODY.PEEK[] must not set the Seen flag, even on servers that allow it.
    status, payload = client.fetch(matches[0], "(BODY.PEEK[])")
    if status != "OK":
        raise RuntimeError("quality_audit_read_failed")
    raw = next(
        (part[1] for part in payload or []
         if isinstance(part, tuple) and isinstance(part[1], bytes)),
        None,
    )
    if raw is None:
        raise RuntimeError("quality_audit_readback_missing")
    msg = BytesParser(policy=default).parsebytes(raw)
    if lead_id_from_message(msg) != lead_id:
        raise RuntimeError("quality_audit_lead_identity_changed")
    if msg.is_multipart():
        part = msg.get_body(preferencelist=("plain",))
        body = part.get_content() if part is not None else ""
    else:
        body = msg.get_content()
    if not isinstance(body, str):
        body = ""
    return str(msg.get("Subject", "")), body


def live_audit() -> dict:
    from _once_myhost_existing_rewrite import inventory_existing
    from _once_myhost_safe_hold import HOLD_FOLDER, validate_hold_inventory
    from myhost_draft import connect_imap, find_drafts_folder
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        active, held = validate_hold_inventory(
            client, folder, HOLD_FOLDER, inventory_existing, EXPECTED_TOTAL
        )
        if (len(active), len(held)) != (EXPECTED_ACTIVE, EXPECTED_HELD):
            raise RuntimeError("quality_audit_inventory_changed")
        rows = [fetch_existing_copy(client, folder, item["lead_id"]) for item in active]
        report = batch_summaries(rows)
        if report["checked"] != EXPECTED_ACTIVE:
            raise RuntimeError("quality_audit_incomplete")
        return {
            "status": "green",
            "inventory": {
                "active": len(active), "held": len(held),
                "total": EXPECTED_TOTAL,
            },
            **report,
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


if __name__ == "__main__":
    # Public Actions logs contain counters only, never private text or errors.
    try:
        output = live_audit()
    except Exception:
        print("DRAFT_QUALITY_READONLY=red private_details_suppressed")
        raise SystemExit(1)
    print("DRAFT_QUALITY_READONLY=green " + json.dumps(output, sort_keys=True))
