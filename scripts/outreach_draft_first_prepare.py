#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from typing import Mapping

from outreach_agent_prepare import CONTACT_HEADERS, CONTACT_SHEET, FULL_QUEUE_HEADERS, LEAD_HEADERS, LEAD_SHEET, PROSPECT_HEADERS, PROSPECT_SHEET
from outreach_agent_prepare_v2 import _copy_with_value, _cta_variant
from outreach_sender import QUEUE_SHEET, build_sheets_service, ensure_expected_headers, get_values, rows_from_values
import outreach_daily_batch_drafts as draft_base
from outreach_site_personalization import personalize_from_evidence
from prospect_agent_qualification import AGENT_CATALOG, AGENT_QUALIFICATION_HEADERS, AGENT_QUALIFICATION_SHEET
from prospect_discovery import host_key, hosts_related
from prospect_intelligence import canonical_domain
from prospect_target_policy import canonical_country

AUTOMATION_ID = "agent_sales_draft_first_v14"
COPY_CONTRACT = "draft_first_v14"
NET_NEW_AGENTS = {"front_desk_sales", "quote_intake", "review_concierge", "customer_support", "commerce"}
BLOCKED_ROLE_TOKENS = {
    "noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "postmaster", "abuse",
    "privacy", "legal", "billing", "payroll", "hr", "humanresources", "human-resources",
    "career", "careers", "job", "jobs", "recruiting", "recruitment", "press", "media",
}


def text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def email(value: object) -> str:
    return text(value).casefold()


def load(service, spreadsheet_id: str, sheet: str, headers: list[str]):
    found_headers, rows = rows_from_values(get_values(service, spreadsheet_id, sheet))
    ensure_expected_headers(found_headers, headers, sheet)
    return [{str(k): str(v or "") for k, v in row.items()} for row in rows]


def index(rows, key: str):
    return {text(row.get(key)): row for row in rows if text(row.get(key))}


def role_safe(address: str) -> bool:
    address = email(address)
    if "@" not in address:
        return False
    local = address.rsplit("@", 1)[0]
    compact = re.sub(r"[^a-z0-9]+", "", local)
    blocked = {re.sub(r"[^a-z0-9]+", "", item) for item in BLOCKED_ROLE_TOKENS}
    return local not in BLOCKED_ROLE_TOKENS and compact not in blocked


def official_contact_source(website: str, source_url: str) -> bool:
    wh = host_key(website)
    sh = host_key(source_url)
    return bool(wh and sh and hosts_related(wh, sh))


def qualification_ok(q: Mapping[str, object]) -> bool:
    try:
        score = int(text(q.get("customer_potential")) or "0")
    except ValueError:
        return False
    return (
        text(q.get("offer_family")).casefold() == "ai_agent"
        and text(q.get("agent_type")).casefold() in NET_NEW_AGENTS
        and text(q.get("tier")).upper() in {"A", "B"}
        and text(q.get("status")).casefold() in {"qualified", "hold"}
        and score >= 6
    )


def candidate_ok(candidate: Mapping[str, object], q: Mapping[str, object], contact: Mapping[str, object], *, country: str) -> bool:
    if not candidate or not q or not contact:
        return False
    if text(candidate.get("status")).casefold() not in {"qualified", "hold"}:
        return False
    if canonical_country(text(candidate.get("country"))) != country:
        return False
    if not qualification_ok(q):
        return False
    address = email(contact.get("email"))
    if text(contact.get("status")).casefold() not in {"ready", "manual_review"}:
        return False
    if text(contact.get("mx_status")).casefold() == "missing":
        return False
    if not address or "@" not in address or not role_safe(address):
        return False
    if not official_contact_source(text(candidate.get("website")), text(contact.get("source_url"))):
        return False
    return True


def append_row(service, spreadsheet_id: str, sheet: str, headers: list[str], row: Mapping[str, object]) -> None:
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet}'!A:ZZ",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [[str(row.get(header, "")) for header in headers]]},
    ).execute()


def build_row(candidate, q, contact, *, postal_address: str, sender_mailbox_id: str, sender_email: str):
    company = text(candidate.get("company"))
    website = text(candidate.get("website"))
    country = canonical_country(text(candidate.get("country")))
    agent_type = text(q.get("agent_type")).casefold()
    evidence_url = text(q.get("evidence_url")) or website
    language = "nl" if country in {"NL", "BE"} else "en"
    personalization_mode = "specific_anchor"
    try:
        p = personalize_from_evidence(company=company, agent_type=agent_type, language=language, evidence_url=evidence_url)
        observation, value = p.observation, p.value
        anchor, process_label, final_evidence = p.anchor, p.process_label, p.evidence_url
    except ValueError:
        personalization_mode = "verified_process_fallback"
        observation = text(q.get("fact"))
        value = text(q.get("idea"))
        anchor = text(q.get("business_process")) or agent_type
        process_label = text(q.get("business_process"))
        final_evidence = evidence_url
    if not observation or not value:
        raise ValueError("missing evidence-grounded observation/value")
    subject, body, followup_subject, followup_body, delay = _copy_with_value(
        company=company, country=country, fact=observation, value=value,
        agent_type=agent_type, postal_address=postal_address,
    )
    try:
        score = int(text(q.get("customer_potential")) or "0")
    except ValueError:
        score = 0
    evidence = {
        "automation": AUTOMATION_ID, "copy_contract": COPY_CONTRACT, "offer_family": "ai_agent",
        "primary_agent_type": agent_type, "agent_type": agent_type,
        "business_process": text(q.get("business_process")), "kpi_candidate": text(q.get("kpi_candidate")),
        "integration_hint": text(q.get("integration_hint")), "evidence_url": final_evidence,
        "observation": observation, "value_asset_summary": value, "personalization_anchor": anchor,
        "personalization_process_label": process_label, "personalization_mode": personalization_mode,
        "qualification_tier": text(q.get("tier")).upper(), "customer_potential": score,
        "draft_fit": text(q.get("tier")).upper(), "contact_confidence": text(contact.get("status")).casefold(),
        "contact_domain_alignment": text(contact.get("domain_alignment")).casefold(),
        "contact_mx_status": text(contact.get("mx_status")).casefold(), "email_source_url": text(contact.get("source_url")),
        "cta_variant": _cta_variant(), "send_permission": "none",
    }
    row = {header: "" for header in FULL_QUEUE_HEADERS}
    row.update({
        "lead_id": text(candidate.get("candidate_id")), "company": company, "website": website,
        "email": email(contact.get("email")), "first_name": "", "subject": subject, "body": body,
        "followup_subject": followup_subject, "followup_body": followup_body,
        "followup_delay_days": str(delay), "country": country, "compliance_status": "manual_review",
        "opt_out_mode": "reply_optout", "status": "manual_review", "verification_status": "official_site_ready",
        "verification_checked_at": text(contact.get("checked_at")), "stage": "1",
        "source": "agent_offer:" + json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
        "sender_mailbox_id": text(sender_mailbox_id) or "primary", "sender_email": text(sender_email),
        "compliance_basis": "",
    })
    return row


def run() -> int:
    spreadsheet_id = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id or not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("OUTREACH_SPREADSHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON are required")
    country = canonical_country(os.getenv("DAILY_DRAFT_COUNTRY", ""))
    if not country:
        raise ValueError("DAILY_DRAFT_COUNTRY is required")
    limit = max(1, min(int(os.getenv("OUTREACH_PREPARE_MAX_PER_RUN", "25") or "25"), 50))

    service = build_sheets_service()
    candidates = load(service, spreadsheet_id, PROSPECT_SHEET, PROSPECT_HEADERS)
    qualifications = load(service, spreadsheet_id, AGENT_QUALIFICATION_SHEET, AGENT_QUALIFICATION_HEADERS)
    contacts = load(service, spreadsheet_id, CONTACT_SHEET, CONTACT_HEADERS)
    queue = load(service, spreadsheet_id, QUEUE_SHEET, FULL_QUEUE_HEADERS)
    leads = load(service, spreadsheet_id, LEAD_SHEET, LEAD_HEADERS)
    _, suppressions = rows_from_values(get_values(service, spreadsheet_id, draft_base.SUPPRESSION_SHEET))
    suppressed_emails, suppressed_domains = draft_base._suppression_sets(suppressions)

    q_by_id = index(qualifications, "candidate_id")
    c_by_id = index(contacts, "candidate_id")
    queued_ids = {text(row.get("lead_id")) for row in queue if text(row.get("lead_id"))}
    queued_domains = {canonical_domain(row.get("website")) for row in queue if canonical_domain(row.get("website"))}
    queued_emails = {email(row.get("email")) for row in queue if email(row.get("email"))}
    known_domains = {canonical_domain(row.get("Website") or row.get("website")) for row in leads}
    known_domains.discard("")

    postal_address = os.getenv("OUTREACH_POSTAL_ADDRESS", "")
    sender_mailbox_id = os.getenv("OUTREACH_MAILBOX_ID", "primary")
    sender_email = os.getenv("OUTREACH_SENDER_EMAIL", "info@andrewbaeten.nl")
    prepared = skipped = 0
    tier_counts = {"A": 0, "B": 0}

    for candidate in candidates:
        if prepared >= limit:
            break
        candidate_id = text(candidate.get("candidate_id"))
        if not candidate_id or candidate_id in queued_ids:
            continue
        q = q_by_id.get(candidate_id, {})
        contact = c_by_id.get(candidate_id, {})
        if not candidate_ok(candidate, q, contact, country=country):
            continue
        address = email(contact.get("email"))
        address_domain = address.rsplit("@", 1)[1] if "@" in address else ""
        domain_before = canonical_domain(candidate.get("website"))
        if address in suppressed_emails or address_domain in suppressed_domains:
            skipped += 1
            continue
        if domain_before in queued_domains or address in queued_emails:
            continue
        try:
            row = build_row(candidate, q, contact, postal_address=postal_address, sender_mailbox_id=sender_mailbox_id, sender_email=sender_email)
        except ValueError:
            skipped += 1
            continue
        domain = canonical_domain(row.get("website"))
        if domain and domain not in known_domains:
            append_row(service, spreadsheet_id, LEAD_SHEET, LEAD_HEADERS, {
                "Bedrijf": row.get("company", ""), "Website": row.get("website", ""),
                "E-mail": row.get("email", ""), "Status": "gevonden",
            })
            known_domains.add(domain)
        append_row(service, spreadsheet_id, QUEUE_SHEET, FULL_QUEUE_HEADERS, row)
        queued_ids.add(candidate_id)
        queued_domains.add(domain)
        queued_emails.add(email(row.get("email")))
        tier = text(q.get("tier")).upper()
        if tier in tier_counts:
            tier_counts[tier] += 1
        prepared += 1

    print(f"DRAFT_FIRST_PREPARE=green prepared={prepared} tier_a={tier_counts['A']} tier_b={tier_counts['B']} skipped={skipped} country={country} send_permission=none")
    return 0


def main() -> int:
    try:
        return run()
    except (RuntimeError, ValueError) as exc:
        print(f"DRAFT_FIRST_PREPARE=blocked detail={exc} send_permission=none", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
