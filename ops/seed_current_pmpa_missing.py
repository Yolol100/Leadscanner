from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from prospect_discovery import BoundedHttpClient, CANDIDATE_HEADERS, LEAD_HEADERS, host_key, parse_page, root_url, rows_to_dicts
from prospect_discovery_runtime import append_rows, get_values, load_google_service
from outreach_sender import rows_from_values

SPREADSHEET_ID = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
SOURCES = {
    "us-pmpa-contract-manufacturers": "https://www.pmpa.org/forms/MemberDirectory/search?action=find",
    "us-pmpa-contract-manufacturers-page2": "https://www.pmpa.org/forms/MemberDirectory/search?PCursorEnd=100&PCursorStart=1&action=find",
}
NON_MEMBER_HOSTS = {
    "pmpa.org", "connectedcommunity.org", "calendly.com", "pmts.com",
    "facebook.com", "twitter.com", "x.com", "linkedin.com", "instagram.com", "youtube.com",
    "batteriesplus.com", "appienergy.com", "federatedinsurance.com", "grainger.com", "partnership.com",
}
NON_MEMBER_LABELS = {
    "facebook", "twitter", "linkedin", "instagram", "youtube", "schedule a benefits overview",
    "member directory", "find-a-supplier", "batteries plus", "federated insurance", "grainger", "partnership",
}
NON_US_COMPANIES = {
    "a. berger precision ltd.", "l&m precision products inc.", "collison-goll limited",
    "s&e manufacturing", "pleasant manufacturing co. limited", "price screw machine products ltd.",
}


def norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def candidate_id(domain: str) -> str:
    return "prospect-pmpa-" + hashlib.sha256(domain.encode("utf-8")).hexdigest()[:20]


def host_excluded(host: str) -> bool:
    return any(host == blocked or host.endswith("." + blocked) for blocked in NON_MEMBER_HOSTS)


def main() -> int:
    if not SPREADSHEET_ID:
        raise RuntimeError("OUTREACH_SPREADSHEET_ID is required")
    service = load_google_service()

    source_values = get_values(service, SPREADSHEET_ID, "'ProspectSources'!A:I")
    source_headers = [str(v).strip() for v in source_values[0]] if source_values else []
    source_rows = []
    for raw in source_values[1:]:
        padded = list(raw) + [""] * max(0, len(source_headers) - len(raw))
        source_rows.append({source_headers[i]: str(padded[i] or "") for i in range(len(source_headers))})
    approved = {
        row.get("source_id", "").strip(): row
        for row in source_rows
        if str(row.get("approved", "")).strip().casefold() in {"true", "1", "yes"}
        and str(row.get("enabled", "")).strip().casefold() in {"true", "1", "yes"}
    }
    for source_id, source_url in SOURCES.items():
        row = approved.get(source_id)
        if not row or row.get("source_url", "").strip() != source_url:
            raise RuntimeError(f"approved Project Leads source mismatch: {source_id}")

    candidates = rows_to_dicts(get_values(service, SPREADSHEET_ID, "'ProspectCandidates'!A:K"), CANDIDATE_HEADERS)
    leads = rows_to_dicts(get_values(service, SPREADSHEET_ID, "'Leadlijst'!A:D"), LEAD_HEADERS)
    _queue_headers, queue = rows_from_values(get_values(service, SPREADSHEET_ID, "'OutreachQueue'!A:AC"))
    known_domains = {
        domain for row in candidates if (domain := host_key(str(row.get("website") or "")))
    }
    known_domains.update(
        domain for row in leads if (domain := host_key(str(row.get("Website") or row.get("website") or "")))
    )
    known_domains.update(
        domain for row in queue if (domain := host_key(str(row.get("website") or "")))
    )

    client = BoundedHttpClient(
        user_agent="WebactueelPMPASeed/1.0 (+https://andrewbaeten.nl)",
        timeout=12.0,
        max_bytes=2_097_152,
        min_interval=0.5,
    )
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    output_rows = []
    skipped = []

    for source_id, source_url in SOURCES.items():
        html = client.fetch_text(source_url)
        page = parse_page(html, source_url)
        for href, label in page.links:
            company = norm(label)
            website = root_url(href)
            domain = host_key(website)
            label_key = company.casefold()
            if not company or not domain:
                continue
            if host_excluded(domain) or label_key in NON_MEMBER_LABELS:
                continue
            if label_key in NON_US_COMPANIES:
                skipped.append({"company": company, "website": website, "reason": "non_us_member"})
                continue
            if domain in known_domains:
                continue
            # Company labels on the PMPA result pages are the member names. Reject generic navigation labels.
            if label_key in {"home", "about", "contact us", "login", "join/renew", "news", "careers", "new search", "previous", "next"}:
                continue
            output_rows.append([
                candidate_id(domain),
                now,
                company,
                website,
                source_url,
                source_id,
                "directory_page",
                "US",
                "pmpa_member;direct_official_company_link",
                "discovered",
                "current approved PMPA member directory direct company link; no qualification, contact readiness or send permission implied",
            ])
            known_domains.add(domain)

    append_rows(service, SPREADSHEET_ID, "'ProspectCandidates'!A:K", output_rows)
    report = {
        "status": "completed",
        "seeded": len(output_rows),
        "skipped_non_us": len(skipped),
        "source_ids": list(SOURCES),
        "seeded_companies": [row[2] for row in output_rows],
        "send_permission": "none",
        "smtp_send": "not_invoked",
    }
    Path("seed-current-pmpa-missing.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PMPA_CURRENT_SEED=green seeded={len(output_rows)} non_us_skipped={len(skipped)} smtp_send=not_invoked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
