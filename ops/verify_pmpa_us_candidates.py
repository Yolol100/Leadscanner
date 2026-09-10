from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from prospect_discovery import BoundedHttpClient, CANDIDATE_HEADERS, DiscoveryError, host_key, parse_page, rows_to_dicts
from prospect_discovery_runtime import get_values, load_google_service

SPREADSHEET_ID = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
PMPA_SOURCE_IDS = {
    "us-pmpa-contract-manufacturers",
    "us-pmpa-contract-manufacturers-page2",
}
DETAIL_HINTS = ("contact", "location", "locations", "facility", "facilities", "about")
US_STATE_ABBRS = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
    "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY",
    "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
)
US_STATE_NAMES = (
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware", "Florida",
    "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine",
    "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio", "Oklahoma",
    "Oregon", "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah",
    "Vermont", "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming", "District of Columbia",
)
US_ABBR_ZIP_RE = re.compile(r"(?:,\s*|\s)(?:" + "|".join(US_STATE_ABBRS) + r")\s+\d{5}(?:-\d{4})?\b")
US_NAME_ZIP_RE = re.compile(r"\b(?:" + "|".join(re.escape(name) for name in US_STATE_NAMES) + r")\s+\d{5}(?:-\d{4})?\b", re.I)
CANADA_POSTAL_RE = re.compile(r"\b[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z]\s?\d[ABCEGHJ-NPRSTV-Z]\d\b", re.I)
CANADA_RE = re.compile(r"\b(?:Canada|Ontario|Quebec|Québec|Alberta|Manitoba|Saskatchewan|Nova Scotia|New Brunswick|British Columbia|Prince Edward Island|Newfoundland(?: and Labrador)?)\b", re.I)
OTHER_COUNTRY_RE = re.compile(r"\b(?:Mexico|United Kingdom|England|Scotland|Wales|Germany|France|Italy|Spain|Switzerland|Netherlands|Belgium|Poland|Czech Republic|Czechia|Sweden|Denmark|Norway|Finland|Austria)\b", re.I)


def text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def detail_url(page, website: str) -> str:
    root_host = host_key(website)
    ranked = []
    for index, (href, label) in enumerate(page.links[:250]):
        if host_key(href) != root_host:
            continue
        parsed = urlparse(href)
        haystack = f"{parsed.path} {label}".casefold()
        score = sum(2 if hint in text(label).casefold() else 1 for hint in DETAIL_HINTS if hint in haystack)
        if score and parsed.path not in {"", "/"}:
            ranked.append((-score, index, href.split("#", 1)[0]))
    ranked.sort()
    return ranked[0][2] if ranked else ""


def classify_location(visible_text: str) -> tuple[str, str]:
    value = text(visible_text)
    if US_ABBR_ZIP_RE.search(value) or US_NAME_ZIP_RE.search(value):
        return "US", "official_site_us_postal_address"
    if CANADA_POSTAL_RE.search(value) or CANADA_RE.search(value):
        return "CA", "official_site_canada_location"
    if OTHER_COUNTRY_RE.search(value):
        return "NON_US", "official_site_non_us_location"
    return "UNVERIFIED", "no_official_us_postal_evidence"


def append_term(raw: object, term: str) -> str:
    items = [piece.strip() for piece in str(raw or "").split(";") if piece.strip()]
    if term not in items:
        items.append(term)
    return ";".join(items)


def replace_candidates(service, rows) -> None:
    values = [CANDIDATE_HEADERS] + [[str(row.get(header, "")) for header in CANDIDATE_HEADERS] for row in rows]
    service.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID, range="'ProspectCandidates'!A:K", body={}
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range="'ProspectCandidates'!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="pmpa-country-verification.json")
    args = parser.parse_args()
    if not SPREADSHEET_ID or not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("Sheet runtime configuration is required")

    service = load_google_service()
    candidates = rows_to_dicts(get_values(service, SPREADSHEET_ID, "'ProspectCandidates'!A:K"), CANDIDATE_HEADERS)
    client = BoundedHttpClient(
        user_agent="WebactueelPMPACountryVerify/1.0 (+https://andrewbaeten.nl)",
        timeout=8.0,
        max_bytes=524288,
        min_interval=0.25,
    )
    counts = {"verified_us": 0, "canada": 0, "other_non_us": 0, "unverified": 0, "fetch_error": 0}
    samples = {key: [] for key in counts}
    changed = 0

    for row in candidates:
        if text(row.get("source_id")) not in PMPA_SOURCE_IDS or not text(row.get("candidate_id")).startswith("prospect-pmpa-"):
            continue
        company = text(row.get("company"))
        website = text(row.get("website"))
        try:
            homepage_html = client.fetch_text(website)
            homepage = parse_page(homepage_html, website)
            visible = homepage.text
            target = detail_url(homepage, website)
            if target:
                try:
                    visible += " " + parse_page(client.fetch_text(target), target).text
                except (DiscoveryError, OSError, ValueError):
                    pass
            country, reason = classify_location(visible)
        except (DiscoveryError, OSError, ValueError):
            country, reason = "UNVERIFIED", "official_site_location_fetch_failed"
            counts["fetch_error"] += 1
            if len(samples["fetch_error"]) < 10:
                samples["fetch_error"].append(company)

        before = (text(row.get("country")), text(row.get("status")), text(row.get("reason")), text(row.get("matched_terms")))
        if country == "US":
            counts["verified_us"] += 1
            if len(samples["verified_us"]) < 10:
                samples["verified_us"].append(company)
            row["country"] = "US"
            row["matched_terms"] = append_term(row.get("matched_terms"), "official_site_us_location_verified")
            if text(row.get("status")).casefold() == "hold" and text(row.get("reason")).startswith("country_verification:"):
                row["status"] = "discovered"
            row["reason"] = "country_verification: official-site US postal evidence; qualification/contact/send permission still required"
        elif country == "CA":
            counts["canada"] += 1
            if len(samples["canada"]) < 10:
                samples["canada"].append(company)
            row["country"] = "CA"
            row["status"] = "rejected"
            row["reason"] = f"country_verification: {reason}; excluded from US campaign"
            row["matched_terms"] = append_term(row.get("matched_terms"), "country_non_us")
        elif country == "NON_US":
            counts["other_non_us"] += 1
            if len(samples["other_non_us"]) < 10:
                samples["other_non_us"].append(company)
            row["country"] = "NON_US"
            row["status"] = "rejected"
            row["reason"] = f"country_verification: {reason}; excluded from US campaign"
            row["matched_terms"] = append_term(row.get("matched_terms"), "country_non_us")
        else:
            counts["unverified"] += 1
            if len(samples["unverified"]) < 10:
                samples["unverified"].append(company)
            row["country"] = "UNVERIFIED"
            row["status"] = "hold"
            row["reason"] = f"country_verification: {reason}; no US campaign eligibility"
            row["matched_terms"] = append_term(row.get("matched_terms"), "country_unverified")
        after = (text(row.get("country")), text(row.get("status")), text(row.get("reason")), text(row.get("matched_terms")))
        if after != before:
            changed += 1

    replace_candidates(service, candidates)
    report = {
        "status": "completed",
        "checked": counts["verified_us"] + counts["canada"] + counts["other_non_us"] + counts["unverified"],
        "changed": changed,
        "counts": counts,
        "samples": samples,
        "campaign_country": "US",
        "rule": "official-site US postal evidence required for PMPA candidates",
        "send_permission": "none",
        "smtp_send": "not_invoked",
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "PMPA_COUNTRY_VERIFY=green "
        f"verified_us={counts['verified_us']} canada={counts['canada']} other_non_us={counts['other_non_us']} "
        f"unverified={counts['unverified']} fetch_error={counts['fetch_error']} smtp_send=not_invoked",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
