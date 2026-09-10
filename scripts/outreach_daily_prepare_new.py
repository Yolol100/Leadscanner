#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from typing import Mapping

from outreach_agent_prepare import (
    CONTACT_HEADERS,
    CONTACT_SHEET,
    FULL_QUEUE_HEADERS,
    LEAD_HEADERS,
    LEAD_SHEET,
    PROSPECT_HEADERS,
    PROSPECT_SHEET,
)
from outreach_agent_prepare_v2 import build_prepared_row
from outreach_sender import QUEUE_SHEET, build_sheets_service, ensure_expected_headers, get_values, rows_from_values
from prospect_agent_qualification import AGENT_CATALOG, AGENT_QUALIFICATION_HEADERS, AGENT_QUALIFICATION_SHEET
from prospect_intelligence import canonical_domain
from prospect_target_policy import canonical_country

ALLOWED_EXISTING_LEAD_STATUSES = {"", "gevonden", "found", "prepared"}
NET_NEW_AGENTS = {"front_desk_sales", "quote_intake", "review_concierge", "customer_support", "commerce"}


def text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def load(service, spreadsheet_id: str, sheet: str, headers: list[str]):
    found_headers, rows = rows_from_values(get_values(service, spreadsheet_id, sheet))
    ensure_expected_headers(found_headers, headers, sheet)
    return [{str(k): str(v or "") for k, v in row.items()} for row in rows]


def index(rows, key: str):
    return {text(row.get(key)): row for row in rows if text(row.get(key))}


def lead_statuses_by_domain(rows) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for row in rows:
        domain = canonical_domain(row.get("Website") or row.get("website"))
        if domain:
            result.setdefault(domain, set()).add(text(row.get("Status") or row.get("status")).casefold())
    return result


def append_row(service, spreadsheet_id: str, sheet: str, headers: list[str], row: Mapping[str, object]) -> None:
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet}'!A:ZZ",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [[str(row.get(header, "")) for header in headers]]},
    ).execute()


def eligible(candidate, qualification, contact, *, agent_type: str, country: str, queued_ids: set[str], lead_statuses: dict[str, set[str]]) -> bool:
    candidate_id = text(candidate.get("candidate_id"))
    domain = canonical_domain(candidate.get("website"))
    if not candidate_id or candidate_id in queued_ids or not domain:
        return False
    statuses = lead_statuses.get(domain, set())
    if statuses and not statuses.issubset(ALLOWED_EXISTING_LEAD_STATUSES):
        return False
    if text(candidate.get("status")).casefold() != "qualified":
        return False
    if canonical_country(text(candidate.get("country"))) != country:
        return False
    if text(qualification.get("candidate_id")) != candidate_id:
        return False
    if text(qualification.get("status")).casefold() != "qualified" or text(qualification.get("tier")).upper() != "A":
        return False
    if text(qualification.get("offer_family")).casefold() != "ai_agent":
        return False
    if text(qualification.get("agent_type")).casefold() != agent_type:
        return False
    try:
        potential = int(text(qualification.get("customer_potential")) or "0")
    except ValueError:
        return False
    if potential < 8:
        return False
    if text(contact.get("candidate_id")) != candidate_id or text(contact.get("status")).casefold() != "ready":
        return False
    if text(contact.get("domain_alignment")).casefold() != "aligned" or text(contact.get("mx_status")).casefold() != "present":
        return False
    return True


def run() -> int:
    spreadsheet_id = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id or not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("OUTREACH_SPREADSHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON are required")
    agent_type = os.getenv("AGENT_SALES_TARGET_TYPE", "").strip().casefold()
    if agent_type not in NET_NEW_AGENTS or agent_type not in AGENT_CATALOG:
        raise ValueError("AGENT_SALES_TARGET_TYPE must be one explicit net-new approved agent")
    country = canonical_country(os.getenv("DAILY_DRAFT_COUNTRY", ""))
    if not country:
        raise ValueError("DAILY_DRAFT_COUNTRY is required")
    try:
        limit = int(os.getenv("OUTREACH_PREPARE_MAX_PER_RUN", "25") or "25")
    except ValueError as exc:
        raise ValueError("OUTREACH_PREPARE_MAX_PER_RUN must be an integer") from exc
    limit = max(1, min(limit, 25))

    service = build_sheets_service()
    candidates = load(service, spreadsheet_id, PROSPECT_SHEET, PROSPECT_HEADERS)
    qualifications = load(service, spreadsheet_id, AGENT_QUALIFICATION_SHEET, AGENT_QUALIFICATION_HEADERS)
    contacts = load(service, spreadsheet_id, CONTACT_SHEET, CONTACT_HEADERS)
    queue = load(service, spreadsheet_id, QUEUE_SHEET, FULL_QUEUE_HEADERS)
    leads = load(service, spreadsheet_id, LEAD_SHEET, LEAD_HEADERS)

    q_by_id = index(qualifications, "candidate_id")
    contact_by_id = index(contacts, "candidate_id")
    queued_ids = {text(row.get("lead_id")) for row in queue if text(row.get("lead_id"))}
    status_map = lead_statuses_by_domain(leads)
    known_lead_domains = set(status_map)

    postal_address = os.getenv("OUTREACH_POSTAL_ADDRESS", "")
    sender_mailbox_id = os.getenv("OUTREACH_MAILBOX_ID", "primary")
    sender_email = os.getenv("OUTREACH_SENDER_EMAIL", "info@andrewbaeten.nl")
    prepared = skipped = 0

    for candidate in candidates:
        if prepared >= limit:
            break
        candidate_id = text(candidate.get("candidate_id"))
        qualification = q_by_id.get(candidate_id, {})
        contact = contact_by_id.get(candidate_id, {})
        if not eligible(
            candidate,
            qualification,
            contact,
            agent_type=agent_type,
            country=country,
            queued_ids=queued_ids,
            lead_statuses=status_map,
        ):
            continue
        try:
            row = build_prepared_row(
                candidate,
                qualification,
                contact,
                postal_address=postal_address,
                sender_mailbox_id=sender_mailbox_id,
                sender_email=sender_email,
            )
        except ValueError:
            skipped += 1
            continue
        append_row(service, spreadsheet_id, QUEUE_SHEET, FULL_QUEUE_HEADERS, row)
        queued_ids.add(candidate_id)
        domain = canonical_domain(row.get("website"))
        if domain and domain not in known_lead_domains:
            append_row(service, spreadsheet_id, LEAD_SHEET, LEAD_HEADERS, {
                "Bedrijf": row.get("company", ""),
                "Website": row.get("website", ""),
                "E-mail": row.get("email", ""),
                "Status": "gevonden",
            })
            known_lead_domains.add(domain)
            status_map[domain] = {"gevonden"}
        prepared += 1

    print(
        f"DAILY_PREPARE_NEW=green prepared={prepared} skipped_copy_or_evidence={skipped} "
        f"agent={agent_type} country={country} send_permission=none"
    )
    return 0


def main() -> int:
    try:
        return run()
    except (RuntimeError, ValueError) as exc:
        print(f"DAILY_PREPARE_NEW=blocked detail={exc} send_permission=none", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
