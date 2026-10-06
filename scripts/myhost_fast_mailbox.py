"""UID-based bulk IMAP inventory and exact bounded draft mutation helpers."""
from __future__ import annotations

import imaplib
import re
from email.parser import BytesParser
from email.policy import default

from myhost_draft import (
    LEAD_ID_RE,
    exact_message_matches,
    fetch_message_uid,
    normalize_text,
    plain_body,
    require_uidplus,
    select_folder,
    uid_expunge_only,
)

HEADER_FETCH = "(BODY.PEEK[HEADER.FIELDS (X-Webactueel-Lead-ID)])"
HEADER_CHUNK = 250


def snapshot_message(msg, lead_id: str) -> dict:
    return {
        "lead_id": lead_id,
        "to": normalize_text(msg.get("To", "")),
        "subject": normalize_text(msg.get("Subject", "")),
        "body": plain_body(msg),
        "review_status": normalize_text(msg.get("X-Webactueel-Review-Required", "")),
        "actual_lead_id": normalize_text(msg.get("X-Webactueel-Lead-ID", "")),
        "count": 1,
        "duplicate": False,
    }


def _uid_from_meta(meta: bytes) -> bytes | None:
    match = re.search(rb"\bUID\s+(\d+)\b", meta or b"")
    return match.group(1) if match else None


def search_lead_uids(client, folder: str, lead_id: str, *, ensure_selected: bool = True) -> list[bytes]:
    if ensure_selected:
        select_folder(client, folder, readonly=True)
    status, data = client.uid("search", None, "HEADER", "X-Webactueel-Lead-ID", f'"{lead_id}"')
    if status != "OK":
        raise RuntimeError(f"Could not search draft UID readback for {lead_id}")
    return list((data[0] if data else b"").split())


def bulk_inventory_drafts(client, folder: str, lead_ids) -> dict[str, dict]:
    ordered = list(dict.fromkeys(str(value or "").strip() for value in lead_ids))
    if any(not LEAD_ID_RE.fullmatch(lead_id) for lead_id in ordered):
        raise ValueError("bulk inventory requires canonical growth lead IDs")
    targets = set(ordered)
    inventory = {lead_id: {"uids": [], "messages": []} for lead_id in ordered}
    select_folder(client, folder, readonly=True)
    status, data = client.uid("search", None, "ALL")
    if status != "OK":
        raise RuntimeError("Could not inventory mijn.host drafts")
    all_uids = list((data[0] if data else b"").split())

    matched: dict[str, list[bytes]] = {lead_id: [] for lead_id in ordered}
    for start in range(0, len(all_uids), HEADER_CHUNK):
        chunk = all_uids[start:start + HEADER_CHUNK]
        if not chunk:
            continue
        uid_set = b",".join(chunk).decode("ascii")
        status, rows = client.uid("fetch", uid_set, HEADER_FETCH)
        if status != "OK":
            raise RuntimeError("Could not bulk-fetch growth draft headers")
        for item in rows or []:
            if not (isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray))):
                continue
            meta = bytes(item[0]) if isinstance(item[0], (bytes, bytearray)) else str(item[0]).encode()
            uid = _uid_from_meta(meta)
            if uid is None:
                raise RuntimeError("Bulk UID header readback omitted UID metadata")
            header = BytesParser(policy=default).parsebytes(bytes(item[1]))
            lead_id = normalize_text(header.get("X-Webactueel-Lead-ID", ""))
            if lead_id in targets:
                matched[lead_id].append(uid)

    for lead_id in ordered:
        uids = matched[lead_id]
        inventory[lead_id]["uids"] = list(uids)
        inventory[lead_id]["messages"] = [fetch_message_uid(client, uid) for uid in uids]
    return inventory


def current_from_inventory(inventory: dict[str, dict], lead_id: str) -> dict:
    entry = inventory.get(lead_id) or {"uids": [], "messages": []}
    uids = list(entry.get("uids") or [])
    messages = list(entry.get("messages") or [])
    if len(uids) != len(messages):
        raise RuntimeError(f"Inventory UID/message mismatch for {lead_id}")
    if len(uids) != 1:
        return {"lead_id": lead_id, "count": len(uids), "duplicate": len(uids) > 1}
    return snapshot_message(messages[0], lead_id)


def uid_from_inventory(inventory: dict[str, dict], lead_id: str) -> bytes | None:
    entry = inventory.get(lead_id) or {"uids": []}
    uids = list(entry.get("uids") or [])
    return uids[0] if len(uids) == 1 else None


def _assert_expected_snapshot(msg, lead_id: str, expected_snapshot: dict) -> None:
    current = snapshot_message(msg, lead_id)
    if current != expected_snapshot:
        raise RuntimeError(f"Current draft changed since exact audit for {lead_id}")


def replace_known_draft_and_verify(client, folder: str, lead_id: str, existing_uid: bytes, expected_msg, expected_snapshot: dict):
    if not existing_uid:
        raise RuntimeError(f"Missing known draft UID for {lead_id}")
    select_folder(client, folder, readonly=True)
    actual = fetch_message_uid(client, existing_uid)
    _assert_expected_snapshot(actual, lead_id, expected_snapshot)
    if exact_message_matches(actual, expected_msg):
        return "existing", existing_uid, actual

    # Replacement must be provably target-only before any mailbox mutation.
    # Without UIDPLUS we may not append a second draft that cannot be safely
    # reduced back to exactly one.
    require_uidplus(client, "bounded draft replacement")

    raw = expected_msg.as_bytes(policy=default)
    status, _ = client.append(
        folder,
        "(\\Draft)",
        imaplib.Time2Internaldate(__import__("time").time()),
        raw,
    )
    if status != "OK":
        raise RuntimeError(f"IMAP APPEND failed for {lead_id}")

    select_folder(client, folder, readonly=True)
    uids_after_append = search_lead_uids(client, folder, lead_id, ensure_selected=False)
    new_uids = [uid for uid in uids_after_append if uid != existing_uid]
    if len(new_uids) != 1 or existing_uid not in uids_after_append:
        raise RuntimeError(f"Expected one old and one new draft UID after append for {lead_id}")
    new_uid = new_uids[0]
    new_actual = fetch_message_uid(client, new_uid)
    if not exact_message_matches(new_actual, expected_msg):
        raise RuntimeError(f"Draft UID readback mismatch after append for {lead_id}")

    old_actual = fetch_message_uid(client, existing_uid)
    _assert_expected_snapshot(old_actual, lead_id, expected_snapshot)
    uid_expunge_only(
        client,
        folder,
        existing_uid,
        operation=f"bounded draft replacement for {lead_id}",
    )

    select_folder(client, folder, readonly=True)
    final_uids = search_lead_uids(client, folder, lead_id, ensure_selected=False)
    if final_uids != [new_uid]:
        raise RuntimeError(f"Expected one final draft UID after replacement for {lead_id}")
    final_actual = fetch_message_uid(client, new_uid)
    if not exact_message_matches(final_actual, expected_msg):
        raise RuntimeError(f"Final UID replacement readback mismatch for {lead_id}")
    return "replaced", new_uid, final_actual


def delete_known_draft_and_verify(client, folder: str, lead_id: str, existing_uid: bytes, expected_snapshot: dict) -> int:
    if not existing_uid:
        return 0
    select_folder(client, folder, readonly=True)
    actual = fetch_message_uid(client, existing_uid)
    _assert_expected_snapshot(actual, lead_id, expected_snapshot)
    if normalize_text(actual.get("X-Webactueel-Lead-ID", "")) != lead_id:
        raise RuntimeError(f"Current draft lead identity mismatch for {lead_id}")
    if normalize_text(actual.get("X-Webactueel-Review-Required", "")) != "contact-basis":
        raise RuntimeError(f"Current draft is not review-required for {lead_id}")

    actual = fetch_message_uid(client, existing_uid)
    _assert_expected_snapshot(actual, lead_id, expected_snapshot)
    require_uidplus(client, "target-only hold deletion")
    uid_expunge_only(
        client,
        folder,
        existing_uid,
        operation=f"target-only hold deletion for {lead_id}",
    )
    select_folder(client, folder, readonly=True)
    if search_lead_uids(client, folder, lead_id, ensure_selected=False):
        raise RuntimeError(f"Hold draft still present after UID removal for {lead_id}")
    return 1
