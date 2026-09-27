from __future__ import annotations

import argparse
import json
from pathlib import Path


def primary_source(item: dict) -> tuple[str | None, str | None]:
    emails = item.get("public_business_emails") or []
    types = item.get("email_source_types") or []
    urls = item.get("email_source_urls") or []
    refs = item.get("email_source_refs") or []
    if not emails:
        return None, None
    source_type = str(types[0] if types else "").strip() or None
    if source_type == "official_site":
        source = str(urls[0] if urls else "").strip() or None
    else:
        source = str(refs[0] if refs else "").strip() or None
    return source_type, source


def build_ready(payload: dict) -> dict:
    candidates = payload.get("candidates") or []
    if not isinstance(candidates, list):
        raise ValueError("candidates must be a list")

    ready: list[dict] = []
    blocked: list[dict] = []
    email_found = 0
    official_site_checked = 0

    for item in candidates:
        if not isinstance(item, dict):
            continue
        status = str(item.get("contact_discovery_status") or "")
        if status not in {"no_website", "unreachable_or_cross_domain"}:
            official_site_checked += 1
        if item.get("public_business_emails"):
            email_found += 1

        reasons: list[str] = []
        if item.get("excluded_competitor"):
            reasons.append("excluded_competitor")
        if not str(item.get("name_hint") or "").strip():
            reasons.append("missing_company_name")
        if not str(item.get("website_hint") or "").strip():
            reasons.append("missing_website")
        if not str(item.get("official_domain_hint") or "").strip():
            reasons.append("missing_official_domain")
        if item.get("language") not in {"nl", "en"}:
            reasons.append("missing_language")
        emails = item.get("public_business_emails") or []
        if not emails:
            reasons.append("missing_public_business_email")
        source_type, source_ref = primary_source(item)
        if emails and (not source_type or not source_ref):
            reasons.append("missing_email_provenance")
        observation = str(item.get("verified_observation") or "").strip()
        observation_url = str(item.get("verified_observation_source_url") or "").strip()
        if not observation:
            reasons.append("missing_verified_observation")
        if observation and (
            item.get("verified_observation_source_type") != "official_site" or not observation_url
        ):
            reasons.append("invalid_observation_provenance")
        if emails and item.get("contact_basis_status") != "review_required":
            reasons.append("contact_basis_not_review_required")

        if reasons:
            blocked.append({
                "company": item.get("name_hint"),
                "website": item.get("website_hint"),
                "status": status,
                "reasons": reasons,
            })
            continue

        ready.append({
            "company": str(item.get("name_hint")).strip(),
            "official_website": observation_url,
            "official_domain": str(item.get("official_domain_hint")).strip(),
            "language": item.get("language"),
            "email": str(emails[0]).strip().lower(),
            "email_source_type": source_type,
            "email_source": source_ref,
            "verified_observation": observation,
            "verified_observation_source_url": observation_url,
            "contact_basis_status": "review_required",
            "contact_discovery_status": status,
            "google_maps_place_id": item.get("google_maps_place_id"),
            "google_maps_cid": item.get("google_maps_cid"),
            "overture_id": item.get("overture_id"),
        })

    return {
        "schema_version": "webactueel-verified-ready/1.0",
        "candidate_count": len(candidates),
        "official_site_checked_count": official_site_checked,
        "email_found_count": email_found,
        "blocked_or_skipped_count": len(blocked),
        "ready_for_copy_count": len(ready),
        "ready_for_copy": ready,
        "blocked_or_skipped": blocked,
        "safety": {
            "company_and_domain_verified_via_official_site_fetch": True,
            "verified_official_site_observation_required": True,
            "email_addresses_guessed": False,
            "contact_basis_auto_pass": False,
            "copy_created": False,
            "draft_created": False,
            "email_send": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contacts", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = json.loads(Path(args.contacts).read_text(encoding="utf-8"))
    result = build_ready(payload)
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "VERIFY_READY=green "
        f"candidates={result['candidate_count']} "
        f"site_checked={result['official_site_checked_count']} "
        f"emails={result['email_found_count']} "
        f"blocked={result['blocked_or_skipped_count']} "
        f"ready={result['ready_for_copy_count']} "
        "copy=false draft=false email_send=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
