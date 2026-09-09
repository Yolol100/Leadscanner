from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import outreach_agent_prepare as prepare
import outreach_site_personalization as sitecopy
import prospect_agent_qualification as qual
import prospect_contact_enrichment as contact
from outreach_sender import append_row, build_sheets_service, ensure_expected_headers, get_values, rows_from_values
from prospect_discovery import BoundedHttpClient, DiscoveryError, host_key, root_url
from prospect_intelligence import SIGNAL_HEADERS
from prospect_target_policy import canonical_country

SPREADSHEET_ID = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
TARGET_AGENT = "quote_intake"
TARGET_COUNTRY = "US"
BASELINE_LEAD_COUNT = 175
BASELINE_LEAD_ID = "prospect-25d374063f3f069399d1"
PROSPECT_SOURCE_SHEET = "ProspectSources"
SOURCE_HEADERS = [
    "source_id", "source_type", "source_url", "country", "include_terms",
    "exclude_terms", "max_candidates", "approved", "enabled",
]
BANNED_COPY_RE = re.compile(r"\b(?:ai|automation|bot|roi|agentic|orchestration|agent)\b", re.I)


def truthy(value: object) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "ja", "y", "on"}


def text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def load_sheet(service, sheet: str, expected_headers: list[str]):
    headers, rows = rows_from_values(get_values(service, SPREADSHEET_ID, sheet))
    ensure_expected_headers(headers, expected_headers, sheet)
    return headers, rows


def parse_agent_source(value: str) -> dict:
    value = str(value or "")
    if not value.startswith("agent_offer:"):
        return {}
    try:
        payload = json.loads(value.split(":", 1)[1])
    except (ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def pretask_domains(leads: list[Mapping[str, str]]) -> set[str]:
    domains = set()
    for row in leads[:BASELINE_LEAD_COUNT]:
        domain = host_key(row.get("Website") or row.get("website") or "")
        if domain:
            domains.add(domain)
    return domains


def all_lead_domains(leads: list[Mapping[str, str]]) -> set[str]:
    return {
        domain
        for row in leads
        if (domain := host_key(row.get("Website") or row.get("website") or ""))
    }


def approved_sources(source_rows: list[Mapping[str, str]]) -> set[str]:
    return {
        text(row.get("source_id"))
        for row in source_rows
        if text(row.get("source_id")) and truthy(row.get("approved")) and truthy(row.get("enabled"))
    }


def best_ready_contact(rows: list[Mapping[str, str]]) -> Mapping[str, str] | None:
    ready = [row for row in rows if text(row.get("status")).casefold() == "ready"]
    if not ready:
        return None
    ready.sort(key=lambda row: text(row.get("checked_at")), reverse=True)
    return ready[0]


def assessment_row(candidate: Mapping[str, str], assessment: qual.Assessment) -> dict[str, str]:
    return {
        "candidate_id": text(candidate.get("candidate_id")),
        "assessed_at": qual.utc_iso(),
        "company": text(candidate.get("company")),
        "website": text(candidate.get("website")),
        "country": canonical_country(text(candidate.get("country"))),
        "icp_score": str(assessment.icp_score),
        "agent_opportunity_score": str(assessment.agent_opportunity_score),
        "signal_score": str(assessment.signal_score),
        "value_integration_fit_score": str(assessment.value_integration_fit_score),
        "customer_potential": str(assessment.customer_potential),
        "tier": assessment.tier,
        "evidence_url": assessment.evidence_url,
        "fact": assessment.fact,
        "idea": assessment.idea,
        "offer_family": assessment.offer_family,
        "agent_type": assessment.agent_type,
        "business_process": assessment.business_process,
        "kpi_candidate": assessment.kpi_candidate,
        "integration_hint": assessment.integration_hint,
        "status": assessment.status,
        "reason": assessment.reason,
    }


def human_body(company: str, anchor: str, process_label: str, lead_id: str) -> str:
    variants = int(hashlib.sha256(lead_id.encode("utf-8")).hexdigest()[:2], 16) % 3
    process = process_label or "quote request"
    openings = [
        f"I was looking at the {process} route on your site and noticed {anchor}.",
        f"While looking at how {company} handles {process} online, {anchor} stood out to me.",
        f"I came across {anchor} in the part of your site that leads into {process}.",
    ]
    ideas = [
        "One small idea: collect only the request details that are still missing before it reaches the team, so the first review starts with a more complete request.",
        "A simple improvement could be to ask for any missing request details first and then pass the complete request to the person who actually reviews it.",
        "I would keep it simple: fill in the missing request information before the handoff, without changing the rest of your quote process.",
    ]
    ctas = [
        f"Would you like me to send a short example using {anchor} as the starting point?",
        f"Want me to send a simple example of how that could work for {company}?",
        f"Would it be useful if I sent over a short example for {company}?",
    ]
    return (
        f"Hi {company} team,\n\n{openings[variants]}\n\n{ideas[variants]}\n\n{ctas[variants]}\n\n"
        "Not relevant? A quick \"no\" is enough.\n\nThis is a commercial message.\n\n"
        "Best regards,\nAndrew Baeten\n{{OUTREACH_POSTAL_ADDRESS}}\nandrewbaeten.nl"
    )


def word_count_core(body: str) -> int:
    core = body.split("Not relevant?", 1)[0]
    return len(re.findall(r"\b[\w'-]+\b", core))


def build_queue_row(candidate: Mapping[str, str], qrow: Mapping[str, str], crow: Mapping[str, str], *, client: BoundedHttpClient):
    company = text(candidate.get("company"))
    lead_id = text(candidate.get("candidate_id"))
    evidence_url = text(qrow.get("evidence_url")) or root_url(text(candidate.get("website")))
    if not company or not lead_id or not evidence_url:
        return None, "missing_identity_or_evidence"
    try:
        personalization = sitecopy.personalize_from_evidence(
            company=company,
            agent_type=TARGET_AGENT,
            language="en",
            evidence_url=evidence_url,
            fetcher=client.fetch_text,
        )
    except (ValueError, RuntimeError, OSError, DiscoveryError) as exc:
        return None, f"personalization:{type(exc).__name__}:{text(exc)[:160]}"

    anchor = text(personalization.anchor)
    process_label = text(personalization.process_label) or "quote request"
    if not anchor:
        return None, "missing_anchor"
    body = human_body(company, anchor, process_label, lead_id)
    subject = f"Quote requests at {company}"
    if BANNED_COPY_RE.search(subject) or BANNED_COPY_RE.search(body):
        return None, "prospect_copy_banned_jargon"
    words = word_count_core(body)
    if words < 40 or words > 120:
        return None, f"prospect_copy_length:{words}"

    fact = personalization.observation
    value = personalization.value
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
        "cta_variant": "A",
        "copy_contract": "evidence_personalized_v13_5",
        "draft_copy_contract": "context_resolved_human_v7",
    }
    return {
        "lead_id": lead_id,
        "company": company,
        "website": text(candidate.get("website")),
        "email": text(crow.get("email")),
        "first_name": "",
        "subject": subject,
        "body": body,
        "followup_subject": subject,
        "followup_body": (
            f"Hi {company} team,\n\nJust following up once. I still have the short example for {company} ready.\n\n"
            f"Want me to send it over?\n\nNot relevant? A quick \"no\" is enough.\n\nBest regards,\nAndrew Baeten"
        ),
        "followup_delay_days": "4",
        "country": TARGET_COUNTRY,
        "compliance_status": "manual_review",
        "opt_out_mode": "reply_optout",
        "status": "manual_review",
        "verification_status": "official_site_ready",
        "verification_checked_at": qual.utc_iso(),
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
    }, ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-new", type=int, default=30)
    parser.add_argument("--max-assess", type=int, default=160)
    parser.add_argument("--report", default="targeted-us-quote-fill.json")
    args = parser.parse_args()
    target_new = max(1, min(args.target_new, 40))
    max_assess = max(target_new, min(args.max_assess, 250))

    if not SPREADSHEET_ID or not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("Sheet runtime configuration is required")

    service = build_sheets_service()
    candidate_headers, candidates = load_sheet(service, qual.PROSPECT_SHEET, qual.PROSPECT_HEADERS)
    signal_headers, signals = load_sheet(service, qual.SIGNAL_SHEET, SIGNAL_HEADERS)
    aq_headers, aq_rows = load_sheet(service, qual.AGENT_QUALIFICATION_SHEET, qual.AGENT_QUALIFICATION_HEADERS)
    contact_headers, contact_rows = load_sheet(service, contact.CONTACT_SHEET, contact.CONTACT_HEADERS)
    queue_headers, queue_rows = load_sheet(service, prepare.QUEUE_SHEET, prepare.FULL_QUEUE_HEADERS)
    lead_headers, lead_rows = load_sheet(service, prepare.LEAD_SHEET, prepare.LEAD_HEADERS)
    source_headers, source_rows = load_sheet(service, PROSPECT_SOURCE_SHEET, SOURCE_HEADERS)

    pre_domains = pretask_domains(lead_rows)
    all_domains = all_lead_domains(lead_rows)
    queue_ids = {text(row.get("lead_id")) for row in queue_rows if text(row.get("lead_id"))}
    queue_domains = {host_key(row.get("website", "")) for row in queue_rows if host_key(row.get("website", ""))}
    source_ids = approved_sources(source_rows)
    aq_by_id = {text(row.get("candidate_id")): dict(row) for row in aq_rows if text(row.get("candidate_id"))}
    contacts_by_id: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in contact_rows:
        cid = text(row.get("candidate_id"))
        if cid:
            contacts_by_id[cid].append(row)

    client = BoundedHttpClient(
        user_agent="WebactueelTargetedQuoteFill/1.0 (+https://andrewbaeten.nl)",
        timeout=8.0,
        max_bytes=524288,
        min_interval=0.25,
    )

    eligible = []
    for index, candidate in enumerate(candidates):
        cid = text(candidate.get("candidate_id"))
        website = text(candidate.get("website"))
        domain = host_key(website)
        if not cid or cid == BASELINE_LEAD_ID or cid in queue_ids:
            continue
        if canonical_country(text(candidate.get("country"))) != TARGET_COUNTRY:
            continue
        if not domain or domain in pre_domains or domain in queue_domains:
            continue
        if text(candidate.get("source_id")) not in source_ids:
            continue
        eligible.append((index, candidate))

    def rank(item):
        _, candidate = item
        cid = text(candidate.get("candidate_id"))
        q = aq_by_id.get(cid, {})
        c = best_ready_contact(contacts_by_id.get(cid, []))
        a_ready = (
            text(q.get("status")).casefold() == "qualified"
            and text(q.get("tier")).upper() == "A"
            and text(q.get("agent_type")) == TARGET_AGENT
        )
        return (0 if a_ready and c else 1 if a_ready else 2, cid)

    eligible.sort(key=rank)
    prepared_rows = []
    prepared_ids = []
    assessed = qualified = contact_checked = contact_ready = copy_rejected = 0
    skip_reasons: dict[str, int] = defaultdict(int)

    for index, candidate in eligible:
        if len(prepared_rows) >= target_new or assessed >= max_assess:
            break
        cid = text(candidate.get("candidate_id"))
        website = root_url(text(candidate.get("website")))
        qrow = aq_by_id.get(cid)
        q_is_a = bool(
            qrow
            and text(qrow.get("status")).casefold() == "qualified"
            and text(qrow.get("tier")).upper() == "A"
            and text(qrow.get("agent_type")) == TARGET_AGENT
        )
        if not q_is_a:
            assessed += 1
            try:
                homepage_html = client.fetch_text(website)
                homepage = qual._parse_evidence_page(homepage_html, website)
                process_url = qual.select_process_evidence_link(homepage, website, TARGET_AGENT)
                process_html = ""
                if process_url:
                    try:
                        process_html = client.fetch_text(process_url)
                    except (DiscoveryError, RuntimeError, ValueError):
                        process_url = ""
                        process_html = ""
                assessment = qual.assess_candidate(
                    candidate,
                    homepage_html,
                    signals,
                    target_agent_type=TARGET_AGENT,
                    process_html=process_html,
                    process_url=process_url,
                )
            except (DiscoveryError, RuntimeError, ValueError) as exc:
                skip_reasons[f"qualification_fetch:{type(exc).__name__}"] += 1
                continue
            candidate["status"] = assessment.status
            candidate["reason"] = assessment.reason
            qrow = assessment_row(candidate, assessment)
            aq_by_id[cid] = qrow
            if assessment.status != "qualified" or assessment.tier != "A" or assessment.agent_type != TARGET_AGENT:
                skip_reasons[f"qualification:{assessment.tier}"] += 1
                continue
            qualified += 1

        crows = contacts_by_id.get(cid, [])
        crow = best_ready_contact(crows)
        if crow is None:
            if crows:
                skip_reasons["contact_existing_nonready"] += 1
                continue
            contact_checked += 1
            output, is_ready = contact.contact_output(candidate, fetch=client.fetch_text)
            append_row(service, SPREADSHEET_ID, contact.CONTACT_SHEET, contact.CONTACT_HEADERS, output)
            contacts_by_id[cid].append(output)
            if not is_ready:
                skip_reasons[f"contact:{text(output.get('status')) or 'unknown'}"] += 1
                continue
            crow = output
            contact_ready += 1

        queue_row, reason = build_queue_row(candidate, qrow, crow, client=client)
        if not queue_row:
            copy_rejected += 1
            skip_reasons[reason or "copy_unknown"] += 1
            continue

        domain = host_key(queue_row.get("website", ""))
        if domain and domain not in all_domains:
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
            all_domains.add(domain)
        prepared_rows.append(queue_row)
        prepared_ids.append(cid)
        queue_ids.add(cid)
        if domain:
            queue_domains.add(domain)
        print(f"TARGETED_HUMAN_PREPARED={len(prepared_rows)} lead_id={cid} company={queue_row['company']}", flush=True)

    qual._replace_rows(service, SPREADSHEET_ID, qual.PROSPECT_SHEET, qual.PROSPECT_HEADERS, candidates)
    aq_final = [aq_by_id[key] for key in sorted(aq_by_id)]
    qual._replace_rows(service, SPREADSHEET_ID, qual.AGENT_QUALIFICATION_SHEET, qual.AGENT_QUALIFICATION_HEADERS, aq_final)
    if prepared_rows:
        queue_rows.extend(prepared_rows)
        prepare._replace_rows(service, SPREADSHEET_ID, prepare.QUEUE_SHEET, prepare.FULL_QUEUE_HEADERS, queue_rows)

    report = {
        "status": "completed",
        "target_new": target_new,
        "prepared": len(prepared_rows),
        "prepared_ids": prepared_ids,
        "assessed": assessed,
        "qualified_new": qualified,
        "contact_checked": contact_checked,
        "contact_ready_new": contact_ready,
        "copy_rejected": copy_rejected,
        "skip_reasons": dict(sorted(skip_reasons.items())),
        "agent_type": TARGET_AGENT,
        "country": TARGET_COUNTRY,
        "copy_contract": "context_resolved_human_v7",
        "queue_status": "manual_review",
        "send_permission": "none",
        "smtp_send": "not_invoked",
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"TARGETED_US_QUOTE_FILL=complete prepared={len(prepared_rows)} target={target_new} "
        f"assessed={assessed} qualified={qualified} contact_ready={contact_ready} smtp_send=not_invoked",
        flush=True,
    )
    return 0 if prepared_rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
