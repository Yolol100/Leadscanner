"""Narrow sender-name correction inside the non-sending mijn.host source list.

No permission/evidence assertion, new lead, campaign staging, account assignment,
campaign activation, sending or source IMAP mutation. A future owner review is
still required before commercial use. Never publish contact/mail content.
"""
from __future__ import annotations

import re
import time

from instantly_campaign_copy import TARGET_CAMPAIGNS
from instantly_language_campaigns import read_imported_leads
from instantly_mail_quality import SIGNATURE_FIRST, classify_signature_tail
from myhost_instantly_import import TARGET_LIST_ID

UUID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
TAIL_NAME = re.compile(r"(?i)andrew[ \t]*[.!]?[ \t]*\Z")
MAX_UPDATES = 100
EXPECTED_ORIGIN = "myhost_drafts"


def _text(value: object) -> str:
    return str(value or "").strip()


def _custom(row: dict) -> dict:
    values = row.get("payload")
    if not isinstance(values, dict):
        values = row.get("custom_variables")
    if not isinstance(values, dict) or any(
        not isinstance(key, str)
        or not isinstance(value, (str, int, float, bool, type(None)))
        for key, value in values.items()
    ):
        raise RuntimeError("source_signature_custom_variables_invalid")
    return values


def _campaigns_still_quiet(client) -> None:
    for _, (cid, name) in TARGET_CAMPAIGNS.items():
        campaign = client.get_campaign(cid)
        if (
            not isinstance(campaign, dict)
            or campaign.get("id") != cid
            or campaign.get("name") != name
            or type(campaign.get("status")) is not int
            or campaign["status"] != 2
            or campaign.get("email_list") != []
        ):
            raise RuntimeError("signature_repair_requires_paused_campaigns_without_senders")
        page = client.list_leads(campaign=cid, limit=100)
        if (
            not isinstance(page, dict)
            or page.get("items") != []
            or page.get("next_starting_after")
        ):
            raise RuntimeError("signature_repair_requires_empty_target_campaigns")


def _verified_row(row: dict, *, source_list_id: str) -> tuple[str, dict]:
    if not isinstance(row, dict) or row.get("list_id") != source_list_id:
        raise RuntimeError("signature_repair_source_list_mismatch")
    if row.get("campaign") is not None:
        raise RuntimeError("signature_repair_source_already_assigned")
    lead_id = _text(row.get("id"))
    if not UUID.fullmatch(lead_id) or _text(row.get("email")).count("@") != 1:
        raise RuntimeError("signature_repair_lead_identity_invalid")
    return lead_id, _custom(row)


def _safe_replacement(variables: dict) -> str | None:
    subject = variables.get("leadscanner_subject")
    body = variables.get("leadscanner_body")
    if (
        variables.get("leadscanner_import_origin") != EXPECTED_ORIGIN
        or variables.get("leadscanner_contact_basis") != "review_required"
        or not isinstance(subject, str) or not subject.strip()
        or not isinstance(body, str) or not body.strip()
    ):
        return None
    if any(x in (subject + "\n" + body).casefold() for x in ("webactueel", "{{", "{%", "andrew baeten")):
        return None
    if classify_signature_tail(body) != "first_name_only_tail" or not SIGNATURE_FIRST.search(body.strip()):
        return None
    trimmed = body.rstrip(" \t\r\n")
    trailing = body[len(trimmed):]
    output, count = TAIL_NAME.subn("Andrew Baeten", trimmed)
    if count != 1 or not output.endswith("Andrew Baeten"):
        raise RuntimeError("signature_repair_normalization_not_exact")
    # Only the trailing sender name is different. No marketing claims, CTAs,
    # recipient identity, first-party observations, or legal bases are changed.
    marker = TAIL_NAME.search(trimmed)
    if marker is None or output[:marker.start()] != trimmed[:marker.start()]:
        raise RuntimeError("signature_repair_unexpected_body_change")
    output += trailing
    if output == body:
        raise RuntimeError("signature_repair_normalization_not_exact")
    return output


def normalize_source_first_mail_signatures(
    client, *, list_id: str, expected_count: int, max_updates: int,
    sleep_fn=time.sleep,
) -> dict:
    if list_id != TARGET_LIST_ID:
        raise ValueError("signature_repair_exact_source_list_required")
    if type(expected_count) is not int or not 1 <= expected_count <= 5000:
        raise ValueError("signature_repair_expected_count_invalid")
    if type(max_updates) is not int or not 1 <= max_updates <= MAX_UPDATES:
        raise ValueError("signature_repair_max_updates_invalid")

    _campaigns_still_quiet(client)
    observed_list_id, rows = read_imported_leads(client)
    if observed_list_id != list_id or len(rows) != expected_count:
        raise RuntimeError("signature_repair_source_count_or_identity_changed")

    seen = set()
    candidates = []
    remaining_before = 0
    for row in rows:
        lead_id, values = _verified_row(row, source_list_id=list_id)
        if lead_id in seen:
            raise RuntimeError("signature_repair_duplicate_lead_id")
        seen.add(lead_id)
        new_body = _safe_replacement(values)
        if new_body is not None:
            remaining_before += 1
            candidates.append((row, values, new_body))
    candidates.sort(key=lambda item: item[0]["id"])
    targets = candidates[:max_updates]
    updated = 0

    for row, values, new_body in targets:
        lead_id = row["id"]
        # An independent GET before every mutation rejects a changed recipient,
        # sender, status or payload. Unknown PATCH outcomes are NEVER retried.
        before = client.get_lead(lead_id)
        if not isinstance(before, dict):
            raise RuntimeError("signature_repair_lead_readback_invalid")
        observed_id, before_values = _verified_row(before, source_list_id=list_id)
        if observed_id != lead_id or _text(before.get("email")).casefold() != _text(row.get("email")).casefold():
            raise RuntimeError("signature_repair_recipient_changed")
        if before_values != values or _safe_replacement(before_values) != new_body:
            raise RuntimeError("signature_repair_copy_changed_before_patch")

        new_variables = dict(before_values)
        new_variables["leadscanner_body"] = new_body
        client._request(
            "PATCH", "/leads/" + lead_id, json={"custom_variables": new_variables}
        )
        # Instantly can expose an older lead snapshot immediately after a
        # successful PATCH. Only repeat safe GET requests, never the PATCH.
        matched = False
        for attempt in range(8):
            after = client.get_lead(lead_id)
            if not isinstance(after, dict):
                raise RuntimeError("signature_repair_postwrite_readback_invalid")
            observed_after_id, after_values = _verified_row(after, source_list_id=list_id)
            if (
                observed_after_id != lead_id
                or _text(after.get("email")).casefold() != _text(row.get("email")).casefold()
            ):
                raise RuntimeError("signature_repair_postwrite_recipient_changed")
            for key in ("status", "lt_interest_status", "verification_status", "timestamp_last_contact"):
                if key in before and after.get(key) != before[key]:
                    raise RuntimeError("signature_repair_unexpected_lead_status_change")
            if (
                after_values == new_variables
                and _safe_replacement(after_values) is None
                and classify_signature_tail(new_body) == "full_name_tail"
            ):
                matched = True
                break
            if attempt < 7:
                sleep_fn((0.4, 0.6, 1, 1.5, 2, 3, 4)[attempt])
        if not matched:
            raise RuntimeError("signature_repair_postwrite_mismatch_after_get_retries")
        updated += 1

    _campaigns_still_quiet(client)
    final_matches = False
    remaining_after = -1
    for attempt in range(8):
        # Bounded GET-only source-list reconciliation; provider pages may also
        # lag a committed PATCH. Never treat a stale page as a new write target.
        after_list_id, after_rows = read_imported_leads(client)
        if after_list_id != list_id or len(after_rows) != expected_count:
            raise RuntimeError("signature_repair_final_list_identity_or_count_changed")
        after_ids = {_text(row.get("id")) for row in after_rows}
        if after_ids != seen or len(after_ids) != expected_count:
            raise RuntimeError("signature_repair_original_leads_changed")
        remaining_after = 0
        for row in after_rows:
            _, values = _verified_row(row, source_list_id=list_id)
            if _safe_replacement(values) is not None:
                remaining_after += 1
        if remaining_after == remaining_before - updated:
            final_matches = True
            break
        if attempt < 7:
            sleep_fn((0.4, 0.6, 1, 1.5, 2, 3, 4)[attempt])
    if not final_matches:
        raise RuntimeError("signature_repair_final_copy_count_changed_after_get_retries")

    return {
        "schema_version": "leadscanner-source-signature-repair/1.0",
        "source_list_id": list_id,
        "source_count": expected_count,
        "eligible_before": remaining_before,
        "updated_count": updated,
        "remaining_after": remaining_after,
        "all_lead_ids_unchanged": True,
        "campaign_leads": 0,
        "campaign_senders": 0,
        "campaign_status": "paused",
        "contact_bases_unchanged": True,
        "website_proofs_unchanged": True,
        "email_body_changes_only_in_tail_signature": True,
        "campaigns_activated": False,
        "emails_sent": False,
        "contains_email_addresses_or_copy": False,
    }
