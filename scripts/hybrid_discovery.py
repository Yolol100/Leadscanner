from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

MAX_RESULTS = 5000
EMAIL_RE = re.compile(r"(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,63})(?![A-Z0-9._%+-])", re.I)

FORBIDDEN_CONTACT_FIELDS = {
    "email",
    "emails",
    "phone",
    "phones",
    "social",
    "socials",
    "facebook",
    "instagram",
    "linkedin",
    "twitter",
    "x",
}


def _normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().casefold()


def _valid_http_url(value: object) -> bool:
    try:
        parsed = urlparse(str(value or "").strip())
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _normalize_domain(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = text if "://" in text else f"https://{text}"
    try:
        parsed = urlparse(candidate)
    except Exception:
        return None
    host = (parsed.hostname or "").strip().casefold().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _parse_email_candidates(value: object, source: str) -> list[dict]:
    text = str(value or "")
    found: list[dict] = []
    seen: set[str] = set()
    for match in EMAIL_RE.findall(text):
        email = match.strip().lower().strip(".,;:()[]<>")
        if email and email not in seen:
            seen.add(email)
            found.append({"email": email, "source": source})
    return found


def _float_or_none(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _website_probe(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    allowed = {"status", "final_url", "http_status", "detail"}
    safe = {key: value.get(key) for key in allowed if key in value}
    final_url = safe.get("final_url")
    if final_url and not _valid_http_url(final_url):
        safe["final_url"] = None
    return safe or None


def normalize_overture_candidates(payload: dict, *, require_website: bool) -> list[dict]:
    candidates: list[dict] = []
    for raw in payload.get("candidates") or []:
        if not isinstance(raw, dict):
            continue
        website = str(raw.get("website_hint") or "").strip() or None
        if website and not _valid_http_url(website):
            website = None
        if require_website and not website:
            continue

        candidate = {
            "overture_id": str(raw.get("overture_id") or "").strip() or None,
            "name_hint": str(raw.get("name_hint") or "").strip() or None,
            "category_hint": str(raw.get("category_hint") or "").strip() or None,
            "website_hint": website,
            "longitude": _float_or_none(raw.get("longitude")),
            "latitude": _float_or_none(raw.get("latitude")),
            "confidence": _float_or_none(raw.get("confidence")),
            "discovery_email_candidates": list(raw.get("discovery_email_candidates") or []),
            "discovery_sources": ["overture"],
            "identity_status": "needs_leads_verification",
        }
        probe = _website_probe(raw.get("website_probe"))
        if probe:
            candidate["website_probe"] = probe
        candidates.append(candidate)
    return candidates


def read_google_maps_candidates(path: Path, *, require_website: bool) -> tuple[list[dict], int]:
    candidates: list[dict] = []
    raw_rows = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            raw_rows += 1
            status = _normalize_text(row.get("status"))
            if "permanently closed" in status:
                continue

            website = str(row.get("website") or row.get("web_site") or "").strip() or None
            if website and not _valid_http_url(website):
                website = None
            if require_website and not website:
                continue

            candidate = {
                "google_maps_cid": str(row.get("cid") or "").strip() or None,
                "google_maps_place_id": str(row.get("place_id") or "").strip() or None,
                "maps_link_hint": str(row.get("link") or "").strip() or None,
                "name_hint": str(row.get("title") or "").strip() or None,
                "category_hint": str(row.get("category") or "").strip() or None,
                "website_hint": website,
                "longitude": _float_or_none(row.get("longitude")),
                "latitude": _float_or_none(row.get("latitude")),
                "discovery_email_candidates": _parse_email_candidates(row.get("emails"), "google_maps"),
                "discovery_sources": ["google_maps"],
                "identity_status": "needs_leads_verification",
            }
            if candidate["maps_link_hint"] and not _valid_http_url(candidate["maps_link_hint"]):
                candidate["maps_link_hint"] = None
            candidates.append(candidate)
    return candidates, raw_rows


def _candidate_keys(candidate: dict) -> list[str]:
    keys: list[str] = []
    domain = _normalize_domain(candidate.get("website_hint"))
    if domain:
        keys.append(f"domain:{domain}")

    overture_id = str(candidate.get("overture_id") or "").strip()
    if overture_id:
        keys.append(f"overture:{overture_id}")

    place_id = str(candidate.get("google_maps_place_id") or "").strip()
    if place_id:
        keys.append(f"google_maps_place:{place_id}")

    cid = str(candidate.get("google_maps_cid") or "").strip()
    if cid:
        keys.append(f"google_maps_cid:{cid}")
    return keys


def _merge_candidate(base: dict, incoming: dict) -> dict:
    merged = dict(base)
    merged["discovery_sources"] = sorted(
        set(base.get("discovery_sources") or []) | set(incoming.get("discovery_sources") or [])
    )

    combined_emails: list[dict] = []
    seen_emails: set[str] = set()
    for item in list(base.get("discovery_email_candidates") or []) + list(incoming.get("discovery_email_candidates") or []):
        if not isinstance(item, dict):
            continue
        email = str(item.get("email") or "").strip().lower()
        if not email or email in seen_emails:
            continue
        seen_emails.add(email)
        combined_emails.append({"email": email, "source": str(item.get("source") or "discovery")})
    merged["discovery_email_candidates"] = combined_emails

    for field in (
        "overture_id",
        "google_maps_cid",
        "google_maps_place_id",
        "maps_link_hint",
        "name_hint",
        "category_hint",
        "website_hint",
        "longitude",
        "latitude",
        "confidence",
        "website_probe",
    ):
        if merged.get(field) in (None, "", []):
            value = incoming.get(field)
            if value not in (None, "", []):
                merged[field] = value

    merged["identity_status"] = "needs_leads_verification"
    return merged


def combine_candidates(
    overture_payload: dict,
    google_maps_candidates: list[dict],
    *,
    max_results: int,
    require_website: bool,
) -> dict:
    if not 1 <= max_results <= MAX_RESULTS:
        raise ValueError(f"max_results must be 1-{MAX_RESULTS}")

    overture_candidates = normalize_overture_candidates(
        overture_payload,
        require_website=require_website,
    )
    all_candidates = overture_candidates + list(google_maps_candidates)

    merged: list[dict] = []
    key_to_index: dict[str, int] = {}
    dropped_undedupeable = 0

    for candidate in all_candidates:
        if not isinstance(candidate, dict):
            continue
        if any(field in candidate for field in FORBIDDEN_CONTACT_FIELDS):
            raise ValueError("contact fields must not enter hybrid discovery candidates")

        keys = _candidate_keys(candidate)
        if not keys:
            dropped_undedupeable += 1
            continue

        matching_indices = {key_to_index[key] for key in keys if key in key_to_index}
        if matching_indices:
            target_index = min(matching_indices)
            merged[target_index] = _merge_candidate(merged[target_index], candidate)
            for key in _candidate_keys(merged[target_index]):
                key_to_index[key] = target_index
            continue

        index = len(merged)
        merged.append(candidate)
        for key in keys:
            key_to_index[key] = index

    merged.sort(
        key=lambda item: (
            -len(item.get("discovery_sources") or []),
            item.get("website_hint") is None,
            _normalize_text(item.get("name_hint")),
            _normalize_domain(item.get("website_hint")) or "",
        )
    )
    merged = merged[:max_results]

    for candidate in merged:
        for forbidden in FORBIDDEN_CONTACT_FIELDS:
            candidate.pop(forbidden, None)
        candidate["identity_status"] = "needs_leads_verification"

    return {
        "schema_version": "webactueel-hybrid-discovery/1.1",
        "sources": [
            {
                "id": "overture",
                "name": "Overture Maps Places",
                "authentication": "none",
            },
            {
                "id": "google_maps",
                "name": "gosom/google-maps-scraper",
                "authentication": "none",
            },
        ],
        "source_counts": {
            "overture_candidates": len(overture_candidates),
            "google_maps_candidates": len(google_maps_candidates),
        },
        "candidate_count": len(merged),
        "dropped_undedupeable_count": dropped_undedupeable,
        "candidates": merged,
        "privacy_and_scope": {
            "email_candidates_emitted": any(item.get("discovery_email_candidates") for item in merged),
            "phones_emitted": False,
            "socials_emitted": False,
            "google_reviews_emitted": False,
            "contact_basis_evaluated": False,
            "draftqueue_write": False,
            "email_send": False,
        },
        "deduplication": {
            "cross_source_domain": True,
            "source_ids": [
                "overture_id",
                "google_maps_place_id",
                "google_maps_cid",
            ],
            "unverified_name_only_deduplication": False,
        },
        "handoff": {
            "owner": "leads",
            "required_next_step": (
                "Open website_hint/final_url directly and verify company + official domain "
                "before any qualification, contact-basis or outreach claim."
            ),
            "discovery_data_is_not_prospect_claim_evidence": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overture", required=True)
    parser.add_argument("--google-maps-csv", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-results", type=int, default=40)
    parser.add_argument("--require-website", action="store_true")
    args = parser.parse_args()

    overture_payload = json.loads(Path(args.overture).read_text(encoding="utf-8"))
    google_candidates, raw_rows = read_google_maps_candidates(
        Path(args.google_maps_csv),
        require_website=args.require_website,
    )
    result = combine_candidates(
        overture_payload,
        google_candidates,
        max_results=args.max_results,
        require_website=args.require_website,
    )
    result["source_counts"]["google_maps_raw_rows"] = raw_rows

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "HYBRID_DISCOVERY=green "
        f"candidates={result['candidate_count']} "
        f"overture={result['source_counts']['overture_candidates']} "
        f"google_maps={result['source_counts']['google_maps_candidates']} "
        "contact_fields=bounded_email_candidates identity=needs_leads_verification"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
