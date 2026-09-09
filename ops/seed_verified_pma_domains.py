from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from scripts.prospect_discovery import CANDIDATE_HEADERS, LEAD_HEADERS, host_key, rows_to_dicts
from scripts.prospect_discovery_runtime import append_rows, get_values, load_google_service
from scripts.outreach_sender import rows_from_values

SPREADSHEET_ID = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
CANDIDATE_SHEET = "ProspectCandidates"
QUEUE_SHEET = "OutreachQueue"

CLEVELAND_SOURCE_ID = "us-pma-cleveland-members"
CLEVELAND_SOURCE_URL = "https://www.pma.org/districts/cleveland/member-list/"
LONE_STAR_SOURCE_ID = "us-pma-lone-star-members"
LONE_STAR_SOURCE_URL = "https://www.pma.org/districts/lone-star/member-list/"

SEEDS = [
    ("A.J. Rose Manufacturing Co.", "https://ajrose.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("AccuTrex Products, Inc.", "https://www.accutrex.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Ace Wire Spring & Form Co., Inc.", "https://www.acewirespring.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("American Punch Co.", "https://www.americanpunchco.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("AML Industries Inc", "https://amlube.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Anchor Manufacturing Group, Inc.", "https://www.anchor-mfg.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("ArtiFlex Manufacturing, LLC", "https://artiflexmfg.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Atlantic Tool & Die Company", "https://www.atlantictool.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Automation Tool & Die, Inc.", "https://www.automationtd.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Compco", "https://compco.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Destiny Manufacturing", "https://www.destinymfg.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Diamond Wire Spring Co.", "https://diamondwire.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Die Co., Inc.", "https://diecoinc.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Eberhard Manufacturing Company", "https://www.eberhard.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Exact Tool & Die, Inc.", "https://www.exact-tool.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Fastfeed Corporation", "https://fastfeedcorporation.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Ferragon Specialty Steel", "https://ferragonspecialtysteel.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Hynes Industries", "https://www.hynesindustries.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Interlake Stamping of Ohio Inc.", "http://www.interlakestamping.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Morrison Products, Inc.", "https://morrisonproducts.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Oberg Industries, LLC", "https://www.oberg.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("OGS Industries", "https://www.ogsindustries.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Ohio Fabricators Company", "https://ohfab.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Penn United Technologies, Inc.", "https://www.pennunited.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Phoenix Steel Service, Inc.", "https://phoenixsteelservice.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Precision Metal Products, Inc.", "https://www.pmpstamping.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Progressive Machine Die, Inc.", "https://pmd-inc.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Regal Metal Products Co.", "https://www.regalmetalproducts.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Solon Manufacturing Co", "https://www.solonmfg.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Stripmatic Products, Inc.", "https://stripmatic.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Talan Products Inc.", "https://www.talanproducts.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("TuscoMFG", "https://www.tuscomfg.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Weiss Industries, Inc.", "https://www.weissind.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Com-Corp Industries", "https://www.ccioh.com/", CLEVELAND_SOURCE_ID, CLEVELAND_SOURCE_URL),
    ("Dayton Rogers Manufacturing Co.", "https://daytonrogers.com/", LONE_STAR_SOURCE_ID, LONE_STAR_SOURCE_URL),
    ("Fasteel", "https://fasteelmrs.com/", LONE_STAR_SOURCE_ID, LONE_STAR_SOURCE_URL),
    ("ITD Precision", "https://www.itdprecision.com/", LONE_STAR_SOURCE_ID, LONE_STAR_SOURCE_URL),
    ("Micro Forms, Inc.", "https://mforms.com/", LONE_STAR_SOURCE_ID, LONE_STAR_SOURCE_URL),
    ("Quick-Way Manufacturing, Inc.", "https://www.quick-way.com/", LONE_STAR_SOURCE_ID, LONE_STAR_SOURCE_URL),
    ("Wrico Stamping of Texas", "https://www.wrico-net.com/", LONE_STAR_SOURCE_ID, LONE_STAR_SOURCE_URL),
]


def candidate_id(domain: str) -> str:
    return "prospect-pma-" + hashlib.sha256(domain.encode("utf-8")).hexdigest()[:20]


def main() -> int:
    if not SPREADSHEET_ID:
        raise RuntimeError("OUTREACH_SPREADSHEET_ID is required")
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
    for company, website, source_id, source_url in SEEDS:
        domain = host_key(website)
        if not domain or domain in known_domains:
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
        "source_ids": [CLEVELAND_SOURCE_ID, LONE_STAR_SOURCE_ID],
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
