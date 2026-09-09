from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from prospect_discovery import CANDIDATE_HEADERS, LEAD_HEADERS, host_key, rows_to_dicts
from prospect_discovery_runtime import append_rows, get_values, load_google_service
from outreach_sender import rows_from_values

SPREADSHEET_ID = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
SEED_PATH = ROOT / "ops" / "pma_verified_seeds.json"


def candidate_id(domain: str) -> str:
    return "prospect-pma-" + hashlib.sha256(domain.encode("utf-8")).hexdigest()[:20]


def main() -> int:
    if not SPREADSHEET_ID:
        raise RuntimeError("OUTREACH_SPREADSHEET_ID is required")
    seeds = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    service = load_google_service()
    candidates = rows_to_dicts(get_values(service, SPREADSHEET_ID, "'ProspectCandidates'!A:K"), CANDIDATE_HEADERS)
    leads = rows_to_dicts(get_values(service, SPREADSHEET_ID, "'Leadlijst'!A:D"), LEAD_HEADERS)
    _queue_headers, queue = rows_from_values(get_values(service, SPREADSHEET_ID, "'OutreachQueue'!A:AC"))

    known_domains = {
        domain
        for row in candidates
        if (domain := host_key(str(row.get("website") or "")))
    }
    known_domains.update(
        domain
        for row in leads
        if (domain := host_key(str(row.get("Website") or row.get("website") or "")))
    )
    known_domains.update(
        domain
        for row in queue
        if (domain := host_key(str(row.get("website") or "")))
    )

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rows = []
    skipped = []
    for seed in seeds:
        company = str(seed.get("company") or "").strip()
        website = str(seed.get("website") or "").strip()
        source_id = str(seed.get("source_id") or "").strip()
        source_url = str(seed.get("source_url") or "").strip()
        domain = host_key(website)
        if not company or not domain or not source_id or not source_url:
            skipped.append({"company": company, "website": website, "reason": "invalid_seed"})
            continue
        if domain in known_domains:
            skipped.append({"company": company, "website": website, "reason": "domain_already_known"})
            continue
        rows.append([
            candidate_id(domain),
            now,
            company,
            website,
            source_url,
            source_id,
            "directory_page",
            "US",
            "pma_member;official_domain_web_verified",
            "discovered",
            "approved PMA member; official domain resolved from current public web evidence; no qualification or send permission implied",
        ])
        known_domains.add(domain)

    append_rows(service, SPREADSHEET_ID, "'ProspectCandidates'!A:K", rows)
    report = {
        "status": "completed",
        "seeded": len(rows),
        "skipped": len(skipped),
        "seeded_companies": [row[2] for row in rows],
        "skipped_items": skipped,
        "qualification": "not_granted",
        "contact_ready": "not_granted",
        "send_permission": "none",
        "smtp_send": "not_invoked",
    }
    Path("seed-verified-pma-domains.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PMA_DOMAIN_SEED=green seeded={len(rows)} skipped={len(skipped)} send_permission=none smtp_send=not_invoked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
