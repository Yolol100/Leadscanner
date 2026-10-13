"""Reversible, UID-exact isolation of unverified existing mijn.host Drafts.

Messages are copied byte-for-byte to a private hold folder and verified before
only the original UID is expunged. Never send, globally EXPUNGE, log addresses,
or delete any message without a verified server-side backup.
"""
from __future__ import annotations

from email.policy import default
from email.utils import getaddresses

from dedupe_preflight import normalize_email
from myhost_draft import (
    exact_message_matches, fetch_message_uid, find_message_ids,
    require_draft_flag, require_uidplus, review_status_from_message,
    select_folder, uid_expunge_only, uid_for_message_id,
)

HOLD_FOLDER = "Leadscanner_Hold_20261013"


def _one_address(message, name):
    parsed = getaddresses(message.get_all(name, []))
    return normalize_email(parsed[0][1]) if len(parsed) == 1 else ""


def _raw_uid(client, uid):
    status, payload = client.uid("fetch", uid.decode("ascii"), "(BODY.PEEK[])")
    if status != "OK":
        raise RuntimeError("hold_raw_uid_fetch_failed")
    messages = [
        bytes(row[1]) for row in (payload or [])
        if isinstance(row, tuple) and len(row) > 1
        and isinstance(row[1], (bytes, bytearray))
    ]
    if len(messages) != 1 or not messages[0]:
        raise RuntimeError("hold_raw_uid_not_unique")
    return messages[0]


def _one_uid(client, folder, lead, *, require_draft=False):
    select_folder(client, folder, readonly=True)
    matches = find_message_ids(client, folder, lead, ensure_selected=False)
    if len(matches) > 1:
        raise RuntimeError("hold_duplicate_lead_id_in_folder")
    if not matches:
        return None
    uid = uid_for_message_id(client, matches[0])
    if require_draft:
        require_draft_flag(client, uid)
    return uid


def ensure_hold_folder(client, drafts_folder):
    if HOLD_FOLDER.casefold() == drafts_folder.casefold():
        raise RuntimeError("hold_cannot_be_drafts_folder")
    try:
        select_folder(client, HOLD_FOLDER, readonly=True)
    except RuntimeError:
        status, _ = client.create('"' + HOLD_FOLDER + '"')
        if status != "OK":
            raise RuntimeError("hold_folder_create_failed")
        select_folder(client, HOLD_FOLDER, readonly=True)
    return HOLD_FOLDER


def _assert_recoverable_duplicate(client, drafts, hold, lead):
    source_uid = _one_uid(client, drafts, lead, require_draft=True)
    saved_uid = _one_uid(client, hold, lead)
    if source_uid is None or saved_uid is None:
        raise RuntimeError("hold_overlap_missing_copy")
    select_folder(client, drafts, readonly=True)
    before = _raw_uid(client, source_uid)
    select_folder(client, hold, readonly=True)
    after = _raw_uid(client, saved_uid)
    if before != after:
        raise RuntimeError("hold_overlap_copy_mismatch")


def validate_hold_inventory(client, drafts, hold, inventory_existing, expected_total):
    active = inventory_existing(client, drafts, expected_total=None)
    saved = inventory_existing(client, hold, expected_total=None)
    active_ids = {x["lead_id"] for x in active}
    saved_ids = {x["lead_id"] for x in saved}
    if len(active_ids | saved_ids) != expected_total:
        raise RuntimeError("hold_union_baseline_changed")
    select_folder(client, hold, readonly=True)
    status, rows = client.search(None, "ALL")
    if status != "OK" or len((rows[0] if rows else b"").split()) != len(saved):
        raise RuntimeError("hold_folder_unrelated_content")
    for lead in active_ids & saved_ids:
        _assert_recoverable_duplicate(client, drafts, hold, lead)
    return active, saved


def move_to_hold(client, drafts, hold, lead, recipient, sender, expected):
    """Return False on an edited target; raise on missing/unsafe archive proof."""
    require_uidplus(client, "recoverable hold move")
    uid = _one_uid(client, drafts, lead, require_draft=True)
    if uid is None:
        return False
    select_folder(client, drafts, readonly=True)
    current = fetch_message_uid(client, uid)
    if (_one_address(current, "To") != recipient
            or _one_address(current, "From") != sender
            or not exact_message_matches(current, expected)
            or review_status_from_message(current) != review_status_from_message(expected)
            or current.as_bytes(policy=default) != expected.as_bytes(policy=default)):
        return False
    original_raw = _raw_uid(client, uid)

    saved_uid = _one_uid(client, hold, lead)
    if saved_uid is None:
        select_folder(client, drafts, readonly=False)
        # A fresh per-UID check immediately precedes COPY.
        if _raw_uid(client, uid) != original_raw:
            return False
        status, _ = client.uid("copy", uid.decode("ascii"), '"' + hold + '"')
        if status != "OK":
            raise RuntimeError("hold_uid_copy_failed")

    saved_uid = _one_uid(client, hold, lead)
    if saved_uid is None:
        raise RuntimeError("hold_backup_not_found")
    select_folder(client, hold, readonly=True)
    if _raw_uid(client, saved_uid) != original_raw:
        raise RuntimeError("hold_backup_exact_readback_failed")

    source_uid = _one_uid(client, drafts, lead, require_draft=True)
    if source_uid is None or source_uid != uid:
        return False
    select_folder(client, drafts, readonly=True)
    if _raw_uid(client, source_uid) != original_raw:
        return False
    uid_expunge_only(client, drafts, uid, operation="verified hold original only")
    if _one_uid(client, drafts, lead) is not None:
        raise RuntimeError("hold_original_still_present")
    saved_uid = _one_uid(client, hold, lead)
    if saved_uid is None:
        raise RuntimeError("hold_verified_backup_missing")
    select_folder(client, hold, readonly=True)
    if _raw_uid(client, saved_uid) != original_raw:
        raise RuntimeError("hold_verified_backup_changed")
    return True
