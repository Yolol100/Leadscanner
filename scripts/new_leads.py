"""New company hints only: read live suppressions, no mail or registry writes."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import ipaddress
import json
import re
from urllib.parse import urlparse

from dedupe_preflight import match_candidate, normalize_company, normalize_domain
from overture_discovery import discover
from registry_readonly import load_suppressions


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
        ident = {"name_hint": name, "website_hint": url}
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
    return {"counts": counts, "candidates": kept, "emails_sent": 0, "mailbox_writes": 0}


def run(region, keywords, radius, limit):
    if not (2 <= len(region) <= 100 and 1 <= len(keywords) <= 8
            and all(2 <= len(x) <= 64 for x in keywords)
            and .5 <= radius <= 30 and 1 <= limit <= 100):
        raise ValueError("invalid_inputs")
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        registry = load_suppressions()
        raw = discover(region=region, bbox=None, radius_km=radius,
                       keywords=keywords, max_results=limit,
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
                          "identities_exposed": False, "emails_sent": 0}, sort_keys=True))
        return 0
    except Exception:
        print('{"status":"red","reason":"discovery_or_registry_unavailable","emails_sent":0}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
