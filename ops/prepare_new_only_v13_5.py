from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import outreach_agent_prepare as legacy
import outreach_agent_prepare_v2 as v2
from prospect_intelligence import canonical_domain
from prospect_target_policy import canonical_country

TARGET_AGENT = "quote_intake"
TARGET_COUNTRY = "US"


def _rows(service, spreadsheet_id: str, sheet: str):
    return legacy.rows_from_values(legacy.get_values(service, spreadsheet_id, sheet))


def run(target_new: int, report_path: str) -> int:
    spreadsheet_id = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        raise RuntimeError("OUTREACH_SPREADSHEET_ID is required")
    if not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is required")
    if not os.getenv("OUTREACH_POSTAL_ADDRESS", "").strip():
        raise RuntimeError("OUTREACH_POSTAL_ADDRESS is required for US commercial draft copy")

    service = legacy.build_sheets_service()
    candidate_headers, candidates = _rows(service, spreadsheet_id, legacy.PROSPECT_SHEET)
    legacy.ensure_expected_headers(candidate_headers, legacy.PROSPECT_HEADERS, legacy.PROSPECT_SHEET)
    qualification_headers, qualifications = _rows(service, spreadsheet_id, legacy.AGENT_QUALIFICATION_SHEET)
    legacy.ensure_expected_headers(
        qualification_headers, legacy.AGENT_QUALIFICATION_HEADERS, legacy.AGENT_QUALIFICATION_SHEET
    )
    contact_headers, contacts = _rows(service, spreadsheet_id, legacy.CONTACT_SHEET)
    legacy.ensure_expected_headers(contact_headers, legacy.CONTACT_HEADERS, legacy.CONTACT_SHEET)
    queue_headers, queue = _rows(service, spreadsheet_id, legacy.QUEUE_SHEET)
    legacy.ensure_expected_headers(queue_headers, legacy.FULL_QUEUE_HEADERS, legacy.QUEUE_SHEET)
    lead_headers, leads = _rows(service, spreadsheet_id, legacy.LEAD_SHEET)
    legacy.ensure_expected_headers(lead_headers, legacy.LEAD_HEADERS, legacy.LEAD_SHEET)

    qualification_by_id = {
        legacy._text(row.get("candidate_id")): row
        for row in qualifications
        if legacy._text(row.get("candidate_id"))
    }
    contact_by_id = {
        legacy._text(row.get("candidate_id")): row
        for row in contacts
        if legacy._text(row.get("candidate_id"))
    }
    queue_by_id = {
        legacy._text(row.get("lead_id")): row
        for row in queue
        if legacy._text(row.get("lead_id"))
    }
    lead_domains = {
        canonical_domain(row.get("Website") or row.get("website"))
        for row in leads
    }
    lead_domains.discard("")

    sender_mailbox_id = os.getenv("OUTREACH_MAILBOX_ID", "primary").strip() or "primary"
    sender_email = os.getenv("OUTREACH_SENDER_EMAIL", "info@andrewbaeten.nl").strip()
    postal_address = os.getenv("OUTREACH_POSTAL_ADDRESS", "")

    prepared = skipped_existing = skipped_not_eligible = skipped_copy = 0
    prepared_ids: list[str] = []

    for candidate in candidates:
        if prepared >= target_new:
            break
        candidate_id = legacy._text(candidate.get("candidate_id"))
        if not candidate_id or candidate_id in queue_by_id:
            skipped_existing += 1
            continue
        if canonical_country(legacy._text(candidate.get("country"))) != TARGET_COUNTRY:
            continue
        domain = canonical_domain(candidate.get("website"))
        if not domain or domain in lead_domains:
            skipped_existing += 1
            continue

        qualification = qualification_by_id.get(candidate_id)
        contact = contact_by_id.get(candidate_id)
        if not legacy._prepare_eligible(candidate, qualification, contact):
            skipped_not_eligible += 1
            continue
        if legacy._text(qualification.get("agent_type")).casefold() != TARGET_AGENT:
            skipped_not_eligible += 1
            continue

        try:
            new_row = v2.build_prepared_row(
                candidate,
                qualification,
                contact,
                postal_address=postal_address,
                sender_mailbox_id=sender_mailbox_id,
                sender_email=sender_email,
            )
        except (RuntimeError, ValueError, OSError):
            skipped_copy += 1
            continue

        new_row["status"] = "manual_review"
        new_row["compliance_status"] = "manual_review"
        new_row["compliance_basis"] = ""

        queue.append(new_row)
        queue_by_id[candidate_id] = new_row
        legacy._append_lead(
            service,
            spreadsheet_id,
            {
                "Bedrijf": new_row["company"],
                "Website": new_row["website"],
                "E-mail": new_row["email"],
                "Status": "gevonden",
            },
        )
        lead_domains.add(domain)
        prepared += 1
        prepared_ids.append(candidate_id)
        print(f"NEW_ONLY_PREPARED={prepared} lead_id={candidate_id}", flush=True)

    if prepared:
        legacy._replace_rows(service, spreadsheet_id, legacy.QUEUE_SHEET, legacy.FULL_QUEUE_HEADERS, queue)

    payload = {
        "status": "completed",
        "prepared": prepared,
        "prepared_ids": prepared_ids,
        "skipped_existing": skipped_existing,
        "skipped_not_eligible": skipped_not_eligible,
        "skipped_copy": skipped_copy,
        "agent_type": TARGET_AGENT,
        "country": TARGET_COUNTRY,
        "send_permission": "none",
        "smtp_send": "not_invoked",
    }
    Path(report_path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"NEW_ONLY_PREPARE=complete prepared={prepared} target={target_new} "
        "send_permission=none smtp_send=not_invoked",
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-new", type=int, default=25)
    parser.add_argument("--report", default="prepare-new-only-report.json")
    args = parser.parse_args()
    try:
        return run(max(1, min(args.target_new, 25)), args.report)
    except (RuntimeError, ValueError) as exc:
        Path(args.report).write_text(
            json.dumps({"status": "blocked", "error": str(exc), "send_permission": "none"}, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"NEW_ONLY_PREPARE=blocked detail={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
