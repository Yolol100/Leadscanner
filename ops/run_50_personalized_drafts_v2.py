from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
OPS = ROOT / "ops"
sys.path.insert(0, str(SCRIPTS))

from outreach_imap_draft import append_verified_draft, choose_mailbox
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
from prospect_discovery import host_key

TARGET = 50
AGENT_TYPE = "quote_intake"
SPREADSHEET_ID = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
PRETASK_LEAD_COUNT = 175
TASK_DISCOVERY_START = "2026-09-09T20:04:53Z"
PREFERRED_COUNTRIES = "US,NL,DE,GB,UK"
MAX_EXISTING_QUAL_PASSES = 18
MAX_CONTACT_PASSES = 18
MAX_PREPARE_PASSES = 18
MAX_DISCOVERY_WAVES = 3

BANNED_BODY_TERMS = (
    "bounded digital agents",
    "human handoff where needed",
    "orchestration",
    "agentic",
    "ai-powered",
    "one concrete example flow",
)


def run_script(script: str, *args: str, extra_env: dict[str, str] | None = None) -> None:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    cmd_path = OPS / script if script.startswith("ops:") else SCRIPTS / script
    if script.startswith("ops:"):
        cmd_path = OPS / script.split(":", 1)[1]
    cmd = [sys.executable, str(cmd_path), *args]
    print("RUN", cmd_path.name, " ".join(args), flush=True)
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def rows(sheet: str) -> list[dict[str, str]]:
    service = build_sheets_service()
    _headers, data = rows_from_values(get_values(service, SPREADSHEET_ID, sheet))
    return [{str(k): str(v or "") for k, v in row.items()} for row in data]


def parse_agent_source(source: str) -> dict:
    if not str(source or "").startswith("agent_offer:"):
        return {}
    try:
        payload = json.loads(str(source).split(":", 1)[1])
    except (ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def task_new_domains() -> set[str]:
    lead_values = get_values(build_sheets_service(), SPREADSHEET_ID, "Leadlijst")
    if not lead_values:
        return set()
    data = lead_values[1:]
    task_rows = data[PRETASK_LEAD_COUNT:]
    output: set[str] = set()
    for row in task_rows:
        website = str(row[1] if len(row) > 1 else "").strip()
        domain = host_key(website)
        if domain:
            output.add(domain)
    return output


def selected_rows() -> list[dict[str, str]]:
    service = build_sheets_service()
    _headers, queue = rows_from_values(get_values(service, SPREADSHEET_ID, QUEUE_SHEET))
    suppressed_emails, suppressed_domains = suppression_sets(
        get_values(service, SPREADSHEET_ID, SUPPRESSION_SHEET)
    )
    new_domains = task_new_domains()
    selected: list[tuple[int, str, dict[str, str]]] = []
    seen_domains: set[str] = set()
    seen_copy: set[tuple[str, str]] = set()

    for raw in queue:
        row = {str(k): str(v or "") for k, v in raw.items()}
        domain = host_key(row.get("website", ""))
        if not domain or domain not in new_domains or domain in seen_domains:
            continue
        if row.get("status", "").strip().casefold() not in {"prepared", "manual_review", "approved"}:
            continue
        if row.get("verification_status", "").strip().casefold() != "official_site_ready":
            continue
        if any(row.get(field, "").strip() for field in TERMINAL_FIELDS):
            continue
        email = row.get("email", "").strip().casefold()
        email_domain = email.rsplit("@", 1)[1] if "@" in email else ""
        if not email or email in suppressed_emails or email_domain in suppressed_domains:
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
        body = row.get("body", "")
        subject = row.get("subject", "")
        lower = body.casefold()
        if any(term in lower for term in BANNED_BODY_TERMS):
            continue
        if any(token in subject.casefold().split() for token in {"ai", "automation", "bot", "roi"}):
            continue
        copy_key = (fact.casefold(), value.casefold())
        if copy_key in seen_copy:
            continue
        try:
            score = int(str(meta.get("customer_potential", "0")))
        except ValueError:
            score = 0
        selected.append((score, row.get("lead_id", ""), row))
        seen_domains.add(domain)
        seen_copy.add(copy_key)

    selected.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in selected]


def ready_count() -> int:
    count = len(selected_rows())
    print(f"TASK_DRAFT_READY={count}", flush=True)
    return count


def qualification_pass(label: str, *, discovered_after: str = "") -> int:
    report = f"qual-{label}.json"
    run_script(
        "ops:prospect_agent_qualification_filtered.py",
        "--mode",
        "qualify",
        "--report",
        report,
        extra_env={
            "OUTREACH_SPREADSHEET_ID": SPREADSHEET_ID,
            "GOOGLE_SERVICE_ACCOUNT_JSON": os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"],
            "AGENT_SALES_TARGET_TYPE": AGENT_TYPE,
            "AGENT_SALES_FIRST_PARTY_REACTIVATION": "false",
            "PROSPECT_QUALIFICATION_MAX_PER_RUN": "25",
            "PROSPECT_QUALIFICATION_RECHECK_DAYS": "30",
            "PROSPECT_QUALIFICATION_FORCE_RECHECK": "false",
            "PROSPECT_QUALIFICATION_TIMEOUT_SECONDS": os.getenv("PROSPECT_QUALIFICATION_TIMEOUT_SECONDS", "8"),
            "PROSPECT_QUALIFICATION_MAX_BYTES": os.getenv("PROSPECT_QUALIFICATION_MAX_BYTES", "524288"),
            "PROSPECT_QUALIFICATION_MIN_INTERVAL_SECONDS": os.getenv("PROSPECT_QUALIFICATION_MIN_INTERVAL_SECONDS", "0.25"),
            "PROSPECT_QUALIFICATION_USER_AGENT": os.getenv("PROSPECT_QUALIFICATION_USER_AGENT", ""),
            "TEMP_QUAL_COUNTRIES": PREFERRED_COUNTRIES,
            "TEMP_QUAL_DISCOVERED_AFTER": discovered_after,
        },
    )
    payload = json.loads(Path(report).read_text(encoding="utf-8"))
    return int(payload.get("assessed", 0) or 0)


def campaign_gate(label: str) -> None:
    run_script(
        "prospect_campaign_gate.py",
        "--mode",
        "audit",
        "--report",
        f"gate-{label}.json",
        extra_env={
            "OUTREACH_SPREADSHEET_ID": SPREADSHEET_ID,
            "GOOGLE_SERVICE_ACCOUNT_JSON": os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"],
            "AGENT_SALES_CAMPAIGN_GATE_MODE": "audit",
            "AGENT_SALES_TARGET_TYPE": AGENT_TYPE,
            "AGENT_SALES_FIRST_PARTY_REACTIVATION": "false",
        },
    )


def enrich_and_prepare(label: str) -> int:
    common = {
        "OUTREACH_SPREADSHEET_ID": SPREADSHEET_ID,
        "GOOGLE_SERVICE_ACCOUNT_JSON": os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"],
        "AGENT_SALES_TARGET_TYPE": AGENT_TYPE,
        "AGENT_SALES_FIRST_PARTY_REACTIVATION": "false",
    }
    for index in range(1, MAX_CONTACT_PASSES + 1):
        before = len(rows("ContactCandidates"))
        run_script(
            "prospect_contact_enrichment_campaign.py",
            extra_env={
                **common,
                "CONTACT_ENRICHMENT_MODE": "discover",
                "CONTACT_ENRICHMENT_MAX_PER_RUN": "25",
                "CONTACT_ENRICHMENT_MIN_INTERVAL": os.getenv("CONTACT_ENRICHMENT_MIN_INTERVAL", "0.25"),
                "CONTACT_ENRICHMENT_TIMEOUT": os.getenv("CONTACT_ENRICHMENT_TIMEOUT", "8"),
            },
        )
        after = len(rows("ContactCandidates"))
        print(f"CONTACT_PASS label={label} index={index} added={after-before}", flush=True)
        if after <= before:
            break

    previous = -1
    unchanged = 0
    for index in range(1, MAX_PREPARE_PASSES + 1):
        run_script(
            "outreach_agent_prepare_v2.py",
            "--mode",
            "prepare",
            "--report",
            f"prepare-{label}-{index}.json",
            extra_env={
                **common,
                "OUTREACH_PREPARE_MODE": "prepare",
                "OUTREACH_CTA_VARIANT": "A",
                "OUTREACH_PREPARE_MAX_PER_RUN": "25",
                "OUTREACH_MAILBOX_ID": os.getenv("OUTREACH_MAILBOX_ID", "primary"),
                "OUTREACH_SENDER_EMAIL": os.getenv("OUTREACH_SENDER_EMAIL", "info@andrewbaeten.nl"),
            },
        )
        current = ready_count()
        if current >= TARGET:
            return current
        if current == previous:
            unchanged += 1
        else:
            unchanged = 0
        previous = current
        if unchanged >= 1:
            break
    return ready_count()


def discover_wave(wave: int) -> str:
    from datetime import datetime, timezone
    started = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    run_script(
        "prospect_discovery_runtime.py",
        "--mode",
        "discover",
        "--report",
        f"discovery-v2-{wave}.json",
        extra_env={
            "OUTREACH_SPREADSHEET_ID": SPREADSHEET_ID,
            "GOOGLE_SERVICE_ACCOUNT_JSON": os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"],
            "PROSPECT_DISCOVERY_MODE": "discover",
            "PROSPECT_DISCOVERY_MAX_TOTAL": "200",
            "PROSPECT_DISCOVERY_TARGET_NEW": "150",
            "PROSPECT_DISCOVERY_TIMEOUT_SECONDS": os.getenv("PROSPECT_DISCOVERY_TIMEOUT_SECONDS", "8"),
            "PROSPECT_DISCOVERY_MAX_BYTES": os.getenv("PROSPECT_DISCOVERY_MAX_BYTES", "2097152"),
            "PROSPECT_DISCOVERY_MIN_INTERVAL_SECONDS": os.getenv("PROSPECT_DISCOVERY_MIN_INTERVAL_SECONDS", "0.25"),
            "PROSPECT_DISCOVERY_USER_AGENT": os.getenv("PROSPECT_DISCOVERY_USER_AGENT", ""),
            "PROSPECT_DISCOVERY_PREFERRED_COUNTRIES": PREFERRED_COUNTRIES,
            "PROSPECT_DISCOVERY_EXCLUDE_AGENCIES": "true",
        },
    )
    run_script(
        "prospect_candidate_sanitizer.py",
        extra_env={
            "OUTREACH_SPREADSHEET_ID": SPREADSHEET_ID,
            "GOOGLE_SERVICE_ACCOUNT_JSON": os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"],
            "PROSPECT_QUALIFICATION_TIMEOUT_SECONDS": "8",
            "PROSPECT_QUALIFICATION_MAX_BYTES": "524288",
            "PROSPECT_QUALIFICATION_MIN_INTERVAL_SECONDS": "0.25",
        },
    )
    return started


def build_drafts(rows_to_draft: list[dict[str, str]]) -> list[dict[str, object]]:
    daily_limit = int(os.getenv("OUTREACH_DAILY_LIMIT", "20") or "20")
    mailboxes = enabled_mailboxes(load_mailboxes_from_env(mode="validate", default_daily_limit=daily_limit))
    mailbox = choose_mailbox(mailboxes, os.getenv("OUTREACH_DRAFT_MAILBOX_ID", "primary"))
    service = build_sheets_service()
    suppressed_emails, suppressed_domains = suppression_sets(get_values(service, SPREADSHEET_ID, SUPPRESSION_SHEET))
    receipts: list[dict[str, object]] = []

    for index, row in enumerate(rows_to_draft[:TARGET], start=1):
        email = row.get("email", "").strip().casefold()
        domain = email.rsplit("@", 1)[1] if "@" in email else ""
        if not email or email in suppressed_emails or domain in suppressed_domains:
            raise RuntimeError(f"suppressed/invalid draft recipient for {row.get('lead_id')}")
        if any(row.get(field, "").strip() for field in TERMINAL_FIELDS):
            raise RuntimeError(f"terminal evidence blocks draft for {row.get('lead_id')}")
        body = inject_private_postal_for_draft(row, row.get("body", ""))
        digest = hashlib.sha256(row["lead_id"].encode("utf-8")).hexdigest()[:18]
        test_id = f"leads50-v2-20260909-{digest}"
        receipt = append_verified_draft(
            mailbox,
            recipient=email,
            subject=row.get("subject", ""),
            body=body,
            test_id=test_id,
            explicit_folder=os.getenv("OUTREACH_DRAFT_FOLDER", ""),
            self_only=False,
            retries=3,
            delay_seconds=1.0,
        )
        receipts.append({
            "lead_id": row.get("lead_id", ""),
            "company": row.get("company", ""),
            "website": row.get("website", ""),
            "email": email,
            "subject": row.get("subject", ""),
            "test_id": test_id,
            "folder": receipt.folder,
            "readback_count": len(receipt.message_ids),
        })
        print(f"MYHOST_REVIEW_DRAFT=green index={index} lead_id={row.get('lead_id')} folder={receipt.folder} smtp_send=not_invoked", flush=True)
    return receipts


def main() -> int:
    if not SPREADSHEET_ID:
        raise RuntimeError("OUTREACH_SPREADSHEET_ID is required")
    for name in ("GOOGLE_SERVICE_ACCOUNT_JSON", "OUTREACH_MAIL_PASSWORD"):
        if not os.getenv(name, "").strip():
            raise RuntimeError(f"{name} is required")
    if not os.getenv("OUTREACH_POSTAL_ADDRESS", "").strip():
        raise RuntimeError("OUTREACH_POSTAL_ADDRESS is required for US drafts")

    # Phase 1: finish the candidates discovered by this user-requested task first.
    for index in range(1, 4):
        assessed = qualification_pass(f"task-first-{index}", discovered_after=TASK_DISCOVERY_START)
        print(f"QUAL_TASK_FIRST pass={index} assessed={assessed}", flush=True)
        if assessed == 0:
            break
    campaign_gate("task-first")
    if enrich_and_prepare("task-first") >= TARGET:
        chosen = selected_rows()[:TARGET]
        Path("selected-50-leads-v2.json").write_text(json.dumps(chosen, indent=2, ensure_ascii=False), encoding="utf-8")
        receipts = build_drafts(chosen)
        Path("draft-receipts-v2.json").write_text(json.dumps(receipts, indent=2, ensure_ascii=False), encoding="utf-8")
        print("LEADS50_V2_RESULT=green selected=50 drafts=50 smtp_send=not_invoked", flush=True)
        return 0

    # Phase 2: exhaust still-unassessed candidates from the preferred markets before discovering more.
    for index in range(1, MAX_EXISTING_QUAL_PASSES + 1):
        assessed = qualification_pass(f"existing-{index}")
        print(f"QUAL_EXISTING pass={index} assessed={assessed}", flush=True)
        if assessed == 0:
            break
    campaign_gate("existing")
    if enrich_and_prepare("existing") >= TARGET:
        chosen = selected_rows()[:TARGET]
        Path("selected-50-leads-v2.json").write_text(json.dumps(chosen, indent=2, ensure_ascii=False), encoding="utf-8")
        receipts = build_drafts(chosen)
        Path("draft-receipts-v2.json").write_text(json.dumps(receipts, indent=2, ensure_ascii=False), encoding="utf-8")
        print("LEADS50_V2_RESULT=green selected=50 drafts=50 smtp_send=not_invoked", flush=True)
        return 0

    # Phase 3: bounded discovery waves only if the existing candidate pool was insufficient.
    for wave in range(1, MAX_DISCOVERY_WAVES + 1):
        started = discover_wave(wave)
        for index in range(1, 8):
            assessed = qualification_pass(f"wave-{wave}-{index}", discovered_after=started)
            print(f"QUAL_DISCOVERY wave={wave} pass={index} assessed={assessed}", flush=True)
            if assessed == 0:
                break
        campaign_gate(f"wave-{wave}")
        if enrich_and_prepare(f"wave-{wave}") >= TARGET:
            chosen = selected_rows()[:TARGET]
            Path("selected-50-leads-v2.json").write_text(json.dumps(chosen, indent=2, ensure_ascii=False), encoding="utf-8")
            receipts = build_drafts(chosen)
            Path("draft-receipts-v2.json").write_text(json.dumps(receipts, indent=2, ensure_ascii=False), encoding="utf-8")
            print("LEADS50_V2_RESULT=green selected=50 drafts=50 smtp_send=not_invoked", flush=True)
            return 0

    final = ready_count()
    raise RuntimeError(f"bounded campaign ended with {final} new personalized draft-ready leads; target={TARGET}")


if __name__ == "__main__":
    raise SystemExit(main())
