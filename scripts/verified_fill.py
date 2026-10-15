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
import time
from requests.exceptions import RequestException

from dedupe_preflight import domains_match, match_candidate, normalize_company, normalize_domain
from new_leads import NATIONAL_HUBS, NATIONAL_NAMES, safe_hint
from overture_discovery import discover
from registry_readonly import load_discovery_suppressions
from target_scope import validate_requested_keywords
from verify_official_lead import category, verify_official_site

MAX_PER_REGION = 700
MAX_SITE_CHECKS = 800
MAX_WORKERS = 6
CHUNK = 24


def fill_verified(region, keywords, radius_km, *, target=100,
                  discoverer=discover, verifier=verify_official_site,
                  load_registry=load_discovery_suppressions):
    if (not isinstance(region, str) or not 2 <= len(region.strip()) <= 100
            or not isinstance(keywords, list) or not 1 <= len(keywords) <= 8
            or not 0.5 <= radius_km <= 30 or target != 100):
        raise ValueError("verified_fill_invalid_request")
    validate_requested_keywords(keywords)
    started = time.monotonic()
    discovery_seconds = verification_seconds = 0.0
    # The source registry/HMAC must be complete BEFORE a single website lookup.
    registry = load_registry()
    regions = NATIONAL_HUBS if region.casefold().strip() in NATIONAL_NAMES else (region,)
    approved = []
    seen_names, seen_domains, seen_emails = set(), set(), set()
    seen_sites = set()
    counts = {"source_hints": 0, "sites_checked": 0, "previously_used": 0,
              "duplicates": 0, "unverified": 0, "source_errors": 0,
              "regions_scanned": 0}
    # One worker pool across regions, not a new six-thread pool per 24 websites.
    def inspect_one(row):
        try:
            return verifier(row)
        except (RequestException, ValueError, UnicodeError):
            # Malformed/unreachable individual websites are NOT system failures.
            return None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for centre in regions:
            if len(approved) == target or counts["sites_checked"] >= MAX_SITE_CHECKS:
                break
            try:
                scan_start = time.monotonic()
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    result = discoverer(
                        region=centre, bbox=None, radius_km=radius_km,
                        keywords=keywords, max_results=MAX_PER_REGION,
                        require_website=True, probe_websites=False,
                    )
                discovery_seconds += time.monotonic() - scan_start
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
            index = 0
            while index < len(possible):
                remaining_budget = MAX_SITE_CHECKS - counts["sites_checked"]
                remaining_target = target - len(approved)
                if remaining_target <= 0 or remaining_budget <= 0:
                    break
                # Near the target, do not check 24 more sites just to add one.
                batch_size = min(CHUNK, remaining_budget, max(1, remaining_target * 2))
                block = possible[index:index + batch_size]
                index += len(block)
                verify_start = time.monotonic()
                verified = list(executor.map(inspect_one, block))
                verification_seconds += time.monotonic() - verify_start
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
            "timings": {"total_s": round(time.monotonic() - started, 2),
                        "discovery_s": round(discovery_seconds, 2),
                        "verification_s": round(verification_seconds, 2)},
            "emails_sent": 0, "mailbox_writes": 0}


def _verify_with_one_pass_evidence(row):
    """Keep parsed official text only for the private, successful first pass."""
    import requests
    with requests.Session() as session:
        return verify_official_site(row, session=session, collect_evidence=True)


def main():
    try:
        region = os.getenv("REGION", "Nederland").strip() or "Nederland"
        words = [x.strip() for x in re.split(r"[,;]", os.getenv("KEYWORDS", "vakbedrijven"))
                 if x.strip()]
        radius = float(os.getenv("RADIUS", "25"))
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            result = fill_verified(region, words, radius, target=100,
                                   verifier=_verify_with_one_pass_evidence)
            from approved_handoff import store_approved
            saved = store_approved(result["approved"])
            # Reuse the original verified pages; zero extra site requests.
            from fast_website_evidence import store_preverified_approved
            extra = store_preverified_approved(result["approved"])
        print(json.dumps({
            "status": "complete" if result["complete"] else "partial",
            "target": 100, "approved_stored_privately": saved,
            "one_pass_evidence": extra,
            "counts": result["counts"], "timings": result["timings"], "emails_sent": 0,
            "mailbox_writes": 0, "public_identities": 0,
        }, sort_keys=True))
        return 0 if result["complete"] else 2
    except Exception:
        print(json.dumps({"status": "blocked", "reason": "source_or_registry_unavailable",
                          "emails_sent": 0, "public_identities": 0}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
