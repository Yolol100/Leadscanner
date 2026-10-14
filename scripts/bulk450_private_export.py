"""One-time, read-only Dutch leads research; encrypt all identities before output.

This is data collection, NOT accepted customers or permission to contact them.
The private key never leaves the user's local workspace.
"""
import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from io import StringIO
import json
import os
import re
import sys
import zlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from dedupe_preflight import match_candidate, normalize_company, normalize_domain
from new_leads import safe_hint
from overture_discovery import discover, probe_website
from registry_readonly import load_suppressions

PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEAu+qCNb77gBvk6101oOCv
uZXAQQ6lOrPx7dE0tiKN3DBp1EbRT/o4hCUaFYCc/Tpdb1hpW9zLfZuGg85skxo3
8jT2wpLXF+zGOj+2hLJqZ5i4plaly3eQao4xFN6fWTPxrThKnoFvs+2ZXSsIpVOZ
CSfJhXm9WO37GCPoG2hKdv/ho453AYrs+vCniwjjhw5mr8WxTrdQ/5Kv8A6nLdrn
MDlUsiuTXQWefqZ0T9KpWez1Tl1zo/Am0Qg3UySgWEQRWY47HCw+Ztx8LoL5DT2G
TGoY+Gf5B7YYo9rSfeizvMBEkC1LkzoyiE1tuzuh7TFx7Y8vnn9yX8mS2JJc592r
60DscL5dIf6SGeRj+80lT9FFhgR2QlauzZOy7TsAmdbo5GYrOCXLZzrGXdoBS6c3
DlPYi9mjDGojpOSysMdhwMEH9W0K8EjuN201u15T/Ob7JqCVOaH5vIYjfD1+4ZK7
QtA4VFzj9YB4jLQXITzSeFn3CcIBgv743po7iGKUPiE3AgMBAAE=
-----END PUBLIC KEY-----""".encode()

HUBS = (
    "Groningen", "Leeuwarden", "Assen", "Zwolle", "Lelystad", "Arnhem",
    "Utrecht", "Haarlem", "Den Haag", "Middelburg", "Eindhoven", "Maastricht",
    "Alkmaar", "Hoorn", "Amsterdam", "Almere", "Hilversum", "Rotterdam",
    "Dordrecht", "Breda", "Tilburg", "Den Bosch", "Nijmegen", "Apeldoorn",
    "Deventer", "Enschede", "Venlo", "Roermond", "Emmen", "Heerenveen",
    "Goes", "Terneuzen", "Doetinchem", "Amersfoort", "Leiden", "Gouda",
    "Helmond", "Weert", "Hardenberg", "Sneek",
)
KNOWN_CHAIN_DOMAINS = {
    "amikappers.nl", "kinki.nl", "hizihair.nl", "kreatos.be",
    "cosmohairstyling.com",
}
TARGET = 450
RETRIEVE = 800
RADIUS_KM = 25
PER_HUB = 1250
SECTORS = ("kappers", "bouwbedrijven")


def sector_for(row):
    category = re.sub(r"[_\s]+", " ", str(row.get("category_hint") or "").casefold())
    name = str(row.get("name_hint") or "").casefold()
    if any(v in category for v in ("hair salon", "hairdresser", "barber", "coiff", "hair stylist")):
        return "kappers"
    if any(v in category for v in ("construction", "contractor", "builder", "bouw", "aannemer")):
        return "bouwbedrijven"
    if any(v in name for v in ("kapsalon", "kapper", "hairstyle", "hairdresser", "barber")):
        return "kappers"
    if any(v in name for v in ("bouwbedrijf", "aannem", "construction", "bouwonderneming")):
        return "bouwbedrijven"
    return None


def company_hint(row):
    name = str(row.get("name_hint") or "").strip()
    website = safe_hint(row.get("website_hint"))
    domain = normalize_domain(website)
    if not name or len(name) > 160 or not website or not domain:
        return None
    # Reject websites that are knowingly outside NL, branded chain HQs,
    # or generic directories; keep other domains pending website confirmation.
    if domain.endswith((".de", ".be", ".fr", ".lu", ".com.be", ".co.uk")):
        return None
    if domain in KNOWN_CHAIN_DOMAINS or any(domain.endswith("." + d) for d in KNOWN_CHAIN_DOMAINS):
        return None
    country = str(row.get("country_hint") or "").strip().upper()
    if country and country != "NL":
        return None
    sec = sector_for(row)
    if sec is None:
        return None
    return name, website, domain, country, sec


def survey(registry, source=discover, hubs=HUBS):
    counters = Counter()
    pools = {k: [] for k in SECTORS}
    seen_domains, seen_names, seen_ids = set(), set(), set()
    region_errors = []
    completed = 0
    for idx, centre in enumerate(hubs, start=1):
        try:
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                raw = source(region=centre, bbox=None, radius_km=RADIUS_KM,
                             keywords=["kapsalon", "bouwbedrijf"],
                             max_results=PER_HUB, require_website=True,
                             probe_websites=False)
            if not isinstance(raw, dict) or not isinstance(raw.get("candidates"), list):
                raise RuntimeError("invalid_result")
        except Exception:
            region_errors.append(idx)
            continue
        completed += 1
        for row in raw["candidates"]:
            counters["scanned_source_records"] += 1
            if not isinstance(row, dict):
                counters["bad_records"] += 1
                continue
            hint = company_hint(row)
            if hint is None:
                counters["rejected_location_category_or_site"] += 1
                continue
            name, website, domain, country, sec = hint
            overture_id = str(row.get("overture_id") or "").strip()
            ident = {
                "name_hint": name, "website_hint": website, "lead_id": overture_id,
                "emails": [x.get("email", "") for x in
                           (row.get("discovery_email_candidates") or [])
                           if isinstance(x, dict)],
            }
            if match_candidate(ident, registry):
                counters["historically_suppressed"] += 1
                continue
            namekey = normalize_company(name)
            if domain in seen_domains or namekey in seen_names or (
                overture_id and overture_id in seen_ids
            ):
                counters["batch_duplicates"] += 1
                continue
            seen_domains.add(domain)
            seen_names.add(namekey)
            if overture_id:
                seen_ids.add(overture_id)
            pools[sec].append({
                "company": name, "website": website, "domain": domain,
                "sector": sec, "country_hint": country or "unknown",
                "city_hint": str(row.get("locality_hint") or ""),
                "postcode_hint": str(row.get("postcode_hint") or ""),
                "source_category": str(row.get("category_hint") or ""),
                "overture_id": overture_id, "source_hub": centre,
                "source_lat": row.get("latitude"), "source_lon": row.get("longitude"),
                "source_confidence": row.get("confidence"),
            })
            counters["new_company_hints"] += 1
        # Minimum twelve provincial hubs before a short circuit.
        if idx >= 12 and all(len(pools[s]) >= 360 for s in SECTORS):
            break
        if idx % 8 == 0:
            print("BULK450_PROGRESS hubs_checked=" + str(idx) +
                  " unmatched_hints=" + str(sum(map(len, pools.values()))) +
                  " details_suppressed=true", flush=True)
    if completed < 12:
        raise RuntimeError("insufficient_regional_coverage")
    counters["hubs_completed"] = completed
    counters["hubs_failed"] = len(region_errors)
    counters["hubs_attempted"] = completed + len(region_errors)
    counters["pool_hair"] = len(pools["kappers"])
    counters["pool_build"] = len(pools["bouwbedrijven"])
    # Prefer NL-labeled source records within each sector, retain unknown as unverified.
    for sector in SECTORS:
        pools[sector].sort(key=lambda x: (
            x["country_hint"] != "NL",
            not bool(x["city_hint"]), 
            -(x["source_confidence"] or 0),
        ))
    return pools, dict(counters), region_errors


def balanced_queue(pools, max_items=RETRIEVE):
    # Alternate sectors until depleted, then fill from whichever remains.
    out = []
    for i in range(max(map(len, pools.values()), default=0)):
        for sector in SECTORS:
            if i < len(pools[sector]):
                out.append(pools[sector][i])
                if len(out) >= max_items:
                    return out
    return out


def reachability(rows, probe=probe_website):
    # Bounded website checks; no personal information logged.
    def check(item):
        try:
            p = probe(item["website"], timeout=8)
            if not isinstance(p, dict):
                return {"status": "unreachable", "final_url": None, "http_status": None}
            return {
                "status": str(p.get("status") or "")[:70],
                "final_url": str(p.get("final_url") or "")[:500],
                "http_status": p.get("http_status"),
            }
        except Exception:
            return {"status": "unreachable", "final_url": None, "http_status": None}
    with ThreadPoolExecutor(max_workers=12) as pool:
        return list(pool.map(check, rows))


def choose_450(rows, probes):
    reachable = []
    not_reachable = []
    for item, p in zip(rows, probes):
        item = dict(item)
        item["http_status"] = p.get("http_status")
        item["final_url"] = p.get("final_url")
        item["technical_status"] = p.get("status")
        item["identity_status"] = "website_reachability_only_not_independently_verified"
        if p.get("status") == "reachable_needs_leads_identity_verification":
            reachable.append(item)
        else:
            not_reachable.append(item)
    selected = reachable[:RETRIEVE]
    return selected, len(reachable), len(not_reachable)


def seal(data, pem=PUBLIC_KEY):
    public = serialization.load_pem_public_key(pem)
    symmetric = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    clear = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    if len(clear) > 2_000_000:
        raise RuntimeError("payload_too_large")
    compressed = zlib.compress(clear, level=9)
    cipher = AESGCM(symmetric).encrypt(nonce, compressed, b"fresh-leads-450-v1")
    wrapped = public.encrypt(symmetric, padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(), label=None))
    envelope = {
        "v": 1, "compression": "zlib",
        "key": base64.b64encode(wrapped).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(cipher).decode(),
    }
    return base64.b64encode(json.dumps(envelope, separators=(",", ":")).encode()).decode()


def main():
    try:
        # Fail closed if any historical registry segment / private vault is unavailable.
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            registry = load_suppressions()
        pools, counters, failures = survey(registry)
        rows = balanced_queue(pools, RETRIEVE)
        if len(rows) < TARGET:
            raise RuntimeError("not_enough_source_hints")
        probes = reachability(rows)
        selected, num_reachable, num_unreachable = choose_450(rows, probes)
        results = {
            "collected_utc": datetime.now(timezone.utc).isoformat(),
            "source": "Overture Maps Places + PDOK Locations + Live historical dedupe",
            "coverage": "NL sample of regional 25-km hubs; not a national census",
            "target": TARGET, "raw_probe_size": len(rows),
            "reachable_candidates": num_reachable,
            "unreachable_candidate_count": num_unreachable,
            "counters": counters, "failed_region_indices": failures,
            "candidates": selected,
            "warning": "These are new, previously unsuppressed company hints with reachable web URLs, NOT proven customers or approved contact targets. Official identity, Dutch location, suitability and contact basis need independent review.",
            "emails_sent": 0, "mailbox_writes": 0, "registry_writes": 0,
        }
        encrypted = seal(results)
        print("BULK450_ENCRYPTED=" + encrypted)
        print("BULK450_RESULT=green counted=" + str(len(selected)) +
              " scanned=" + str(counters["scanned_source_records"]) +
              " reachable=" + str(num_reachable) +
              " source_hubs=" + str(counters["hubs_completed"]) +
              " privacy=encrypted no_mail=true", flush=True)
        return 0
    except BaseException:
        print("BULK450_RESULT=blocked reason=safe_source_or_registry_failure no_mail=true", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
