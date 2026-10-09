#!/usr/bin/env python3
"""Import only Leadscanner-tagged mijn.host drafts into an isolated Instantly list.

No SMTP, campaign creation/activation, IMAP mutations, or raw lead data in reports.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from email.utils import getaddresses, parseaddr

from dedupe_preflight import match_candidate
from instantly_client import InstantlyClient
from instantly_service import DEFAULT_REGISTRY_URL, fetch_live_registry
from myhost_draft import (
    LEAD_ID_RE, connect_imap, fetch_message_uid, find_drafts_folder,
    normalize_text, plain_body, select_folder,
)

TARGET_LIST_NAME = "Webactueel - mijn.host concepten - NIET VERZENDEN"
MAX_SOURCE_DRAFTS = 20000
MAX_IMPORT_DRAFTS = 5000
MAX_BLOCKLIST_ROWS = 20000
PERMITTED_REGISTRY_STATUSES = {
    "", "concept", "draft", "draft_ready", "review_draft",
    "concept_preview", "gevonden", "found",
}
EMAIL_RE = re.compile(r"^[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+$")


def _text(value: object) -> str:
    return str(value or "").strip()


def extract_lead_draft(msg, *, sender: str) -> dict | None:
    """None means a non-Leadscanner draft; tagged but invalid drafts are rejected."""
    lead_id = _text(msg.get("X-Webactueel-Lead-ID", "")).casefold()
    if not lead_id:
        return None
    if not LEAD_ID_RE.fullmatch(lead_id):
        raise ValueError("invalid_source_lead_id")
    sender_addr = parseaddr(_text(msg.get("From", "")))[1].casefold()
    if sender_addr != sender.casefold():
        raise ValueError("source_sender_mismatch")
    recipients = [(name, address.strip().casefold()) for name, address in getaddresses([_text(msg.get("To", ""))]) if address.strip()]
    if len(recipients) != 1 or not EMAIL_RE.fullmatch(recipients[0][1]):
        raise ValueError("source_single_valid_recipient_required")
    if _text(msg.get("Cc", "")) or _text(msg.get("Bcc", "")):
        raise ValueError("source_cc_bcc_forbidden")
    if any(True for _ in msg.iter_attachments()):
        raise ValueError("source_attachments_not_supported")
    subject = normalize_text(msg.get("Subject", ""))
    body = plain_body(msg)
    if not subject or len(subject) > 250 or not body or len(body) > 14000:
        raise ValueError("source_copy_missing_or_oversized")
    if "\r" in subject or "\n" in subject:
        raise ValueError("source_subject_multiline_forbidden")
    return {
        "lead_id": lead_id,
        "email": recipients[0][1],
        "subject": subject,
        "body": body,
    }


def read_source_drafts(*, connector=connect_imap) -> dict:
    sender = os.getenv("OUTREACH_SENDER_EMAIL", "info@andrewbaeten.nl").strip().casefold()
    if not EMAIL_RE.fullmatch(sender):
        raise ValueError("source_sender_configuration_invalid")
    client = connector()
    try:
        folder = find_drafts_folder(client)
        select_folder(client, folder, readonly=True)
        # Search only tagged Leadscanner drafts; unrelated mailbox drafts stay unread.
        status, data = client.uid("search", None, "HEADER", "X-Webactueel-Lead-ID", "growth-")
        if status != "OK" or not isinstance(data, list):
            raise RuntimeError("imap_uid_search_failed")
        uids = (data[0] or b"").split() if data else []
        if len(uids) > MAX_SOURCE_DRAFTS:
            raise RuntimeError("source_draft_limit_exceeded")
        rows, untagged, invalid_tagged = [], 0, 0
        for uid in uids:
            msg = fetch_message_uid(client, uid)
            try:
                item = extract_lead_draft(msg, sender=sender)
            except (ValueError, UnicodeError, LookupError):
                invalid_tagged += 1
                continue
            if item is None:
                untagged += 1
            else:
                rows.append(item)
        return {
            "source_count": len(uids),
            "untagged_count": untagged,
            "invalid_tagged_count": invalid_tagged,
            "drafts": rows,
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


def unique_drafts(rows: list[dict]) -> tuple[list[dict], int]:
    ids = Counter(row["lead_id"] for row in rows)
    emails = Counter(row["email"] for row in rows)
    return [
        row for row in rows
        if ids[row["lead_id"]] == 1 and emails[row["email"]] == 1
    ], sum(ids[row["lead_id"]] > 1 or emails[row["email"]] > 1 for row in rows)


def registry_allows_draft(row: dict, registry_rows: list[dict]) -> bool:
    """Historical concept records are allowed; sent/replied/suppressed are not."""
    identity = {"email": row["email"], "lead_id": row["lead_id"]}
    matched = [record for record in registry_rows if match_candidate(identity, [record])]
    for record in matched:
        status = _text(record.get("status")).casefold().replace("-", "_").replace(" ", "_")
        if status not in PERMITTED_REGISTRY_STATUSES:
            return False
    return True


def _items_page(response: object) -> tuple[list[dict], str]:
    if not isinstance(response, dict) or not isinstance(response.get("items"), list):
        raise RuntimeError("provider_page_shape_invalid")
    items = response["items"]
    if any(not isinstance(row, dict) for row in items):
        raise RuntimeError("provider_page_item_invalid")
    return items, _text(response.get("next_starting_after"))


def _iter_pages(client: InstantlyClient, path: str, *, max_rows: int):
    cursor, seen, count = "", set(), 0
    while True:
        params = {"limit": 100}
        if cursor:
            params["starting_after"] = cursor
        items, next_cursor = _items_page(client._request("GET", path, params=params, retry_safe=True))
        count += len(items)
        if count > max_rows:
            raise RuntimeError("provider_pagination_limit_exceeded")
        yield from items
        if not items or not next_cursor:
            return
        if next_cursor == cursor or next_cursor in seen:
            raise RuntimeError("provider_pagination_loop")
        seen.add(next_cursor)
        cursor = next_cursor


def blocked_values(client: InstantlyClient) -> set[str]:
    values = set()
    for item in _iter_pages(client, "/block-lists-entries", max_rows=MAX_BLOCKLIST_ROWS):
        value = _text(item.get("bl_value") or item.get("value")).casefold()
        if not value:
            raise RuntimeError("blocklist_entry_missing_value")
        values.add(value.removeprefix("@"))
    return values


def workspace_contains(client: InstantlyClient, email: str) -> bool:
    cursor, seen = "", set()
    for _ in range(10):
        page = client.list_leads(contacts=[email], limit=100, starting_after=cursor or None)
        items, next_cursor = _items_page(page)
        if any(_text(item.get("email")).casefold() == email for item in items):
            return True
        if not items or not next_cursor:
            return False
        if next_cursor == cursor or next_cursor in seen:
            raise RuntimeError("workspace_leads_pagination_loop")
        seen.add(next_cursor)
        cursor = next_cursor
    raise RuntimeError("workspace_leads_pagination_limit_exceeded")


def matching_list_ids(client: InstantlyClient) -> list[str]:
    matches = []
    for row in _iter_pages(client, "/lead-lists", max_rows=10000):
        if _text(row.get("name")) == TARGET_LIST_NAME:
            list_id = _text(row.get("id"))
            if not list_id:
                raise RuntimeError("matching_list_missing_id")
            matches.append(list_id)
    if len(matches) > 1:
        raise RuntimeError("duplicate_target_lists_block_import")
    return matches


def ensure_isolated_list(client: InstantlyClient) -> str:
    found = matching_list_ids(client)
    if found:
        return found[0]
    response = client._request("POST", "/lead-lists", json={"name": TARGET_LIST_NAME})
    list_id = _text(response.get("id")) if isinstance(response, dict) else ""
    if not list_id:
        raise RuntimeError("created_list_missing_id_no_retry")
    check = client._request("GET", "/lead-lists/" + list_id, retry_safe=True)
    if not isinstance(check, dict) or _text(check.get("id")) != list_id or _text(check.get("name")) != TARGET_LIST_NAME:
        raise RuntimeError("created_list_readback_mismatch")
    return list_id


def lead_payload(row: dict, list_id: str) -> dict:
    return {
        "email": row["email"],
        "list_id": list_id,
        "skip_if_in_workspace": True,
        "custom_variables": {
            "leadscanner_source_lead_id": row["lead_id"],
            "leadscanner_import_origin": "myhost_drafts",
            "leadscanner_subject": row["subject"],
            "leadscanner_body": row["body"],
            "leadscanner_contact_basis": "review_required",
        },
    }


def verify_import(client: InstantlyClient, expected: dict, created: object) -> None:
    lead_id = _text(created.get("id")) if isinstance(created, dict) else ""
    if not lead_id:
        raise RuntimeError("lead_create_missing_id_no_retry")
    actual = client.get_lead(lead_id)
    if not isinstance(actual, dict):
        raise RuntimeError("lead_readback_invalid")
    if _text(actual.get("id")) != lead_id or _text(actual.get("email")).casefold() != expected["email"]:
        raise RuntimeError("lead_readback_identity_mismatch")
    if _text(actual.get("list_id")) != expected["list_id"] or actual.get("campaign") is not None:
        raise RuntimeError("lead_not_in_isolated_list")
    values = actual.get("payload") if isinstance(actual.get("payload"), dict) else actual.get("custom_variables")
    if not isinstance(values, dict) or any(values.get(key) != val for key, val in expected["custom_variables"].items()):
        raise RuntimeError("lead_custom_variables_readback_mismatch")


def _step(label: str, operation, *args, **kwargs):
    """Privacy-safe error stage; never include personal data or request payloads."""
    try:
        return operation(*args, **kwargs)
    except Exception as exc:
        raise RuntimeError(f"migration_step_{label}_{type(exc).__name__}") from exc


def workspace_candidate_emails(client: InstantlyClient, emails: list[str], *, chunk_size: int = 25) -> set[str]:
    """Proven contact-filtered paginated reads; never list entire workspace."""
    if type(chunk_size) is not int or not 1 <= chunk_size <= 50:
        raise ValueError("workspace_chunk_limit_invalid")
    candidates = sorted(set(emails))
    existing: set[str] = set()
    for offset in range(0, len(candidates), chunk_size):
        chunk = candidates[offset:offset + chunk_size]
        accepted = set(chunk)
        cursor, seen = "", set()
        for _ in range(100):
            page = client.list_leads(contacts=chunk, limit=100, starting_after=cursor or None)
            items, next_cursor = _items_page(page)
            for item in items:
                email = _text(item.get("email")).casefold()
                if not email or email not in accepted:
                    raise RuntimeError("provider_contacts_filter_mismatch")
                existing.add(email)
            if not next_cursor:
                break
            if not items or next_cursor == cursor or next_cursor in seen:
                raise RuntimeError("provider_contacts_pagination_invalid")
            seen.add(next_cursor)
            cursor = next_cursor
        else:
            raise RuntimeError("provider_contacts_pagination_limit_exceeded")
    return existing


def execute_migration(client: InstantlyClient, *, mode: str = "audit", registry_url: str = DEFAULT_REGISTRY_URL, max_imports: int = 25) -> dict:
    if mode not in {"audit", "import"}:
        raise ValueError("migration_mode_invalid")
    if type(max_imports) is not int or not 1 <= max_imports <= 250:
        raise ValueError("max_imports_out_of_bounds")
    source = _step("source", read_source_drafts)
    unique, duplicate_count = unique_drafts(source["drafts"])
    if len(unique) > MAX_IMPORT_DRAFTS:
        raise RuntimeError("eligible_source_draft_limit_exceeded")
    registry = _step("registry", fetch_live_registry, registry_url=registry_url)
    blocklist = _step("blocklist", blocked_values, client)
    # Query all candidate emails in bounded contact-filtered groups. The live
    # provider supports contact filters; unfiltered snapshot calls can return
    # endpoint errors on some workspaces. Recheck every lead before writing.
    workspace_emails = _step("workspace_candidate_lookup", workspace_candidate_emails, client, [r["email"] for r in unique])
    pending, suppressed, already_existing = [], 0, 0
    for row in unique:
        domain = row["email"].rsplit("@", 1)[-1]
        if (
            not registry_allows_draft(row, registry)
            or row["email"] in blocklist
            or domain in blocklist
        ):
            suppressed += 1
            continue
        if row["email"] in workspace_emails:
            already_existing += 1
            continue
        pending.append(row)

    report = {
        "schema_version": "leadscanner-myhost-instantly-import/1.0",
        "mode": mode,
        "source_count": source["source_count"],
        "tagged_count": len(source["drafts"]),
        "untagged_count": source["untagged_count"],
        "invalid_tagged_count": source["invalid_tagged_count"],
        "duplicate_count": duplicate_count,
        "suppressed_count": suppressed,
        "already_in_workspace_count": already_existing,
        "eligible_count": len(pending),
        "batch_limit": max_imports,
        "deferred_count": max(0, len(pending) - max_imports) if mode == "import" else len(pending),
        "imported_count": 0,
        "list_name": TARGET_LIST_NAME,
        "list_id": None,
        "automatic_send": False,
        "campaign_mutation": False,
        "imap_mutation": False,
        "registry_mutation": False,
    }
    if mode == "audit" or not pending:
        return report
    list_id = _step("target_list", ensure_isolated_list, client)
    report["list_id"] = list_id
    for row in pending[:max_imports]:
        # Recheck immediately before each write. Ambiguous errors stop; never retry POST.
        if _step(f"prewrite_dedupe_verified_{report['imported_count']}", workspace_contains, client, row["email"]):
            report["already_in_workspace_count"] += 1
            continue
        expected = lead_payload(row, list_id)
        created = _step(f"lead_write_verified_{report['imported_count']}", client._request, "POST", "/leads", json=expected)
        _step(f"lead_readback_verified_{report['imported_count']}", verify_import, client, expected, created)
        report["imported_count"] += 1
    return report
