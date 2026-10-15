"""Keep discovering until 100 VERIFIED local businesses or a bounded source limit.

Not an email sender or campaign. Website/contact proof is checked before
approval. Only aggregate counts reach GitHub; private handoff keeps identities.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
import os
import re

from dedupe_preflight import domains_match, match_candidate, normalize_company, normalize_domain
from new_leads import NATIONAL_HUBS, NATIONAL_NAMES, safe_hint
from overture_discovery import discover
from registry_readonly import load_suppressions
from target_scope import validate_requested_keywords
from verify_official_lead import category, verify_official_site

MAX_PER_REGION = 700
MAX_SITE_CHECKS = 800
MAX_WORKERS = 6
CHUNK = 24


def fill_verified(region, keywords, radius_km, *, target=100,
                  discoverer=discover, verifier=verify_official_site,
                  load_registry=load_suppressions):
    if (not isinstance(region, str) or not 2 <= len(region.strip()) <= 100
            or not isinstance(keywords, list) or not 1 <= len(keywords) <= 8
            or not 0.5 <= radius_km <= 30 or target != 100):
        raise ValueError("verified_fill_invalid_request")
    validate_requested_keywords(keywords)
    # The source registry/HMAC must be complete BEFORE a single website lookup.
    registry = load_registry()
    regions = NATIONAL_HUBS if region.casefold().strip() in NATIONAL_NAMES else (region,)
    approved = []
    seen_names, seen_domains, seen_emails = set(), set(), set()
    seen_sites = set()
    counts = {"source_hints": 0, "sites_checked": 0, "previously_used": 0,
              "duplicates": 0, "unverified": 0, "source_errors": 0,
              "regions_scanned": 0}
    for centre in regions:
        if len(approved) == target or counts["sites_checked"] >= MAX_SITE_CHECKS:
            break
        try:
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = discoverer(
                    region=centre, bbox=None, radius_km=radius_km,
                    keywords=keywords, max_results=MAX_PER_REGION,
                    require_website=True, probe_websites=False,
                )
        except Exception:
            counts["source_errors"] += 1
            continue
        if not isinstance(result, dict) or not isinstance(result.get("candidates"), list):
            raise RuntimeError("verified_fill_discovery_shape_invalid")
        counts["regions_scanned"] += 1
        hints = result["candidates"][:MAX_PER_REGION]
        counts["source_hints"] += len(hints)
        possible = []
        for row in hints:
            if not isinstance(row, dict):
                counts["unverified"] += 1
                continue
            website = safe_hint(row.get("website_hint"))
            name = str(row.get("name_hint") or "").strip()
            domain = normalize_domain(website) if website else ""
            if not website or not name or len(name) > 160 or not domain or not category(row):
                counts["unverified"] += 1
                continue
            # Never query the same site repeatedly, even across Overture regions.
            if domain in seen_sites:
                counts["duplicates"] += 1
                continue
            seen_sites.add(domain)
            if match_candidate({"name_hint": name, "website_hint": website,
                                "lead_id": row.get("overture_id"),
                                "emails": [c.get("email", "") for c in
                                           (row.get("discovery_email_candidates") or [])
                                           if isinstance(c, dict)]}, registry):
                counts["previously_used"] += 1
                continue
            possible.append(row)

        # Small chunks cap in-flight requests; stop at exactly 100 results.
        for index in range(0, len(possible), CHUNK):
            remaining_budget = MAX_SITE_CHECKS - counts["sites_checked"]
            if len(approved) >= target or remaining_budget <= 0:
                break
            block = possible[index:index + min(CHUNK, remaining_budget)]
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                verified = list(executor.map(verifier, block))
            counts["sites_checked"] += len(block)
            for candidate in verified:
                if len(approved) >= target:
                    break
                if candidate is None:
                    counts["unverified"] += 1
                    continue
                name = normalize_company(candidate["company"])
                domain = normalize_domain(candidate["website"])
                email = candidate["email"].casefold()
                # Check email against historical HMAC/ordinary registry again:
                # Overture's email candidates are NEVER contact authority.
                if match_candidate({"name_hint": candidate["company"],
                                    "website_hint": candidate["website"],
                                    "email": email}, registry):
                    counts["previously_used"] += 1
                    continue
                if (name in seen_names or email in seen_emails or
                        any(domains_match(domain, prev) for prev in seen_domains)):
                    counts["duplicates"] += 1
                    continue
                seen_names.add(name)
                seen_domains.add(domain)
                seen_emails.add(email)
                approved.append(candidate)

    # Exhausted is a factual PARTIAL, never a false claim of 100 verified.
    if counts["regions_scanned"] == 0:
        raise RuntimeError("verified_fill_source_unavailable")
    return {"approved": approved, "target": target,
            "complete": len(approved) == target,
            "counts": {**counts, "approved": len(approved)},
            "emails_sent": 0, "mailbox_writes": 0}


def main():
    try:
        region = os.getenv("REGION", "Nederland").strip() or "Nederland"
        words = [x.strip() for x in re.split(r"[,;]", os.getenv("KEYWORDS", "vakbedrijven"))
                 if x.strip()]
        radius = float(os.getenv("RADIUS", "25"))
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            result = fill_verified(region, words, radius, target=100)
            from approved_handoff import store_approved
            saved = store_approved(result["approved"])
        print(json.dumps({
            "status": "complete" if result["complete"] else "partial",
            "target": 100, "approved_stored_privately": saved,
            "counts": result["counts"], "emails_sent": 0,
            "mailbox_writes": 0, "public_identities": 0,
        }, sort_keys=True))
        return 0 if result["complete"] else 2
    except Exception:
        print(json.dumps({"status": "blocked", "reason": "source_or_registry_unavailable",
                          "emails_sent": 0, "public_identities": 0}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
