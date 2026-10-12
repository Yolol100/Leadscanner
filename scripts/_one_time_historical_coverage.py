"""ONE-TIME, read-only legacy suppression coverage inventory.

Removed after the historical check. No provider updates or durable prospect
data. Public output is limited to counters, never identities.
"""
from __future__ import annotations

from collections import Counter
import json
import os
import re
import sys

import requests

from leadscanner_core import fetch_registry
from dedupe_preflight import candidate_identity, domains_match

SOURCE_LIST = "24deb187-59e0-43b5-86b8-fe37a7b21e2a"
EXPECTED_SOURCE_COUNT = 1128
API_URL = "https://api.instantly.ai/api/v2/leads/list"


def run() -> dict:
    key = os.environ.get("INSTANTLY_API_KEY", "").strip()
    if not key or any(ch.isspace() for ch in key):
        raise RuntimeError("provider_secret_unavailable")
    registry = fetch_registry()
    if not registry:
        raise RuntimeError("empty_registry")
    counters = Counter()
    seen_lead_ids, seen_emails, seen_cursors = set(), set(), set()
    cursor = ""
    with requests.Session() as session:
        for _page in range(25):
            payload = {"list_id": SOURCE_LIST, "limit": 100}
            if cursor:
                payload["starting_after"] = cursor
            response = session.post(
                API_URL, json=payload,
                headers={"Authorization": "Bearer " + key,
                         "Accept": "application/json",
                         "Content-Type": "application/json"},
                timeout=25,
            )
            if response.status_code != 200:
                raise RuntimeError("provider_source_read_unavailable")
            result = response.json()
            if not isinstance(result, dict) or not isinstance(result.get("items"), list):
                raise RuntimeError("provider_source_page_invalid")
            for item in result["items"]:
                if not isinstance(item, dict) or item.get("list_id") != SOURCE_LIST:
                    raise RuntimeError("provider_source_identity_changed")
                email = str(item.get("email") or "").strip().casefold()
                lead_id = str(item.get("id") or "").strip().casefold()
                if (
                    not re.fullmatch(r"[0-9a-f-]{36}", lead_id)
                    or email.count("@") != 1 or lead_id in seen_lead_ids
                    or email in seen_emails
                ):
                    raise RuntimeError("provider_source_duplicates_or_invalid")
                seen_lead_ids.add(lead_id)
                seen_emails.add(email)
                fields = item.get("payload") if isinstance(item.get("payload"), dict) else {}
                website = str(item.get("website") or fields.get("website") or fields.get("leadscanner_site_refresh_official_domain") or "").strip()
                company = str(item.get("companyName") or item.get("company") or "").strip()
                source = candidate_identity({
                    "company": company, "website": website,
                    "email": email, "lead_id": lead_id,
                })
                match_email = match_domain = match_company = match_id = False
                for old in registry:
                    identity = old["identity"]
                    match_email |= bool(source["emails"] & identity["emails"])
                    match_id |= bool(source["lead_ids"] & identity["lead_ids"])
                    match_domain |= any(
                        domains_match(left, right)
                        for left in source["domains"]
                        for right in identity["domains"]
                    )
                    match_company |= bool(
                        source["company"]
                        and source["company"] == identity["company"]
                    )
                counters["source_total"] += 1
                counters["exact_email_matches"] += int(match_email)
                counters["official_domain_matches"] += int(match_domain)
                counters["company_name_matches"] += int(match_company)
                counters["lead_id_matches"] += int(match_id)
                if any((match_email, match_domain, match_company, match_id)):
                    counters["covered_by_exclusion"] += 1
                else:
                    counters["not_covered"] += 1
                    counters["uncovered_without_website"] += int(not source["domains"])
            next_cursor = str(result.get("next_starting_after") or "").strip()
            if not next_cursor:
                break
            if next_cursor == cursor or next_cursor in seen_cursors or not result["items"]:
                raise RuntimeError("provider_source_pagination_invalid")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        else:
            raise RuntimeError("provider_source_exceeded_page_bound")
    if counters["source_total"] != EXPECTED_SOURCE_COUNT:
        raise RuntimeError("provider_source_count_changed")
    if counters["source_total"] != counters["covered_by_exclusion"] + counters["not_covered"]:
        raise RuntimeError("provider_source_partition_inconsistent")
    return {
        "status": "fully_covered" if not counters["not_covered"] else "coverage_gap",
        "historical_source_total": counters["source_total"],
        "registered_exclusions": len(registry),
        "covered_by_exclusion": counters["covered_by_exclusion"],
        "not_covered": counters["not_covered"],
        "exact_email_matches": counters["exact_email_matches"],
        "official_domain_matches": counters["official_domain_matches"],
        "company_name_matches": counters["company_name_matches"],
        "lead_id_matches": counters["lead_id_matches"],
        "uncovered_without_website": counters["uncovered_without_website"],
        "provider_mutation": False,
        "registry_mutation": False,
        "emails_sent": 0,
        "contacts_disclosed": False,
    }


if __name__ == "__main__":
    try:
        report = run()
    except Exception:
        print("HISTORICAL_COVERAGE=failed private_details_suppressed")
        sys.exit(1)
    print("HISTORICAL_COVERAGE=" + report["status"] + " " + json.dumps(report, sort_keys=True))
