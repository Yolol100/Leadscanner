"""UID-based bulk IMAP inventory and exact bounded draft mutation helpers."""
from __future__ import annotations

import imaplib
import os
import re
from email.parser import BytesParser
from email.policy import SMTP, default

from imapclient import IMAPClient

from myhost_draft import (
    LEAD_ID_RE,
    exact_message_matches,
    fetch_message_uid,
    normalize_text,
    plain_body,
    imap_capability_tokens,
    require_uidplus,
    select_folder,
    uid_expunge_only,
)

HEADER_FETCH = "(BODY.PEEK[HEADER.FIELDS (X-Webactueel-Lead-ID)])"
FULL_FETCH = "(UID RFC822)"
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


def bulk_fetch_uid_messages(client, uids) -> dict[bytes, object]:
    ordered = list(dict.fromkeys(uids))
    messages = {}
    for start in range(0, len(ordered), HEADER_CHUNK):
        chunk = ordered[start:start + HEADER_CHUNK]
        if not chunk:
            continue
        uid_set = b",".join(chunk).decode("ascii")
        status, rows = client.uid("fetch", uid_set, FULL_FETCH)
        if status != "OK":
            raise RuntimeError("Could not bulk-fetch growth draft messages")
        for item in rows or []:
            if not (
                isinstance(item, tuple)
                and len(item) >= 2
                and isinstance(item[1], (bytes, bytearray))
            ):
                continue
            meta = bytes(item[0]) if isinstance(item[0], (bytes, bytearray)) else str(item[0]).encode()
            uid = _uid_from_meta(meta)
            if uid is None:
                raise RuntimeError("Bulk full-message readback omitted UID metadata")
            messages[uid] = BytesParser(policy=default).parsebytes(bytes(item[1]))
    missing = [uid for uid in ordered if uid not in messages]
    if missing:
        raise RuntimeError(
            f"Bulk full-message readback missing {len(missing)} requested UID(s)"
        )
    return messages


def _append_uid_from_response(client, append_data) -> bytes | None:
    candidates = []
    for value in append_data or []:
        if isinstance(value, bytes):
            candidates.append(value)
        elif value is not None:
            candidates.append(str(value).encode("ascii", errors="ignore"))
    if hasattr(client, "response"):
        try:
            _code, values = client.response("APPENDUID")
            for value in values or []:
                if isinstance(value, bytes):
                    candidates.append(value)
                elif value is not None:
                    candidates.append(str(value).encode("ascii", errors="ignore"))
        except Exception:
            pass

    for raw in candidates:
        match = re.search(rb"APPENDUID\s+\d+\s+(\d+)\b", raw, re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.fullmatch(rb"\s*\d+\s+(\d+)\s*", raw)
        if match:
            return match.group(1)
    return None


def _response_bytes(value) -> list[bytes]:
    if value is None:
        return []
    if isinstance(value, bytes):
        return [value]
    if isinstance(value, str):
        return [value.encode("ascii", errors="ignore")]
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            out.extend(_response_bytes(item))
        return out
    return [str(value).encode("ascii", errors="ignore")]


def _expand_uid_set(value: bytes) -> list[bytes]:
    text = value.decode("ascii", errors="strict")
    out = []
    for part in text.split(","):
        if ":" in part:
            start_text, end_text = part.split(":", 1)
            start = int(start_text)
            end = int(end_text)
            step = 1 if end >= start else -1
            out.extend(str(uid).encode("ascii") for uid in range(start, end + step, step))
        else:
            out.append(str(int(part)).encode("ascii"))
    return out


def parse_multiappend_uids(response, expected_count: int) -> list[bytes]:
    if expected_count < 1:
        raise ValueError("expected_count must be positive")
    for raw in _response_bytes(response):
        match = re.search(
            rb"APPENDUID\s+\d+\s+([0-9:,]+)",
            raw,
            re.IGNORECASE,
        )
        if not match:
            continue
        uids = _expand_uid_set(match.group(1))
        if len(uids) != expected_count or len(set(uids)) != len(uids):
            raise RuntimeError("MULTIAPPEND APPENDUID count mismatch")
        return uids
    return []


def _connect_multiappend_client():
    host = os.getenv("OUTREACH_IMAP_HOST", "mail.andrewbaeten.nl").strip()
    port = int(os.getenv("OUTREACH_IMAP_PORT", "993"))
    user = os.getenv("OUTREACH_MAIL_USER", "info@andrewbaeten.nl").strip()
    password = os.getenv("OUTREACH_MAIL_PASSWORD", "")
    timeout = float(os.getenv("OUTREACH_IMAP_TIMEOUT_SECONDS", "15"))
    if not password:
        raise RuntimeError("OUTREACH_MAIL_PASSWORD is required for MULTIAPPEND")
    client = IMAPClient(host, port=port, ssl=True, timeout=timeout)
    client.login(user, password)
    return client


def multiappend_review_drafts(folder: str, messages) -> list[bytes]:
    messages = list(messages)
    if not messages:
        return []
    client = _connect_multiappend_client()
    try:
        if not client.has_capability("MULTIAPPEND"):
            raise RuntimeError("IMAP MULTIAPPEND is not available")
        if not client.has_capability("UIDPLUS"):
            raise RuntimeError("IMAP UIDPLUS is not available for MULTIAPPEND rollback")
        payloads = [
            {
                "msg": message.as_bytes(policy=SMTP),
                "flags": ("\\Draft",),
            }
            for message in messages
        ]
        response = client.multiappend(folder, payloads)
        uids = parse_multiappend_uids(response, len(messages))
        if not uids:
            raise RuntimeError("MULTIAPPEND completed without a usable APPENDUID set")
        return uids
    finally:
        try:
            client.logout()
        except Exception:
            pass


def _rollback_new_uids(client, folder: str, uids, *, operation: str) -> None:
    errors = []
    for uid in uids:
        try:
            uid_expunge_only(
                client,
                folder,
                uid,
                operation=operation,
            )
        except Exception as exc:
            errors.append(str(exc))
    if errors:
        raise RuntimeError(
            f"{operation} failed for {len(errors)} UID(s): " + "; ".join(errors[:3])
        )


def replace_known_drafts_multiappend_and_verify(
    client,
    folder: str,
    replacements,
    *,
    multiappend_func=None,
):
    rows = list(replacements)
    if not rows:
        return []

    tokens = imap_capability_tokens(client)
    if "UIDPLUS" not in tokens or "MULTIAPPEND" not in tokens:
        raise RuntimeError("MULTIAPPEND replacement requires UIDPLUS and MULTIAPPEND")

    lead_ids = [row["lead_id"] for row in rows]
    if len(set(lead_ids)) != len(lead_ids):
        raise RuntimeError("MULTIAPPEND replacement requires unique lead IDs")
    old_uids = [row["existing_uid"] for row in rows]
    if any(not uid for uid in old_uids) or len(set(old_uids)) != len(old_uids):
        raise RuntimeError("MULTIAPPEND replacement requires unique existing UIDs")

    select_folder(client, folder, readonly=True)
    old_messages = bulk_fetch_uid_messages(client, old_uids)
    for row in rows:
        _assert_expected_snapshot(
            old_messages[row["existing_uid"]],
            row["lead_id"],
            row["expected_snapshot"],
        )

    append = multiappend_func or multiappend_review_drafts
    new_uids = append(folder, [row["expected_msg"] for row in rows])
    if len(new_uids) != len(rows) or len(set(new_uids)) != len(new_uids):
        raise RuntimeError("MULTIAPPEND returned an invalid UID set")

    try:
        select_folder(client, folder, readonly=True)
        new_messages = bulk_fetch_uid_messages(client, new_uids)
        for row, new_uid in zip(rows, new_uids):
            if not exact_message_matches(new_messages[new_uid], row["expected_msg"]):
                raise RuntimeError(
                    f"MULTIAPPEND draft readback mismatch for {row['lead_id']}"
                )

        old_messages = bulk_fetch_uid_messages(client, old_uids)
        for row in rows:
            _assert_expected_snapshot(
                old_messages[row["existing_uid"]],
                row["lead_id"],
                row["expected_snapshot"],
            )
    except Exception as exc:
        try:
            _rollback_new_uids(
                client,
                folder,
                new_uids,
                operation="rollback uncommitted MULTIAPPEND shard",
            )
        except Exception as rollback_exc:
            raise RuntimeError(f"{exc}; {rollback_exc}") from exc
        raise

    committed = 0
    try:
        for row in rows:
            uid_expunge_only(
                client,
                folder,
                row["existing_uid"],
                operation=f"MULTIAPPEND replacement for {row['lead_id']}",
            )
            committed += 1
    except Exception as exc:
        rollback_uids = new_uids[committed:]
        if rollback_uids:
            try:
                _rollback_new_uids(
                    client,
                    folder,
                    rollback_uids,
                    operation="rollback uncommitted MULTIAPPEND replacements",
                )
            except Exception as rollback_exc:
                raise RuntimeError(f"{exc}; {rollback_exc}") from exc
        raise

    return [
        {
            "lead_id": row["lead_id"],
            "new_uid": new_uid,
            "message": new_messages[new_uid],
        }
        for row, new_uid in zip(rows, new_uids)
    ]


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

    matched_uids = [
        uid
        for lead_id in ordered
        for uid in matched[lead_id]
    ]
    messages_by_uid = bulk_fetch_uid_messages(client, matched_uids)

    for lead_id in ordered:
        uids = matched[lead_id]
        inventory[lead_id]["uids"] = list(uids)
        inventory[lead_id]["messages"] = [messages_by_uid[uid] for uid in uids]
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

    require_uidplus(client, "bounded draft replacement")

    raw = expected_msg.as_bytes(policy=default)
    status, append_data = client.append(
        folder,
        "(\\Draft)",
        imaplib.Time2Internaldate(__import__("time").time()),
        raw,
    )
    if status != "OK":
        raise RuntimeError(f"IMAP APPEND failed for {lead_id}")

    new_uid = _append_uid_from_response(client, append_data)
    old_removed = False
    try:
        select_folder(client, folder, readonly=True)
        if new_uid is None:
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
        old_removed = True

        select_folder(client, folder, readonly=True)
        final_uids = search_lead_uids(client, folder, lead_id, ensure_selected=False)
        if final_uids != [new_uid]:
            raise RuntimeError(f"Expected one final draft UID after replacement for {lead_id}")
        final_actual = fetch_message_uid(client, new_uid)
        if not exact_message_matches(final_actual, expected_msg):
            raise RuntimeError(f"Final UID replacement readback mismatch for {lead_id}")
        return "replaced", new_uid, final_actual
    except Exception as exc:
        if new_uid is not None and not old_removed:
            try:
                uid_expunge_only(
                    client,
                    folder,
                    new_uid,
                    operation=f"rollback appended replacement for {lead_id}",
                )
            except Exception as rollback_exc:
                raise RuntimeError(
                    f"{exc}; rollback of newly appended draft failed: {rollback_exc}"
                ) from exc
        raise


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
