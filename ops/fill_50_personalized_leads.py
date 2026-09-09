from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "ops"
sys.path.insert(0, str(OPS))

from run_50_personalized_drafts import (  # noqa: E402
    SPREADSHEET_ID,
    build_sheets_service,
    discovery_wave,
    qualification_pass,
    selected_rows,
)

TARGET = 50
ORIGINAL_BASELINE_EXCLUSIONS = {"prospect-25d374063f3f069399d1"}
MAX_EXISTING_BACKLOG_PASSES = 12
MAX_POST_DISCOVERY_PASSES = 8


def current_rows(service):
    return selected_rows(service, ORIGINAL_BASELINE_EXCLUSIONS)


def write_selection(rows) -> None:
    payload = []
    for row in rows[:TARGET]:
        source = str(row.get("source", ""))
        meta = {}
        if source.startswith("agent_offer:"):
            try:
                meta = json.loads(source.split(":", 1)[1])
            except json.JSONDecodeError:
                meta = {}
        payload.append(
            {
                "lead_id": row.get("lead_id", ""),
                "company": row.get("company", ""),
                "website": row.get("website", ""),
                "email": row.get("email", ""),
                "subject": row.get("subject", ""),
                "body": row.get("body", ""),
                "country": row.get("country", ""),
                "verification_status": row.get("verification_status", ""),
                "queue_status": row.get("status", ""),
                "evidence_url": meta.get("evidence_url", ""),
                "personalization_anchor": meta.get("personalization_anchor", ""),
                "personalization_process_label": meta.get("personalization_process_label", ""),
                "fact": meta.get("fact", ""),
                "value_asset_summary": meta.get("value_asset_summary", ""),
                "customer_potential": meta.get("customer_potential", ""),
                "copy_contract": meta.get("copy_contract", ""),
            }
        )
    Path("selected-50-leads.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    if not SPREADSHEET_ID:
        raise RuntimeError("OUTREACH_SPREADSHEET_ID is required")
    if not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is required")

    service = build_sheets_service()
    rows = current_rows(service)
    print(f"RESUME_PERSONALIZED_READY={len(rows)}", flush=True)

    for pass_no in range(1, MAX_EXISTING_BACKLOG_PASSES + 1):
        if len(rows) >= TARGET:
            break
        qualification_pass(50, pass_no)
        rows = current_rows(service)
        print(f"RESUME_PERSONALIZED_READY={len(rows)} pass={pass_no}", flush=True)

    if len(rows) < TARGET:
        print("RESUME_DISCOVERY=needed", flush=True)
        discovery_wave(50)
        for pass_no in range(1, MAX_POST_DISCOVERY_PASSES + 1):
            if len(rows) >= TARGET:
                break
            qualification_pass(51, pass_no)
            rows = current_rows(service)
            print(f"RESUME_PERSONALIZED_READY={len(rows)} discovery_pass={pass_no}", flush=True)

    if len(rows) < TARGET:
        write_selection(rows)
        print(f"LEADS50_PREP=blocked ready={len(rows)} target={TARGET}", flush=True)
        return 2

    write_selection(rows[:TARGET])
    print("LEADS50_PREP=green selected=50 smtp_send=not_invoked imap_draft=not_invoked", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
