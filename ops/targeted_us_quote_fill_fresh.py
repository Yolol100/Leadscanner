from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "ops"
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(OPS))
sys.path.insert(0, str(SCRIPTS))

import targeted_us_quote_fill as base
from prospect_discovery import BoundedHttpClient, DiscoveryError, host_key, root_url
from prospect_target_policy import canonical_country

TASK_REASSESS_CUTOFF = "2026-09-09T22:19:00Z"


def recently_rejected_for_this_campaign(qrow: Mapping[str, str] | None) -> bool:
    if not qrow:
        return False
    assessed_at = base.text(qrow.get("assessed_at"))
    if not assessed_at or assessed_at < TASK_REASSESS_CUTOFF:
        return False
    is_a = (
        base.text(qrow.get("status")).casefold() == "qualified"
        and base.text(qrow.get("tier")).upper() == "A"
        and base.text(qrow.get("agent_type")) == base.TARGET_AGENT
    )
    if is_a:
        return False
    reason = base.text(qrow.get("reason"))
    return "campaign_target=quote_intake" in reason or "source_semantic_target_policy:" in reason


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-new", type=int, default=35)
    parser.add_argument("--max-assess", type=int, default=250)
    parser.add_argument("--report", default="targeted-us-quote-fill-fresh.json")
    args = parser.parse_args()
    target_new = max(1, min(args.target_new, 40))
    max_assess = max(target_new, min(args.max_assess, 250))

    if not base.SPREADSHEET_ID or not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("Sheet runtime configuration is required")

    service = base.build_sheets_service()
    _candidate_headers, candidates = base.load_sheet(service, base.qual.PROSPECT_SHEET, base.qual.PROSPECT_HEADERS)
    _signal_headers, signals = base.load_sheet(service, base.qual.SIGNAL_SHEET, base.SIGNAL_HEADERS)
    _aq_headers, aq_rows = base.load_sheet(service, base.qual.AGENT_QUALIFICATION_SHEET, base.qual.AGENT_QUALIFICATION_HEADERS)
    _contact_headers, contact_rows = base.load_sheet(service, base.contact.CONTACT_SHEET, base.contact.CONTACT_HEADERS)
    _queue_headers, queue_rows = base.load_sheet(service, base.prepare.QUEUE_SHEET, base.prepare.FULL_QUEUE_HEADERS)
    _lead_headers, lead_rows = base.load_sheet(service, base.prepare.LEAD_SHEET, base.prepare.LEAD_HEADERS)
    _source_headers, source_rows = base.load_sheet(service, base.PROSPECT_SOURCE_SHEET, base.SOURCE_HEADERS)

    pre_domains = base.pretask_domains(lead_rows)
    all_domains = base.all_lead_domains(lead_rows)
    queue_ids = {base.text(row.get("lead_id")) for row in queue_rows if base.text(row.get("lead_id"))}
    queue_domains = {host_key(row.get("website", "")) for row in queue_rows if host_key(row.get("website", ""))}
    source_ids = base.approved_sources(source_rows)
    aq_by_id = {base.text(row.get("candidate_id")): dict(row) for row in aq_rows if base.text(row.get("candidate_id"))}
    contacts_by_id: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in contact_rows:
        cid = base.text(row.get("candidate_id"))
        if cid:
            contacts_by_id[cid].append(row)

    client = BoundedHttpClient(
        user_agent="WebactueelFreshQuoteFill/1.0 (+https://andrewbaeten.nl)",
        timeout=8.0,
        max_bytes=524288,
        min_interval=0.25,
    )

    eligible = []
    skipped_recent = 0
    for index, candidate in enumerate(candidates):
        cid = base.text(candidate.get("candidate_id"))
        domain = host_key(base.text(candidate.get("website")))
        if not cid or cid == base.BASELINE_LEAD_ID or cid in queue_ids:
            continue
        if canonical_country(base.text(candidate.get("country"))) != base.TARGET_COUNTRY:
            continue
        if not domain or domain in pre_domains or domain in queue_domains:
            continue
        if base.text(candidate.get("source_id")) not in source_ids:
            continue
        qrow = aq_by_id.get(cid)
        if recently_rejected_for_this_campaign(qrow):
            skipped_recent += 1
            continue
        eligible.append((index, candidate))

    def rank(item):
        _, candidate = item
        cid = base.text(candidate.get("candidate_id"))
        qrow = aq_by_id.get(cid, {})
        crow = base.best_ready_contact(contacts_by_id.get(cid, []))
        a_ready = (
            base.text(qrow.get("status")).casefold() == "qualified"
            and base.text(qrow.get("tier")).upper() == "A"
            and base.text(qrow.get("agent_type")) == base.TARGET_AGENT
        )
        return (0 if a_ready and crow else 1 if a_ready else 2, cid)

    eligible.sort(key=rank)
    prepared_rows = []
    prepared_ids = []
    assessed = qualified = contact_checked = contact_ready = copy_rejected = 0
    skip_reasons: dict[str, int] = defaultdict(int)

    for _index, candidate in eligible:
        if len(prepared_rows) >= target_new or assessed >= max_assess:
            break
        cid = base.text(candidate.get("candidate_id"))
        website = root_url(base.text(candidate.get("website")))
        qrow = aq_by_id.get(cid)
        q_is_a = bool(
            qrow
            and base.text(qrow.get("status")).casefold() == "qualified"
            and base.text(qrow.get("tier")).upper() == "A"
            and base.text(qrow.get("agent_type")) == base.TARGET_AGENT
        )
        if not q_is_a:
            assessed += 1
            try:
                homepage_html = client.fetch_text(website)
                homepage = base.qual._parse_evidence_page(homepage_html, website)
                process_url = base.qual.select_process_evidence_link(homepage, website, base.TARGET_AGENT)
                process_html = ""
                if process_url:
                    try:
                        process_html = client.fetch_text(process_url)
                    except (DiscoveryError, RuntimeError, ValueError):
                        process_url = ""
                        process_html = ""
                assessment = base.qual.assess_candidate(
                    candidate,
                    homepage_html,
                    signals,
                    target_agent_type=base.TARGET_AGENT,
                    process_html=process_html,
                    process_url=process_url,
                )
            except (DiscoveryError, RuntimeError, ValueError) as exc:
                skip_reasons[f"qualification_fetch:{type(exc).__name__}"] += 1
                continue
            candidate["status"] = assessment.status
            candidate["reason"] = assessment.reason
            qrow = base.assessment_row(candidate, assessment)
            aq_by_id[cid] = qrow
            if assessment.status != "qualified" or assessment.tier != "A" or assessment.agent_type != base.TARGET_AGENT:
                skip_reasons[f"qualification:{assessment.tier}"] += 1
                continue
            qualified += 1

        crows = contacts_by_id.get(cid, [])
        crow = base.best_ready_contact(crows)
        if crow is None:
            if crows:
                skip_reasons["contact_existing_nonready"] += 1
                continue
            contact_checked += 1
            output, is_ready = base.contact.contact_output(candidate, fetch=client.fetch_text)
            base.append_row(
                service,
                base.SPREADSHEET_ID,
                base.contact.CONTACT_SHEET,
                base.contact.CONTACT_HEADERS,
                output,
            )
            contacts_by_id[cid].append(output)
            if not is_ready:
                skip_reasons[f"contact:{base.text(output.get('status')) or 'unknown'}"] += 1
                continue
            crow = output
            contact_ready += 1

        queue_row, reason = base.build_queue_row(candidate, qrow, crow, client=client)
        if not queue_row:
            copy_rejected += 1
            skip_reasons[reason or "copy_unknown"] += 1
            continue

        domain = host_key(queue_row.get("website", ""))
        if domain and domain not in all_domains:
            base.prepare._append_lead(
                service,
                base.SPREADSHEET_ID,
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
        print(f"FRESH_HUMAN_PREPARED={len(prepared_rows)} lead_id={cid} company={queue_row['company']}", flush=True)

    base.qual._replace_rows(
        service,
        base.SPREADSHEET_ID,
        base.qual.PROSPECT_SHEET,
        base.qual.PROSPECT_HEADERS,
        candidates,
    )
    aq_final = [aq_by_id[key] for key in sorted(aq_by_id)]
    base.qual._replace_rows(
        service,
        base.SPREADSHEET_ID,
        base.qual.AGENT_QUALIFICATION_SHEET,
        base.qual.AGENT_QUALIFICATION_HEADERS,
        aq_final,
    )
    if prepared_rows:
        queue_rows.extend(prepared_rows)
        base.prepare._replace_rows(
            service,
            base.SPREADSHEET_ID,
            base.prepare.QUEUE_SHEET,
            base.prepare.FULL_QUEUE_HEADERS,
            queue_rows,
        )

    report = {
        "status": "completed",
        "target_new": target_new,
        "prepared": len(prepared_rows),
        "prepared_ids": prepared_ids,
        "eligible_after_recent_skip": len(eligible),
        "skipped_recent_campaign_non_a": skipped_recent,
        "assessed": assessed,
        "qualified_new": qualified,
        "contact_checked": contact_checked,
        "contact_ready_new": contact_ready,
        "copy_rejected": copy_rejected,
        "skip_reasons": dict(sorted(skip_reasons.items())),
        "agent_type": base.TARGET_AGENT,
        "country": base.TARGET_COUNTRY,
        "copy_contract": "context_resolved_human_v7",
        "queue_status": "manual_review",
        "send_permission": "none",
        "smtp_send": "not_invoked",
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"FRESH_US_QUOTE_FILL=complete prepared={len(prepared_rows)} target={target_new} "
        f"eligible={len(eligible)} skipped_recent={skipped_recent} assessed={assessed} "
        f"qualified={qualified} contact_ready={contact_ready} smtp_send=not_invoked",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
