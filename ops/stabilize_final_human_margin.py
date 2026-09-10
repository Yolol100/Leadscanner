from __future__ import annotations

import json
import os
import re
import sys
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
from outreach_sender import build_sheets_service, ensure_expected_headers, get_values, rows_from_values
from prospect_target_policy import canonical_country

SPREADSHEET_ID = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
FINAL_COPY_CONTRACT = "context_resolved_human_v7"
COPY_CONTRACT = "evidence_personalized_v13_5"
TARGET_AGENT = "quote_intake"

PATCHES = {
    "prospect-e8e30cba0b58d5e30a37": {
        "anchor": "CNC Vertical Machining Services",
        "process": "Request a Quote",
        "evidence_url": "https://www.jessenmfg.com/capabilities/cnc-vertical-machining-services",
        "contact_evidence_url": "https://www.jessenmfg.com/request-quote/",
    },
    "prospect-pma-24a67fea0ef70ce15596": {
        "anchor": "AMLUBE® Lubricants & Coatings",
        "process": "Get a Quote",
        "evidence_url": "https://amlube.com/products/",
        "contact_evidence_url": "https://amlube.com/aml-industries-information-sheet/",
    },
}


def text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def load_sheet(service, sheet: str, headers: list[str]):
    actual, rows = rows_from_values(get_values(service, SPREADSHEET_ID, sheet))
    ensure_expected_headers(actual, headers, sheet)
    return actual, [{str(k): str(v or "") for k, v in row.items()} for row in rows]


def parse_meta(source: str) -> dict:
    raw = str(source or "")
    if not raw.startswith("agent_offer:"):
        return {}
    try:
        value = json.loads(raw.split(":", 1)[1])
    except (ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def ready_contact(rows, candidate_id: str, email: str) -> bool:
    needle = email.casefold()
    for row in rows:
        if text(row.get("candidate_id")) != candidate_id:
            continue
        if text(row.get("email")).casefold() != needle:
            continue
        if text(row.get("status")).casefold() != "ready":
            continue
        if text(row.get("domain_alignment")).casefold() != "aligned":
            continue
        if text(row.get("mx_status")).casefold() != "present":
            continue
        return True
    return False


def main() -> int:
    if not SPREADSHEET_ID or not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("Sheet runtime configuration is required")

    service = build_sheets_service()
    headers, queue = load_sheet(service, prepare.QUEUE_SHEET, prepare.FULL_QUEUE_HEADERS)
    _, qualifications = load_sheet(service, qual.AGENT_QUALIFICATION_SHEET, qual.AGENT_QUALIFICATION_HEADERS)
    _, contacts = load_sheet(service, contact.CONTACT_SHEET, contact.CONTACT_HEADERS)
    q_by_id = {text(row.get("candidate_id")): row for row in qualifications if text(row.get("candidate_id"))}
    row_by_id = {text(row.get("lead_id")): row for row in queue if text(row.get("lead_id"))}

    patched = []
    failures = []
    for lead_id, spec in PATCHES.items():
        row = row_by_id.get(lead_id)
        qrow = q_by_id.get(lead_id)
        if not row or not qrow:
            failures.append(f"{lead_id}:missing_queue_or_qualification")
            continue
        if canonical_country(row.get("country", "")) != "US":
            failures.append(f"{lead_id}:not_us")
            continue
        if text(row.get("verification_status")).casefold() != "official_site_ready":
            failures.append(f"{lead_id}:contact_not_official_site_ready")
            continue
        if not ready_contact(contacts, lead_id, text(row.get("email"))):
            failures.append(f"{lead_id}:no_ready_aligned_mx_contact")
            continue
        if (
            text(qrow.get("status")).casefold() != "qualified"
            or text(qrow.get("tier")).upper() != "A"
            or text(qrow.get("agent_type")) != TARGET_AGENT
            or int(text(qrow.get("customer_potential")) or "0") < 8
        ):
            failures.append(f"{lead_id}:not_current_a_quote_intake")
            continue

        meta = parse_meta(row.get("source", ""))
        if text(meta.get("copy_contract")) != COPY_CONTRACT:
            failures.append(f"{lead_id}:wrong_copy_contract")
            continue
        anchor = text(spec["anchor"])
        process = text(spec["process"])
        company = text(row.get("company"))
        value = (
            f'Around "{anchor}", a short example could ask only for missing request details '
            "before your team reviews the quote or intake"
        )
        meta.update({
            "evidence_url": text(spec["evidence_url"]),
            "fact": f'I noticed "{anchor}" alongside the "{process}" path on your site.',
            "idea": value,
            "value_asset_summary": value,
            "personalization_anchor": anchor,
            "personalization_process_label": process,
            "personalization_evidence_url": text(spec["evidence_url"]),
            "contact_evidence_url": text(spec["contact_evidence_url"]),
            "draft_copy_contract": FINAL_COPY_CONTRACT,
        })
        body = targeted.human_body(company, anchor, process, lead_id)
        if targeted.BANNED_COPY_RE.search(body):
            failures.append(f"{lead_id}:banned_copy_jargon")
            continue
        words = targeted.word_count_core(body)
        if words < 40 or words > 120:
            failures.append(f"{lead_id}:copy_length_{words}")
            continue
        row["subject"] = f"Quote requests at {company}"
        row["body"] = body
        row["status"] = "manual_review"
        row["compliance_status"] = "manual_review"
        row["compliance_basis"] = ""
        row["source"] = "agent_offer:" + json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
        patched.append(lead_id)

    if failures:
        Path("final-human-margin.json").write_text(
            json.dumps({"status": "blocked", "patched": patched, "failures": failures, "smtp_send": "not_invoked"}, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"FINAL_HUMAN_MARGIN=blocked patched={len(patched)} failures={len(failures)} smtp_send=not_invoked", flush=True)
        return 2

    values = [[str(row.get(header, "")) for header in headers] for row in queue]
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{prepare.QUEUE_SHEET}'!A2",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()

    _, after = load_sheet(service, prepare.QUEUE_SHEET, prepare.FULL_QUEUE_HEADERS)
    after_by_id = {text(row.get("lead_id")): row for row in after if text(row.get("lead_id"))}
    verified = []
    for lead_id, spec in PATCHES.items():
        row = after_by_id.get(lead_id, {})
        meta = parse_meta(row.get("source", ""))
        if text(meta.get("personalization_anchor")) == text(spec["anchor"]):
            verified.append(lead_id)
    status = "green" if len(verified) == len(PATCHES) else "blocked"
    Path("final-human-margin.json").write_text(
        json.dumps({"status": status, "patched": patched, "verified": verified, "smtp_send": "not_invoked"}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"FINAL_HUMAN_MARGIN={status} verified={len(verified)} target={len(PATCHES)} smtp_send=not_invoked", flush=True)
    return 0 if status == "green" else 2


if __name__ == "__main__":
    raise SystemExit(main())
