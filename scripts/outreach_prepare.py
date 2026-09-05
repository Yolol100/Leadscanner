#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Mapping, Sequence

from outreach_copy_preflight import followup_copy_errors, initial_copy_errors
from outreach_sender import QUEUE_HEADERS, QUEUE_SHEET, build_sheets_service, ensure_expected_headers, get_values, rows_from_values
from prospect_intelligence import canonical_domain
from prospect_target_policy import canonical_country
from prospect_qualification import QUALIFICATION_HEADERS, QUALIFICATION_SHEET

PROSPECT_SHEET = "ProspectCandidates"
CONTACT_SHEET = "ContactCandidates"
LEAD_SHEET = "Leadlijst"
PROSPECT_HEADERS = [
    "candidate_id", "discovered_at", "company", "website", "source_url",
    "source_id", "source_type", "country", "matched_terms", "status", "reason",
]
CONTACT_HEADERS = [
    "candidate_id", "checked_at", "company", "website", "email", "source_url",
    "email_domain", "domain_alignment", "mx_status", "status", "reason",
]
LEAD_HEADERS = ["Bedrijf", "Website", "E-mail", "Status"]
FULL_QUEUE_HEADERS = QUEUE_HEADERS + ["compliance_basis"]
UK_CORPORATE_SUFFIX_RE = re.compile(r"(?i)\b(?:ltd\.?|limited|llp|plc)\b")


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _language(country: str) -> str:
    return "nl" if canonical_country(country) in {"NL", "BE"} else "en"


def _mail_name(company: str) -> str:
    return _text(company)[:100]


def build_copy(
    *,
    company: str,
    country: str,
    fact: str,
    idea: str,
    analysis_type: str,
    postal_address: str = "",
) -> tuple[str, str, str, str, int]:
    company = _mail_name(company)
    fact = _text(fact)
    idea = _text(idea)
    analysis_type = _text(analysis_type).casefold()
    if not company or not fact or not idea or analysis_type not in {"website", "webshop"}:
        raise ValueError("company, evidence-bound fact/idea and analysis_type are required")
    language = _language(country)
    price = 750 if analysis_type == "webshop" else 500
    if language == "nl":
        subject = f"Idee voor {company}"
        product = "webshop" if analysis_type == "webshop" else "website"
        body = (
            f"Beste team van {company},\n\n"
            f"{fact}\n\n"
            f"Eén idee: {idea}\n\n"
            f"Als je dit breder wilt doorvoeren, kan ik voor {company} een complete, mobielvriendelijke {product} maken voor €{price}.\n\n"
            "Een paar voorbeelden:\n"
            "https://andrewbaeten.nl/category/cases\n\n"
            "Zal ik nog één concreet idee sturen?\n\n"
            "Geen interesse? Een kort \"nee\" is genoeg.\n\n"
            "Met vriendelijke groet,\n"
            "Andrew Baeten"
        )
        followup = (
            f"Beste team van {company},\n\n"
            f"Ik kom hier nog één keer op terug. Als het nuttig is, stuur ik het concrete idee voor {company} graag door.\n\n"
            "Geen interesse? Een kort \"nee\" is genoeg.\n\n"
            "Met vriendelijke groet,\n"
            "Andrew Baeten"
        )
    else:
        subject = f"Idea for {company}"
        product = "online store" if analysis_type == "webshop" else "website"
        legal_lines = ""
        if canonical_country(country) == "US":
            if not _text(postal_address):
                raise ValueError("OUTREACH_POSTAL_ADDRESS is required to prepare US commercial copy")
            legal_lines = f"\n\nThis is a commercial message.\n{_text(postal_address)}"
        body = (
            f"Hi {company} team,\n\n"
            f"{fact}\n\n"
            f"One idea: {idea}\n\n"
            f"If you'd like to take this further, I can build a complete, mobile-friendly {product} for {company} for €{price}.\n\n"
            "A few examples:\n"
            "https://andrewbaeten.nl/category/cases\n\n"
            "Would you like me to send one more concrete idea?"
            f"{legal_lines}\n\n"
            "Not interested? A quick \"no\" is enough.\n\n"
            "Best regards,\n"
            "Andrew Baeten"
        )
        followup = (
            f"Hi {company} team,\n\n"
            f"Just following up once. If useful, I'm happy to send the concrete idea for {company}.\n\n"
            "Not interested? A quick \"no\" is enough.\n\n"
            "Best regards,\n"
            "Andrew Baeten"
        )

    initial_errors = initial_copy_errors(subject, body)
    followup_errors = followup_copy_errors(followup)
    if initial_errors or followup_errors:
        raise ValueError("generated copy violates LeadPromo: " + "; ".join((initial_errors + followup_errors)[:5]))
    return subject, body, "", followup, 4


def build_prepared_row(
    candidate: Mapping[str, object],
    qualification: Mapping[str, object],
    contact: Mapping[str, object],
    *,
    postal_address: str = "",
    sender_mailbox_id: str = "primary",
    sender_email: str = "info@andrewbaeten.nl",
) -> dict[str, str]:
    candidate_id = _text(candidate.get("candidate_id"))
    company = _text(candidate.get("company"))
    website = _text(candidate.get("website"))
    country = canonical_country(_text(candidate.get("country")))
    if _text(candidate.get("status")).casefold() != "qualified":
        raise ValueError("candidate must be qualified")
    if _text(qualification.get("tier")).upper() != "A" or _text(qualification.get("status")).casefold() != "qualified":
        raise ValueError("qualification must be A/qualified")
    if _text(contact.get("status")).casefold() != "ready":
        raise ValueError("contact must be ready")
    email = _text(contact.get("email")).casefold()
    if not candidate_id or not company or not website or not email or "@" not in email:
        raise ValueError("prepared row requires candidate identity, official website and ready email")

    fact = _text(qualification.get("fact"))
    idea = _text(qualification.get("idea"))
    evidence_url = _text(qualification.get("evidence_url")) or website
    analysis_type = _text(qualification.get("analysis_type")).casefold()
    subject, body, followup_subject, followup_body, delay = build_copy(
        company=company,
        country=country,
        fact=fact,
        idea=idea,
        analysis_type=analysis_type,
        postal_address=postal_address,
    )
    evidence = {
        "evidence_url": evidence_url,
        "fact": fact,
        "idea": idea,
        "analysis_type": analysis_type,
        "qualification_tier": "A",
        "customer_potential": _text(qualification.get("customer_potential")),
    }
    if country == "GB" and UK_CORPORATE_SUFFIX_RE.search(company):
        evidence["subscriber_type"] = "corporate"

    row = {header: "" for header in FULL_QUEUE_HEADERS}
    row.update({
        "lead_id": candidate_id,
        "company": company,
        "website": website,
        "email": email,
        "first_name": "",
        "subject": subject,
        "body": body,
        "followup_subject": followup_subject,
        "followup_body": followup_body,
        "followup_delay_days": str(delay),
        "country": country,
        "compliance_status": "manual_review",
        "opt_out_mode": "reply_optout",
        "status": "prepared",
        "verification_status": "official_site_ready",
        "verification_checked_at": _text(contact.get("checked_at")),
        "stage": "1",
        "source": "website_scan:" + json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
        "sender_mailbox_id": _text(sender_mailbox_id) or "primary",
        "sender_email": _text(sender_email),
        "compliance_basis": "",
    })
    return row


def _append_row(service, spreadsheet_id: str, sheet: str, headers: Sequence[str], row: Mapping[str, object]) -> None:
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet}'!A:ZZ",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [[str(row.get(header, "")) for header in headers]]},
    ).execute()


def _write_report(path: str, payload: Mapping[str, object]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def run(mode: str, report_path: str) -> int:
    mode = (mode or "validate").strip().casefold()
    if mode not in {"validate", "prepare"}:
        raise ValueError("mode must be validate or prepare")
    spreadsheet_id = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        raise ValueError("OUTREACH_SPREADSHEET_ID is required")
    if not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is required")

    service = build_sheets_service()
    candidate_headers, candidates = rows_from_values(get_values(service, spreadsheet_id, PROSPECT_SHEET))
    ensure_expected_headers(candidate_headers, PROSPECT_HEADERS, PROSPECT_SHEET)
    qualification_headers, qualifications = rows_from_values(get_values(service, spreadsheet_id, QUALIFICATION_SHEET))
    ensure_expected_headers(qualification_headers, QUALIFICATION_HEADERS, QUALIFICATION_SHEET)
    contact_headers, contacts = rows_from_values(get_values(service, spreadsheet_id, CONTACT_SHEET))
    ensure_expected_headers(contact_headers, CONTACT_HEADERS, CONTACT_SHEET)
    queue_headers, queue = rows_from_values(get_values(service, spreadsheet_id, QUEUE_SHEET))
    ensure_expected_headers(queue_headers, FULL_QUEUE_HEADERS, QUEUE_SHEET)
    lead_headers, leads = rows_from_values(get_values(service, spreadsheet_id, LEAD_SHEET))
    ensure_expected_headers(lead_headers, LEAD_HEADERS, LEAD_SHEET)

    if mode == "validate":
        _write_report(report_path, {"mode": mode, "status": "ready", "send_permission": "none"})
        print("OUTREACH_PREPARE=validated send_permission=none")
        return 0

    qualification_by_id = {_text(row.get("candidate_id")): row for row in qualifications if _text(row.get("candidate_id"))}
    contact_by_id = {_text(row.get("candidate_id")): row for row in contacts if _text(row.get("candidate_id"))}
    queued_ids = {_text(row.get("lead_id")) for row in queue if _text(row.get("lead_id"))}
    lead_domains = {canonical_domain(row.get("Website") or row.get("website")) for row in leads}
    lead_domains.discard("")
    postal_address = os.getenv("OUTREACH_POSTAL_ADDRESS", "")
    sender_mailbox_id = os.getenv("OUTREACH_MAILBOX_ID", "primary")
    sender_email = os.getenv("OUTREACH_SENDER_EMAIL", "info@andrewbaeten.nl")
    hard_max = max(1, min(int(os.getenv("OUTREACH_PREPARE_MAX_PER_RUN", "10") or "10"), 25))

    prepared = skipped = 0
    for candidate in candidates:
        if prepared >= hard_max:
            break
        candidate_id = _text(candidate.get("candidate_id"))
        if not candidate_id or candidate_id in queued_ids:
            continue
        qualification = qualification_by_id.get(candidate_id)
        contact = contact_by_id.get(candidate_id)
        if not qualification or not contact:
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
        _append_row(service, spreadsheet_id, QUEUE_SHEET, FULL_QUEUE_HEADERS, row)
        prepared += 1
        queued_ids.add(candidate_id)
        domain = canonical_domain(row["website"])
        if domain and domain not in lead_domains:
            _append_row(service, spreadsheet_id, LEAD_SHEET, LEAD_HEADERS, {
                "Bedrijf": row["company"], "Website": row["website"], "E-mail": row["email"], "Status": "gevonden",
            })
            lead_domains.add(domain)

    _write_report(report_path, {
        "mode": mode,
        "status": "completed",
        "prepared": prepared,
        "skipped": skipped,
        "send_permission": "none",
        "compliance_status": "manual_review",
        "note": "Prepared rows are evidence-bound drafts only. This capability never approves compliance or sends mail.",
    })
    print(f"OUTREACH_PREPARE=complete prepared={prepared} skipped={skipped} send_permission=none")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare evidence-bound LeadPromo outreach without granting send permission.")
    parser.add_argument("--mode", default=os.getenv("OUTREACH_PREPARE_MODE", "validate"), choices=["validate", "prepare"])
    parser.add_argument("--report", default="outreach-prepare-report.json")
    args = parser.parse_args(argv)
    try:
        return run(args.mode, args.report)
    except (RuntimeError, ValueError) as exc:
        _write_report(args.report, {"mode": args.mode, "status": "blocked", "error": str(exc), "send_permission": "none"})
        print(f"OUTREACH_PREPARE=blocked detail={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
