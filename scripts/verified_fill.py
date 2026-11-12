"""Keep discovering until 100 VERIFIED local businesses or a bounded source limit.

Not an email sender or campaign. Website/contact proof is checked before
approval. Only aggregate counts reach GitHub; private handoff keeps identities.
"""
from __future__ import annotations

from collections import deque
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
# Fixed, not user-configurable region sets for the additional 450 -> 500 goal.
# Continue beyond the already sampled 24 regions without unbounded scanning.
EXTRA_REGION_SETS = {
    "extra opvolging": ("Emmen", "Hoorn", "Roosendaal", "Gouda", "Heerlen",
                         "Hilversum", "Ede", "Hengelo", "Doetinchem", "Sittard"),
    "extra vervolg": ("Goes", "Meppel", "Oss", "Harderwijk", "Purmerend",
                      "Drachten", "Alphen aan den Rijn", "Hoogeveen",
                      "Zutphen", "Schagen"),
}


def fill_verified(region, keywords, radius_km, *, target=100,
                  discoverer=discover, verifier=verify_official_site,
                  load_registry=load_discovery_suppressions,
                  max_site_checks=MAX_SITE_CHECKS):
    if (not isinstance(region, str) or not 2 <= len(region.strip()) <= 100
            or not isinstance(keywords, list) or not 1 <= len(keywords) <= 8
            or not 0.5 <= radius_km <= 30 or not isinstance(target, int)
            or not 1 <= target <= 100
            or not isinstance(max_site_checks, int)
            or not 1 <= max_site_checks <= MAX_SITE_CHECKS):
        raise ValueError("verified_fill_invalid_request")
    validate_requested_keywords(keywords)
    started = time.monotonic()
    discovery_seconds = verification_seconds = 0.0
    # The source registry/HMAC must be complete BEFORE a single website lookup.
    registry = load_registry()
    region_key = region.casefold().strip()
    regions = (EXTRA_REGION_SETS[region_key] if region_key in EXTRA_REGION_SETS
               else NATIONAL_HUBS if region_key in NATIONAL_NAMES else (region,))
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
            if len(approved) == target or counts["sites_checked"] >= max_site_checks:
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

            # Rotate industries before network checks. This avoids taking the
            # first hundred hints from one dominant sector.
            buckets = {}
            for item in possible:
                buckets.setdefault(category(item)[1], deque()).append(item)
            possible = []
            while any(buckets.values()):
                for group in buckets.values():
                    if group:
                        possible.append(group.popleft())

            # Small chunks cap in-flight requests; stop at the exact target.
            index = 0
            while index < len(possible):
                remaining_budget = max_site_checks - counts["sites_checked"]
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
    """Only count a verified general inbox with complete first-party evidence."""
    import requests
    from fast_website_evidence import inspect_verified

    with requests.Session() as session:
        actual = verify_official_site(row, session=session, collect_evidence=True)
    if actual is None:
        return None
    record = {"company": actual["company"], "website": actual["website"],
              "email": actual["email"], "branch": actual["branche_meervoud"]}
    proof = inspect_verified(record, actual, actual.get("_captured_pages", []))
    return actual if proof["status"].startswith("verified_") else None


def _single():
    try:
        region = os.getenv("REGION", "Nederland").strip() or "Nederland"
        words = [x.strip() for x in re.split(r"[,;]", os.getenv("KEYWORDS", "vakbedrijven"))
                 if x.strip()]
        radius = float(os.getenv("RADIUS", "25"))
        campaign_goal = None
        campaign_before = None
        target = 100
        if os.getenv("LEAD_CAMPAIGN_SINCE_UTC"):
            from lead_campaign_counter import remaining
            goal_text = os.getenv("LEAD_CAMPAIGN_GOAL")
            if not goal_text or not goal_text.isascii() or not goal_text.isdecimal():
                raise RuntimeError("campaign_target_invalid")
            campaign_goal = int(goal_text)
            if not 1 <= campaign_goal <= 5000:
                raise RuntimeError("campaign_target_invalid")
            left = remaining(os.environ["LEAD_CAMPAIGN_SINCE_UTC"], goal=campaign_goal)
            campaign_before = campaign_goal - left
            if left == 0:
                print(json.dumps({"status": "goal_reached", "campaign_valid_total":
                                  campaign_goal, "emails_sent": 0,
                                  "mailbox_writes": 0, "public_identities": 0},
                                 sort_keys=True))
                return 0
            target = min(100, left)
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            # Weekly automation is deliberately bounded; it may end PARTIAL.
            limit = 240 if os.getenv("GITHUB_EVENT_NAME") == "schedule" else MAX_SITE_CHECKS
            result = fill_verified(region, words, radius, target=target,
                                   verifier=_verify_with_one_pass_evidence,
                                   max_site_checks=limit)
            saved = 0
            extra = {"source_rows": 0, "captured_without_refetch": 0,
                     "verified_with_detail": 0, "verified_activity_only": 0,
                     "needs_manual_check": 0}
            if result["approved"]:
                from approved_handoff import store_approved, values as approved_values
                from fast_website_evidence import prepare_new_approved_evidence
                # Derive all evidence from the original verified website pages
                # BEFORE the lead enters permanent suppression/history.
                # On failure, NONE of the three private tables is committed.
                approved_snapshot = approved_values(
                    result["approved"], os.getenv("GITHUB_RUN_ID", ""))
                fact_rows = prepare_new_approved_evidence(
                    result["approved"], approved_snapshot)
                if any(not row["status"].startswith("verified_")
                       for row in fact_rows):
                    raise RuntimeError("unverified_evidence_cannot_enter_history")
                saved = store_approved(result["approved"],
                                       evidence_rows=fact_rows)
                extra = {
                    "source_rows": len(fact_rows),
                    "captured_without_refetch": len(fact_rows),
                    "verified_with_detail": sum(
                        row["status"] == "verified_with_detail" for row in fact_rows),
                    "verified_activity_only": sum(
                        row["status"] == "verified_activity_only" for row in fact_rows),
                    "needs_manual_check": sum(
                        row["status"] == "needs_manual_check" for row in fact_rows),
                }
        campaign_valid_total = (campaign_before + extra["verified_with_detail"] +
                                extra["verified_activity_only"] if campaign_before is not None
                                else None)
        # A website-approved candidate with manual evidence cannot count as
        # confirmed. Never claim the 500 target before official evidence agrees.
        goal_complete = result["complete"] and (
            campaign_goal is None or campaign_valid_total >= campaign_goal)
        print(json.dumps({
            "status": "complete" if goal_complete else "partial",
            "target": target, "approved_stored_privately": saved,
            "campaign_valid_total": campaign_valid_total,
            "campaign_remaining": (max(0, campaign_goal - campaign_valid_total)
                                   if campaign_goal is not None else None),
            "one_pass_evidence": extra,
            "counts": result["counts"], "timings": result["timings"], "emails_sent": 0,
            "mailbox_writes": 0, "public_identities": 0,
        }, sort_keys=True))
        return 0 if goal_complete else 2
    except Exception:
        print(json.dumps({"status": "blocked", "reason": "source_or_registry_unavailable",
                          "emails_sent": 0, "public_identities": 0}, sort_keys=True))
        return 1


# A single owner request may need several verified batches. Keep each batch
# small and atomic; the cutoff comes from the authenticated GitHub event.
AUTO_REGIONS = ("Nederland", "Extra opvolging", "Extra vervolg")
MAX_AUTO_BATCHES = 12
MAX_AUTO_SECONDS = 85 * 60


def main():
    if os.getenv("LEAD_AUTO_TARGET") != "1":
        return _single()
    from lead_campaign_counter import remaining

    started = time.monotonic()
    since = os.getenv("LEAD_CAMPAIGN_SINCE_UTC", "")
    goal_text = os.getenv("LEAD_CAMPAIGN_GOAL", "")
    if not goal_text.isascii() or not goal_text.isdecimal():
        return 1
    goal = int(goal_text)
    if not since or not 1 <= goal <= 1000:
        return 1
    try:
        left = remaining(since, goal=goal)
        no_progress = 0
        for n in range(MAX_AUTO_BATCHES):
            if left == 0:
                print(json.dumps({"status": "complete", "remaining": 0,
                                  "requested": goal, "emails_sent": 0,
                                  "mailbox_writes": 0, "public_identities": 0},
                                 sort_keys=True))
                return 0
            if time.monotonic() - started >= MAX_AUTO_SECONDS:
                break
            os.environ["REGION"] = AUTO_REGIONS[n % len(AUTO_REGIONS)]
            status = _single()
            if status == 1:  # System, credential or source-integrity failure.
                return 1
            updated = remaining(since, goal=goal)  # Fresh private readback.
            no_progress = no_progress + 1 if updated >= left else 0
            left = updated
            if no_progress >= len(AUTO_REGIONS):
                break
        done = left == 0
        print(json.dumps({"status": "complete" if done else "partial",
                          "requested": goal, "remaining": left,
                          "reason": "" if done else "bounded_sources_or_time",
                          "emails_sent": 0, "mailbox_writes": 0,
                          "public_identities": 0}, sort_keys=True))
        # A valid partial is not a broken GitHub job. Never call it complete.
        return 0
    except Exception:
        print(json.dumps({"status": "blocked",
                          "reason": "campaign_progress_unavailable",
                          "emails_sent": 0, "public_identities": 0},
                         sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
