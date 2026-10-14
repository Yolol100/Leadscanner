"""New company hints only: read live suppressions, no mail or registry writes."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from itertools import zip_longest
import ipaddress
import json
import re
from urllib.parse import urlparse

from dedupe_preflight import match_candidate, normalize_company, normalize_domain
from overture_discovery import discover
from registry_readonly import load_suppressions


# Geographic sampling across all twelve provinces; NOT exhaustive NL coverage.
NATIONAL_HUBS = (
    "Groningen", "Leeuwarden", "Assen", "Zwolle", "Lelystad", "Arnhem",
    "Utrecht", "Haarlem", "Den Haag", "Middelburg", "Eindhoven", "Maastricht",
)
NATIONAL_NAMES = {"nederland", "heel nederland", "netherlands", "nl"}


def safe_hint(value):
    text = str(value or "").strip()
    if len(text) > 512:
        return ""
    try:
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        if parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
            return ""
        host = parsed.hostname.lower().rstrip(".")
        if "." not in host or host.endswith((".local", ".internal", ".localhost", ".lan", ".test", ".example")):
            return ""
        try:
            if not ipaddress.ip_address(host).is_global:
                return ""
        except ValueError:
            pass
        return text
    except ValueError:
        return ""


def select_candidates(raw, registry, limit):
    if not isinstance(raw, dict) or not isinstance(raw.get("candidates"), list):
        raise ValueError("invalid_discovery")
    if not 1 <= limit <= 100:
        raise ValueError("invalid_limit")
    counts = {"scanned": 0, "previously_used": 0, "duplicate": 0,
              "invalid": 0, "new_unverified_hints": 0, "verified_new_leads": 0}
    kept = []
    names, domains = set(), set()
    for row in raw["candidates"][:5000]:
        counts["scanned"] += 1
        if not isinstance(row, dict):
            counts["invalid"] += 1
            continue
        name = str(row.get("name_hint") or "").strip()
        url = safe_hint(row.get("website_hint"))
        domain = normalize_domain(url) if url else ""
        if not name or len(name) > 160 or not domain:
            counts["invalid"] += 1
            continue
        ident = {"name_hint": name, "website_hint": url,
                 "lead_id": row.get("overture_id"),
                 "emails": [item.get("email", "") for item in
                            (row.get("discovery_email_candidates") or [])
                            if isinstance(item, dict)]}
        if match_candidate(ident, registry):
            counts["previously_used"] += 1
            continue
        key = normalize_company(name)
        if key in names or domain in domains:
            counts["duplicate"] += 1
            continue
        names.add(key)
        domains.add(domain)
        kept.append({"company": name, "website_hint": url,
                     "status": "requires_official_site_verification"})
        if len(kept) >= limit:
            break
    counts["new_unverified_hints"] = len(kept)
    counts["regions_scanned"] = int(raw.get("regions_scanned", 1))
    return {"counts": counts, "candidates": kept, "emails_sent": 0, "mailbox_writes": 0,
            "coverage": raw.get("coverage", "regional_sample")}


def discover_sampled_netherlands(keywords, radius, scan_limit):
    """Sample every province using a bounded Overture region. No complete-NL claim."""
    per_region = min(70, max(25, (scan_limit + len(NATIONAL_HUBS) - 1) // len(NATIONAL_HUBS)))
    groups = []
    for index, centre in enumerate(NATIONAL_HUBS, start=1):
        try:
            response = discover(region=centre, bbox=None, radius_km=radius,
                                keywords=keywords, max_results=per_region,
                                require_website=True, probe_websites=False)
        except Exception as exc:
            # Only fixed diagnostic codes and a numeric region index reach
            # public GitHub Actions. Never print an exception's source text.
            description = str(exc)
            if "PDOK could not resolve region" in description:
                code = "pdok_no_match"
            elif "overturemaps download failed" in description:
                code = "overture_download"
            elif type(exc).__name__ in {"Timeout", "ConnectionError", "HTTPError"}:
                code = "pdok_transport"
            else:
                code = "source_unavailable"
            raise RuntimeError(f"national_region_{index:02d}_{code}") from None
        if not isinstance(response, dict) or not isinstance(response.get("candidates"), list):
            raise RuntimeError(f"national_region_{index:02d}_invalid_payload")
        groups.append(response["candidates"])
    # Round-robin rather than global confidence sorting: geographic diversity.
    hints = [item for group in zip_longest(*groups) for item in group if item is not None]
    return {"candidates": hints, "regions_scanned": len(NATIONAL_HUBS),
            "coverage": "12_regional_centre_samples_not_exhaustive"}


def run(region, keywords, radius, limit):
    if not (2 <= len(region) <= 100 and 1 <= len(keywords) <= 8
            and all(2 <= len(x) <= 64 for x in keywords)
            and .5 <= radius <= 30 and 1 <= limit <= 100):
        raise ValueError("invalid_inputs")
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        registry = load_suppressions()
        # Discover more hints than requested: previously contacted businesses
        # and duplicates must not exhaust the new-lead shortlist prematurely.
        scan_limit = min(5000, max(100, limit * 5))
        if region.casefold() in NATIONAL_NAMES:
            raw = discover_sampled_netherlands(keywords, radius, scan_limit)
        else:
            raw = discover(region=region, bbox=None, radius_km=radius,
                           keywords=keywords, max_results=scan_limit,
                           require_website=True, probe_websites=False)
    return select_candidates(raw, registry, limit)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--region", required=True)
    p.add_argument("--keywords", required=True)
    p.add_argument("--radius-km", type=float, default=8)
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--summary-only", action="store_true")
    args = p.parse_args()
    try:
        result = run(args.region.strip(), [x.strip() for x in re.split("[,;]", args.keywords) if x.strip()],
                     args.radius_km, args.limit)
        print(json.dumps({"status": "green", "counts": result["counts"],
                          "coverage": result["coverage"],
                          "identities_exposed": False, "emails_sent": 0}, sort_keys=True))
        return 0
    except Exception as exc:
        reason = str(exc)
        if not re.fullmatch(
            r"national_region_(0[1-9]|1[0-2])_(pdok_no_match|pdok_transport|overture_download|source_unavailable|invalid_payload)",
            reason,
        ):
            reason = "discovery_or_registry_unavailable"
        print(json.dumps({"status": "red", "reason": reason, "emails_sent": 0}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
