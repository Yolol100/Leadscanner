from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
OPS = ROOT / "ops"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(OPS))

import outreach_agent_prepare as prepare
import prospect_agent_qualification as qual
import prospect_contact_enrichment as contact
import targeted_us_quote_fill as targeted
from outreach_sender import append_row, build_sheets_service, ensure_expected_headers, get_values, rows_from_values
from prospect_discovery import host_key
from prospect_target_policy import canonical_country

SPREADSHEET_ID = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
TARGET_AGENT = "quote_intake"
TARGET_COUNTRY = "US"
BASELINE_LEAD_COUNT = 175
SOURCE_SHEET = "ProspectSources"
SOURCE_HEADERS = [
    "source_id", "source_type", "source_url", "country", "include_terms",
    "exclude_terms", "max_candidates", "approved", "enabled",
]

SPECS = [
    {
        "candidate_id": "manual-20260907-ntma-014",
        "email": "customerservice@mandamachine.com",
        "contact_url": "https://mandamachine.com/contact/",
        "anchor": "Quality Precision Machining Experts",
        "process": "Need a Quote",
    },
    {
        "candidate_id": "prospect-pma-2241f4a401e4468c18dc",
        "email": "wricotxsales@wrico-net.com",
        "contact_url": "https://www.wrico-net.com/wrico-locations/tx/",
        "anchor": "Laser Fabricated Parts",
        "process": "Request Quote",
    },
    {
        "candidate_id": "prospect-pma-2a9987be0fae2fe1604d",
        "email": "sales@pennunited.com",
        "contact_url": "https://www.pennunited.com/wp-content/uploads/2025/02/Plating.pdf",
        "anchor": "Fast and Accurate Quotations",
        "process": "Request a Quote",
    },
    {
        "candidate_id": "prospect-pma-65289f0bd2695d3b3209",
        "email": "compcosales@compco.com",
        "contact_url": "https://compco.com/wp-content/uploads/2025/03/Compco_Capabilities_Brochure_2024.pdf",
        "anchor": "Custom Fabrications",
        "process": "Request a Quote",
    },
    {
        "candidate_id": "prospect-pma-4ce1706ce7be43146805",
        "email": "sales@diecoinc.com",
        "contact_url": "https://diecoinc.com/contact-us",
        "anchor": "Spring Steel Fasteners",
        "process": "RFQs and Inquiries",
    },
    {
        "candidate_id": "prospect-pma-8524cfdf4cdb5f6f3479",
        "email": "info@ohfab.com",
        "contact_url": "https://ohfab.com/contact/",
        "anchor": "Custom Hydraulic Filters",
        "process": "Contact Us",
    },
    {
        "candidate_id": "prospect-pma-9ec23bf89355720292f7",
        "email": "sales@talanproducts.com",
        "contact_url": "https://www.talanproducts.com/resources-and-white-papers/re-shoring-with-talan-the-competitive-advantage-with-domestic-us-metal-stamping-company/",
        "anchor": "Custom Aluminum Extrusions",
        "process": "Request a Quote",
    },
    {
        "candidate_id": "prospect-pmpa-438e73b9577c680737bc",
        "email": "wschoenborn@mitotecprecision.com",
        "contact_url": "https://www.mitotecprecision.com/about/meet-the-team/",
        "anchor": "Precision CNC Machining",
        "process": "Request a Quote",
    },
]


def text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def truthy(value: object) -> bool:
    return text(value).casefold() in {"1", "true", "yes", "ja", "y", "on"}


def load_sheet(service, sheet: str, headers: list[str]):
    actual, rows = rows_from_values(get_values(service, SPREADSHEET_ID, sheet))
    ensure_expected_headers(actual, headers, sheet)
    return actual, [{str(k): str(v or "") for k, v in row.items()} for row in rows]


def approved_source_ids(source_rows) -> set[str]:
    return {
        text(row.get("source_id"))
        for row in source_rows
        if text(row.get("source_id")) and truthy(row.get("approved")) and truthy(row.get("enabled"))
    }


def email_domain(address: str) -> str:
    return contact.email_domain(address)


def make_queue_row(candidate, qrow, spec, *, checked_at: str) -> dict[str, str]:
    company = text(candidate.get("company"))
    website = text(candidate.get("website"))
    lead_id = text(candidate.get("candidate_id"))
    anchor = text(spec["anchor"])
    process_label = text(spec["process"])
    evidence_url = text(qrow.get("evidence_url")) or website
    body = targeted.human_body(company, anchor, process_label, lead_id)
    if targeted.BANNED_COPY_RE.search(body):
        raise RuntimeError(f"prospect-facing banned jargon for {lead_id}")
    words = targeted.word_count_core(body)
    if words < 40 or words > 120:
        raise RuntimeError(f"copy length outside contract for {lead_id}: {words}")
    value = (
        f'Around "{anchor}", a short example could ask only for missing request details '
        "before your team reviews the quote or intake"
    )
    fact = f'I noticed "{anchor}" alongside the "{process_label}" path on your site.'
    meta = {
        "automation": "agent_sales_prepare_v2",
        "offer_family": "ai_agent",
        "agent_type": TARGET_AGENT,
        "business_process": text(qrow.get("business_process")) or "request_to_complete_intake",
        "kpi_candidate": text(qrow.get("kpi_candidate")) or "complete_intake_to_quote",
        "integration_hint": text(qrow.get("integration_hint")) or "form/chat + CRM + quote workflow",
        "evidence_url": evidence_url,
        "fact": fact,
        "idea": value,
        "qualification_tier": "A",
        "customer_potential": text(qrow.get("customer_potential")) or "8",
        "campaign_target_agent_type": TARGET_AGENT,
        "value_asset_type": "process_flow",
        "value_asset_status": "concept_ready",
        "value_asset_summary": value,
        "personalization_anchor": anchor,
        "personalization_process_label": process_label,
        "personalization_evidence_url": evidence_url,
        "contact_evidence_url": text(spec["contact_url"]),
        "cta_variant": "A",
        "copy_contract": "evidence_personalized_v13_5",
        "draft_copy_contract": "context_resolved_human_v7",
    }
    subject = f"Quote requests at {company}"
    return {
        "lead_id": lead_id,
        "company": company,
        "website": website,
        "email": text(spec["email"]).casefold(),
        "first_name": "",
        "subject": subject,
        "body": body,
        "followup_subject": subject,
        "followup_body": (
            f"Hi {company} team,\n\nJust following up once. I still have the short example for {company} ready.\n\n"
            "Want me to send it over?\n\nNot relevant? A quick \"no\" is enough.\n\nBest regards,\nAndrew Baeten"
        ),
        "followup_delay_days": "4",
        "country": TARGET_COUNTRY,
        "compliance_status": "manual_review",
        "opt_out_mode": "reply_optout",
        "status": "manual_review",
        "verification_status": "official_site_ready",
        "verification_checked_at": checked_at,
        "stage": "1",
        "next_send_at": "",
        "sent_at": "",
        "followup_sent_at": "",
        "message_id": "",
        "followup_message_id": "",
        "reply_at": "",
        "bounce_at": "",
        "last_error": "",
        "source": "agent_offer:" + json.dumps(meta, ensure_ascii=False, separators=(",", ":")),
        "sender_mailbox_id": os.getenv("OUTREACH_MAILBOX_ID", "primary").strip() or "primary",
        "sender_email": os.getenv("OUTREACH_SENDER_EMAIL", "info@andrewbaeten.nl").strip(),
        "compliance_basis": "",
    }


def main() -> int:
    if not SPREADSHEET_ID or not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("Sheet runtime configuration is required")

    service = build_sheets_service()
    _, candidates = load_sheet(service, qual.PROSPECT_SHEET, qual.PROSPECT_HEADERS)
    _, qrows = load_sheet(service, qual.AGENT_QUALIFICATION_SHEET, qual.AGENT_QUALIFICATION_HEADERS)
    _, contacts = load_sheet(service, contact.CONTACT_SHEET, contact.CONTACT_HEADERS)
    _, queue_rows = load_sheet(service, prepare.QUEUE_SHEET, prepare.FULL_QUEUE_HEADERS)
    _, lead_rows = load_sheet(service, prepare.LEAD_SHEET, prepare.LEAD_HEADERS)
    _, source_rows = load_sheet(service, SOURCE_SHEET, SOURCE_HEADERS)

    candidate_by_id = {text(row.get("candidate_id")): row for row in candidates if text(row.get("candidate_id"))}
    q_by_id = {text(row.get("candidate_id")): row for row in qrows if text(row.get("candidate_id"))}
    approved = approved_source_ids(source_rows)
    existing_queue_ids = {text(row.get("lead_id")) for row in queue_rows if text(row.get("lead_id"))}
    existing_queue_domains = {host_key(row.get("website", "")) for row in queue_rows if host_key(row.get("website", ""))}
    all_lead_domains = {
        host_key(row.get("Website", "")) for row in lead_rows if host_key(row.get("Website", ""))
    }
    baseline_domains = {
        host_key(row.get("Website", "")) for row in lead_rows[:BASELINE_LEAD_COUNT] if host_key(row.get("Website", ""))
    }

    prepared = []
    contact_written = []
    existing = []
    failures = []

    for spec in SPECS:
        cid = text(spec["candidate_id"])
        candidate = candidate_by_id.get(cid)
        qrow = q_by_id.get(cid)
        if not candidate or not qrow:
            failures.append({"candidate_id": cid, "reason": "missing candidate or qualification"})
            continue
        website = text(candidate.get("website"))
        domain = host_key(website)
        if canonical_country(candidate.get("country", "")) != TARGET_COUNTRY:
            failures.append({"candidate_id": cid, "reason": "candidate is not US"})
            continue
        if text(candidate.get("source_id")) not in approved:
            failures.append({"candidate_id": cid, "reason": "source is not approved+enabled"})
            continue
        if (
            text(qrow.get("status")).casefold() != "qualified"
            or text(qrow.get("tier")).upper() != "A"
            or text(qrow.get("agent_type")) != TARGET_AGENT
            or int(text(qrow.get("customer_potential")) or "0") < 8
        ):
            failures.append({"candidate_id": cid, "reason": "not current A-fit quote_intake"})
            continue
        if not domain or domain in baseline_domains:
            failures.append({"candidate_id": cid, "reason": "baseline-domain dedupe blocked"})
            continue
        proof_domain = host_key(text(spec["contact_url"]))
        if proof_domain != domain:
            failures.append({"candidate_id": cid, "reason": "contact proof is not same official domain"})
            continue
        address = contact.normalize_email(text(spec["email"]))
        if not address or not contact.is_allowed_business_address(address):
            failures.append({"candidate_id": cid, "reason": "invalid or disallowed business address"})
            continue
        address_domain = email_domain(address)
        if not contact.aligned_domain(website, address_domain):
            failures.append({"candidate_id": cid, "reason": "email domain does not align to official website"})
            continue
        mx = contact.mx_status(address_domain)
        if mx != "present":
            failures.append({"candidate_id": cid, "reason": f"MX not proven present: {mx}"})
            continue
        if cid in existing_queue_ids or domain in existing_queue_domains:
            existing.append(cid)
            continue

        checked_at = qual.utc_iso()
        contact_row = {
            "candidate_id": cid,
            "checked_at": checked_at,
            "company": text(candidate.get("company")),
            "website": website,
            "email": address,
            "source_url": text(spec["contact_url"]),
            "email_domain": address_domain,
            "domain_alignment": "aligned",
            "mx_status": "present",
            "status": "ready",
            "reason": "public business address independently verified on official company source; aligned domain and MX present",
        }
        append_row(service, SPREADSHEET_ID, contact.CONTACT_SHEET, contact.CONTACT_HEADERS, contact_row)
        contact_written.append(cid)

        queue_row = make_queue_row(candidate, qrow, spec, checked_at=checked_at)
        if domain not in all_lead_domains:
            prepare._append_lead(
                service,
                SPREADSHEET_ID,
                {
                    "Bedrijf": queue_row["company"],
                    "Website": queue_row["website"],
                    "E-mail": queue_row["email"],
                    "Status": "gevonden",
                },
            )
            all_lead_domains.add(domain)
        queue_rows.append(queue_row)
        prepared.append(cid)
        existing_queue_ids.add(cid)
        existing_queue_domains.add(domain)
        print(f"FINAL8_PREPARED={len(prepared)} lead_id={cid} company={queue_row['company']}", flush=True)

    if prepared:
        prepare._replace_rows(service, SPREADSHEET_ID, prepare.QUEUE_SHEET, prepare.FULL_QUEUE_HEADERS, queue_rows)

    _, queue_after = load_sheet(service, prepare.QUEUE_SHEET, prepare.FULL_QUEUE_HEADERS)
    queue_after_ids = {text(row.get("lead_id")) for row in queue_after if text(row.get("lead_id"))}
    resolved = [text(spec["candidate_id"]) for spec in SPECS if text(spec["candidate_id"]) in queue_after_ids]

    report = {
        "status": "green" if len(resolved) == len(SPECS) and not failures else "blocked",
        "target": len(SPECS),
        "prepared": prepared,
        "existing": existing,
        "resolved_queue_ids": resolved,
        "contact_rows_written": contact_written,
        "failures": failures,
        "campaign": "US manufacturing / quote_intake",
        "qualification": "A only",
        "contact": "official company source + aligned domain + MX present",
        "queue_status": "manual_review",
        "send_permission": "none",
        "smtp_send": "not_invoked",
    }
    Path("final-eight-repair.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["status"] != "green":
        print(f"FINAL8_REPAIR=blocked resolved={len(resolved)} target={len(SPECS)} failures={len(failures)} smtp_send=not_invoked", flush=True)
        return 2
    print(f"FINAL8_REPAIR=green resolved={len(resolved)} target={len(SPECS)} smtp_send=not_invoked", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
