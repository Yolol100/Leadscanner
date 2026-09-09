from __future__ import annotations

import hashlib
import imaplib
import json
import os
import re
import ssl
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from outreach_imap_draft import append_verified_draft, choose_mailbox, detect_drafts_folder
from outreach_mailboxes import enabled_mailboxes, load_mailboxes_from_env
from outreach_queue_imap_draft import (
    QUEUE_SHEET,
    SUPPRESSION_SHEET,
    TERMINAL_FIELDS,
    build_sheets_service,
    get_values,
    inject_private_postal_for_draft,
    rows_from_values,
    suppression_sets,
)

TARGET = 50
AGENT_TYPE = "quote_intake"
MAX_DISCOVERY_WAVES = 3
QUALIFICATION_PASSES_PER_WAVE = 8
SPREADSHEET_ID = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()

BANNED_BODY_TERMS = (
    "bounded digital agents",
    "human handoff where needed",
    "orchestration",
    "agentic",
    "ai-powered",
    "one concrete example flow",
)
BANNED_SUBJECT_RE = re.compile(r"(^re:|\bai\b|\bautomation\b|\bbot\b|\broi\b|%)", re.I)


def run_script(script: str, *args: str, extra_env: dict[str, str] | None = None) -> None:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    cmd = [sys.executable, str(SCRIPTS / script), *args]
    print("RUN", script, " ".join(args), flush=True)
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def queue_rows(service) -> list[dict[str, str]]:
    return rows_from_values(get_values(service, SPREADSHEET_ID, QUEUE_SHEET))


def parse_agent_source(source: str) -> dict:
    if not str(source or "").startswith("agent_offer:"):
        return {}
    try:
        value = json.loads(str(source).split(":", 1)[1])
    except (ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def domain_of(email: str) -> str:
    value = str(email or "").strip().lower()
    return value.rsplit("@", 1)[1] if "@" in value else ""


def review_draft_errors(
    row: dict[str, str],
    *,
    sender_email: str,
    suppressed_emails: set[str],
    suppressed_domains: set[str],
) -> list[str]:
    errors: list[str] = []
    recipient = str(row.get("email", "")).strip().lower()
    status = str(row.get("status", "")).strip().lower()
    stage = str(row.get("stage", "")).strip()
    configured_sender = str(row.get("sender_email", "")).strip().lower()
    sender = str(sender_email or "").strip().lower()

    if status not in {"prepared", "manual_review", "approved"}:
        errors.append("queue status is not review-draft eligible")
    if stage not in {"", "1"}:
        errors.append("only initial stage can be review-drafted")
    if "@" not in recipient:
        errors.append("recipient email is invalid")
    if not str(row.get("subject", "")).strip():
        errors.append("subject is missing")
    if not str(row.get("body", "")).strip():
        errors.append("body is missing")
    if any(str(row.get(field, "")).strip() for field in TERMINAL_FIELDS):
        errors.append("row already has send/reply/bounce evidence")
    if configured_sender and sender and configured_sender != sender:
        errors.append("queue sender does not match configured mailbox")
    if recipient in suppressed_emails or domain_of(recipient) in suppressed_domains:
        errors.append("recipient is suppressed")
    return errors


def selected_rows(service, baseline_ids: set[str]) -> list[dict[str, str]]:
    suppressed_emails, suppressed_domains = suppression_sets(
        get_values(service, SPREADSHEET_ID, SUPPRESSION_SHEET)
    )
    candidates: list[tuple[int, str, dict[str, str]]] = []
    seen_companies: set[str] = set()
    seen_copy: set[tuple[str, str]] = set()

    for row in queue_rows(service):
        lead_id = str(row.get("lead_id", "")).strip()
        if not lead_id or lead_id in baseline_ids:
            continue
        if str(row.get("country", "")).strip().upper() != "US":
            continue
        if str(row.get("verification_status", "")).strip().lower() != "official_site_ready":
            continue
        meta = parse_agent_source(row.get("source", ""))
        if not meta:
            continue
        if str(meta.get("campaign_target_agent_type") or meta.get("agent_type") or "").strip() != AGENT_TYPE:
            continue
        if str(meta.get("copy_contract", "")).strip() != "evidence_personalized_v13_5":
            continue
        if str(meta.get("qualification_tier", "")).strip().upper() != "A":
            continue
        anchor = str(meta.get("personalization_anchor", "")).strip()
        fact = str(meta.get("fact", "")).strip()
        value = str(meta.get("value_asset_summary", "")).strip()
        if not anchor or not fact or not value:
            continue
        company = str(row.get("company", "")).strip()
        company_key = company.casefold()
        copy_key = (fact.casefold(), value.casefold())
        if not company or company_key in seen_companies or copy_key in seen_copy:
            continue

        subject = str(row.get("subject", "")).strip()
        body = str(row.get("body", "")).strip()
        if BANNED_SUBJECT_RE.search(subject):
            continue
        body_lower = body.casefold()
        if any(term in body_lower for term in BANNED_BODY_TERMS):
            continue
        if "@" not in str(row.get("email", "")):
            continue
        if any(str(row.get(field, "")).strip() for field in TERMINAL_FIELDS):
            continue
        recipient = str(row.get("email", "")).strip().lower()
        if recipient in suppressed_emails or domain_of(recipient) in suppressed_domains:
            continue

        try:
            score = int(str(meta.get("customer_potential", "0")))
        except ValueError:
            score = 0
        candidates.append((score, lead_id, row))
        seen_companies.add(company_key)
        seen_copy.add(copy_key)

    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [row for _score, _lead_id, row in candidates]


def count_ready(service, baseline_ids: set[str]) -> int:
    count = len(selected_rows(service, baseline_ids))
    print(f"NEW_PERSONALIZED_READY={count}", flush=True)
    return count


def discovery_wave(wave: int) -> None:
    common = {
        "OUTREACH_SPREADSHEET_ID": SPREADSHEET_ID,
        "GOOGLE_SERVICE_ACCOUNT_JSON": os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"],
    }
    run_script(
        "prospect_discovery_runtime.py",
        "--mode",
        "discover",
        "--report",
        f"prospect-discovery-wave-{wave}.json",
        extra_env={
            **common,
            "PROSPECT_DISCOVERY_MODE": "discover",
            "PROSPECT_DISCOVERY_MAX_TOTAL": "200",
            "PROSPECT_DISCOVERY_TARGET_NEW": "150",
            "PROSPECT_DISCOVERY_TIMEOUT_SECONDS": os.getenv("PROSPECT_DISCOVERY_TIMEOUT_SECONDS", "10"),
            "PROSPECT_DISCOVERY_MAX_BYTES": os.getenv("PROSPECT_DISCOVERY_MAX_BYTES", "2097152"),
            "PROSPECT_DISCOVERY_MIN_INTERVAL_SECONDS": os.getenv("PROSPECT_DISCOVERY_MIN_INTERVAL_SECONDS", "0.5"),
            "PROSPECT_DISCOVERY_USER_AGENT": os.getenv("PROSPECT_DISCOVERY_USER_AGENT", ""),
            "PROSPECT_DISCOVERY_EXCLUDE_COUNTRIES": "NL,DE,BE,GB,UK,FR,ES,IT,SE,DK,NO,FI,AT,CH,IE,PT,PL,CZ",
            "PROSPECT_DISCOVERY_PREFERRED_COUNTRIES": "US",
            "PROSPECT_DISCOVERY_EXCLUDE_AGENCIES": "true",
            "PROSPECT_DISCOVERY_EXTRA_EXCLUDE_TERMS": os.getenv("PROSPECT_DISCOVERY_EXTRA_EXCLUDE_TERMS", ""),
        },
    )
    run_script(
        "prospect_candidate_sanitizer.py",
        extra_env={
            **common,
            "PROSPECT_QUALIFICATION_TIMEOUT_SECONDS": os.getenv("PROSPECT_QUALIFICATION_TIMEOUT_SECONDS", "10"),
            "PROSPECT_QUALIFICATION_MAX_BYTES": os.getenv("PROSPECT_QUALIFICATION_MAX_BYTES", "524288"),
            "PROSPECT_QUALIFICATION_MIN_INTERVAL_SECONDS": os.getenv("PROSPECT_QUALIFICATION_MIN_INTERVAL_SECONDS", "0.5"),
            "PROSPECT_QUALIFICATION_USER_AGENT": os.getenv("PROSPECT_QUALIFICATION_USER_AGENT", ""),
        },
    )
    run_script(
        "prospect_signal_discovery_runtime.py",
        "--mode",
        "discover",
        "--report",
        f"prospect-signal-wave-{wave}.json",
        extra_env={
            **common,
            "PROSPECT_SIGNAL_MODE": "discover",
            "PROSPECT_SIGNAL_MAX_CANDIDATES": "25",
            "PROSPECT_SIGNAL_TIMEOUT_SECONDS": os.getenv("PROSPECT_SIGNAL_TIMEOUT_SECONDS", "10"),
            "PROSPECT_SIGNAL_MAX_BYTES": os.getenv("PROSPECT_SIGNAL_MAX_BYTES", "524288"),
            "PROSPECT_SIGNAL_MIN_INTERVAL_SECONDS": os.getenv("PROSPECT_SIGNAL_MIN_INTERVAL_SECONDS", "0.5"),
            "PROSPECT_SIGNAL_USER_AGENT": os.getenv("PROSPECT_SIGNAL_USER_AGENT", ""),
        },
    )


def qualification_pass(wave: int, pass_no: int) -> None:
    common = {
        "OUTREACH_SPREADSHEET_ID": SPREADSHEET_ID,
        "GOOGLE_SERVICE_ACCOUNT_JSON": os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"],
        "AGENT_SALES_TARGET_TYPE": AGENT_TYPE,
        "AGENT_SALES_FIRST_PARTY_REACTIVATION": "false",
    }
    run_script(
        "prospect_agent_qualification.py",
        "--mode",
        "qualify",
        "--report",
        f"agent-qualification-w{wave}-p{pass_no}.json",
        extra_env={
            **common,
            "PROSPECT_QUALIFICATION_MODE": "qualify",
            "PROSPECT_QUALIFICATION_FORCE_RECHECK": "false",
            "PROSPECT_QUALIFICATION_RECHECK_DAYS": "30",
            "PROSPECT_QUALIFICATION_MAX_PER_RUN": "25",
            "PROSPECT_QUALIFICATION_TIMEOUT_SECONDS": os.getenv("PROSPECT_QUALIFICATION_TIMEOUT_SECONDS", "10"),
            "PROSPECT_QUALIFICATION_MAX_BYTES": os.getenv("PROSPECT_QUALIFICATION_MAX_BYTES", "524288"),
            "PROSPECT_QUALIFICATION_MIN_INTERVAL_SECONDS": os.getenv("PROSPECT_QUALIFICATION_MIN_INTERVAL_SECONDS", "0.5"),
            "PROSPECT_QUALIFICATION_USER_AGENT": os.getenv("PROSPECT_QUALIFICATION_USER_AGENT", ""),
        },
    )
    run_script(
        "prospect_campaign_gate.py",
        "--mode",
        "audit",
        "--report",
        f"campaign-gate-w{wave}-p{pass_no}.json",
        extra_env={**common, "AGENT_SALES_CAMPAIGN_GATE_MODE": "audit"},
    )
    run_script(
        "prospect_contact_enrichment_campaign.py",
        extra_env={
            **common,
            "CONTACT_ENRICHMENT_MODE": "discover",
            "CONTACT_ENRICHMENT_MAX_PER_RUN": "25",
            "CONTACT_ENRICHMENT_MIN_INTERVAL": os.getenv("CONTACT_ENRICHMENT_MIN_INTERVAL", "0.5"),
            "CONTACT_ENRICHMENT_TIMEOUT": os.getenv("CONTACT_ENRICHMENT_TIMEOUT", "10"),
        },
    )
    run_script(
        "outreach_agent_prepare_v2.py",
        "--mode",
        "prepare",
        "--report",
        f"agent-prepare-w{wave}-p{pass_no}.json",
        extra_env={
            **common,
            "OUTREACH_PREPARE_MODE": "prepare",
            "OUTREACH_CTA_VARIANT": "A",
            "OUTREACH_PREPARE_MAX_PER_RUN": "25",
            "OUTREACH_MAILBOX_ID": os.getenv("OUTREACH_MAILBOX_ID", "primary"),
            "OUTREACH_SENDER_EMAIL": os.getenv("OUTREACH_SENDER_EMAIL", "info@andrewbaeten.nl"),
        },
    )


def create_review_drafts(service, rows: list[dict[str, str]]) -> list[dict[str, str | int]]:
    suppressed_emails, suppressed_domains = suppression_sets(
        get_values(service, SPREADSHEET_ID, SUPPRESSION_SHEET)
    )
    daily_limit = int(os.getenv("OUTREACH_DAILY_LIMIT", "20") or "20")
    mailboxes = enabled_mailboxes(load_mailboxes_from_env(mode="validate", default_daily_limit=daily_limit))
    mailbox = choose_mailbox(mailboxes, os.getenv("OUTREACH_DRAFT_MAILBOX_ID", "primary"))
    receipts: list[dict[str, str | int]] = []

    for index, row in enumerate(rows[:TARGET], start=1):
        errors = review_draft_errors(
            row,
            sender_email=mailbox.sender_email,
            suppressed_emails=suppressed_emails,
            suppressed_domains=suppressed_domains,
        )
        if errors:
            raise RuntimeError(f"review draft blocked for {row.get('lead_id')}: {'; '.join(errors)}")
        body = inject_private_postal_for_draft(row, row["body"])
        digest = hashlib.sha256(str(row["lead_id"]).encode("utf-8")).hexdigest()[:18]
        test_id = f"leads50-20260909-{digest}"
        receipt = append_verified_draft(
            mailbox,
            recipient=row["email"],
            subject=row["subject"],
            body=body,
            test_id=test_id,
            explicit_folder=os.getenv("OUTREACH_DRAFT_FOLDER", ""),
            self_only=False,
            retries=3,
            delay_seconds=1.0,
        )
        receipts.append(
            {
                "lead_id": row["lead_id"],
                "company": row["company"],
                "email": row["email"],
                "subject": row["subject"],
                "test_id": test_id,
                "folder": receipt.folder,
                "readback_count": len(receipt.message_ids),
                "compliance_status": row.get("compliance_status", ""),
                "queue_status": row.get("status", ""),
            }
        )
        print(
            f"MYHOST_REVIEW_DRAFT=green index={index} lead_id={row['lead_id']} folder={receipt.folder} smtp_send=not_invoked",
            flush=True,
        )
    return receipts


def main() -> int:
    if not SPREADSHEET_ID:
        raise RuntimeError("OUTREACH_SPREADSHEET_ID is required")
    if not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is required")
    if not os.getenv("OUTREACH_MAIL_PASSWORD", "").strip():
        raise RuntimeError("OUTREACH_MAIL_PASSWORD is required")
    if not os.getenv("OUTREACH_POSTAL_ADDRESS", "").strip():
        raise RuntimeError("OUTREACH_POSTAL_ADDRESS is required for US review drafts")

    service = build_sheets_service()
    baseline_ids = {
        str(row.get("lead_id", "")).strip()
        for row in queue_rows(service)
        if str(row.get("lead_id", "")).strip()
    }
    print(f"BASELINE_QUEUE_IDS={len(baseline_ids)}", flush=True)

    ready = 0
    for wave in range(1, MAX_DISCOVERY_WAVES + 1):
        discovery_wave(wave)
        for pass_no in range(1, QUALIFICATION_PASSES_PER_WAVE + 1):
            qualification_pass(wave, pass_no)
            ready = count_ready(service, baseline_ids)
            if ready >= TARGET:
                break
        if ready >= TARGET:
            break

    rows = selected_rows(service, baseline_ids)
    if len(rows) < TARGET:
        raise RuntimeError(f"only {len(rows)} new personalized draft-ready rows after bounded campaign; target={TARGET}")

    chosen = rows[:TARGET]
    chosen_payload = []
    for row in chosen:
        meta = parse_agent_source(row.get("source", ""))
        chosen_payload.append(
            {
                "lead_id": row.get("lead_id", ""),
                "company": row.get("company", ""),
                "website": row.get("website", ""),
                "email": row.get("email", ""),
                "subject": row.get("subject", ""),
                "personalization_anchor": meta.get("personalization_anchor", ""),
                "fact": meta.get("fact", ""),
                "value_asset_summary": meta.get("value_asset_summary", ""),
                "customer_potential": meta.get("customer_potential", ""),
                "queue_status": row.get("status", ""),
                "compliance_status": row.get("compliance_status", ""),
            }
        )
    Path("selected-50-leads.json").write_text(json.dumps(chosen_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    receipts = create_review_drafts(service, chosen)
    Path("draft-receipts.json").write_text(json.dumps(receipts, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"LEADS50_RESULT=green selected={len(chosen)} drafts={len(receipts)} smtp_send=not_invoked", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
