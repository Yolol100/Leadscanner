from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from extract_public_contacts import EMAIL_RE, email_fits_business_context, normalize_domain


def _row_keys(row: dict) -> list[str]:
    keys: list[str] = []
    place_id = str(row.get("place_id") or "").strip()
    cid = str(row.get("cid") or "").strip()
    domain = normalize_domain(row.get("website") or row.get("web_site"))
    if place_id:
        keys.append("place:" + place_id)
    if cid:
        keys.append("cid:" + cid)
    if domain:
        keys.append("domain:" + domain)
    return keys


def read_fallback_rows(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            for key in _row_keys(row):
                rows[key] = row
    return rows


def _candidate_keys(item: dict) -> list[str]:
    keys: list[str] = []
    place_id = str(item.get("google_maps_place_id") or "").strip()
    cid = str(item.get("google_maps_cid") or "").strip()
    domain = normalize_domain(item.get("official_domain_hint") or item.get("website_hint"))
    if place_id:
        keys.append("place:" + place_id)
    if cid:
        keys.append("cid:" + cid)
    if domain:
        keys.append("domain:" + domain)
    return keys


def apply_fallback(payload: dict, fallback_rows: dict[str, dict]) -> dict:
    changed = 0
    for item in payload.get("candidates") or []:
        if item.get("excluded_competitor") or item.get("public_business_emails"):
            continue

        row = None
        for key in _candidate_keys(item):
            if key in fallback_rows:
                row = fallback_rows[key]
                break
        if not row:
            continue

        official_domain = normalize_domain(item.get("official_domain_hint") or item.get("website_hint"))
        row_domain = normalize_domain(row.get("website") or row.get("web_site"))
        if official_domain and row_domain and official_domain != row_domain:
            continue

        found: list[str] = []
        for match in EMAIL_RE.findall(str(row.get("emails") or "")):
            email = match.strip().lower().strip(".,;:()[]<>")
            if (
                email not in found
                and email_fits_business_context(email, official_domain, "google_maps_targeted_fallback")
            ):
                found.append(email)
            if len(found) >= 3:
                break
        if not found:
            continue

        item["public_business_emails"] = found
        item["email_source_types"] = ["google_maps_targeted_fallback"] * len(found)
        item["email_source_refs"] = [str(row.get("link") or item.get("maps_link_hint") or "")] * len(found)
        item["contact_discovery_status"] = "found_discovery_fallback"
        item["contact_basis_status"] = "review_required"
        item["contact_basis_hint"] = "public_email_review_required"
        changed += 1

    payload["contact_found_count"] = sum(
        1 for item in payload.get("candidates") or [] if item.get("public_business_emails")
    )
    payload.setdefault("safety", {})["google_maps_email_mode"] = "targeted_fallback_only"
    payload["safety"]["google_maps_fallback_changed_count"] = changed
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contacts", required=True)
    parser.add_argument("--google-maps-csv", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = json.loads(Path(args.contacts).read_text(encoding="utf-8"))
    rows = read_fallback_rows(Path(args.google_maps_csv))
    result = apply_fallback(payload, rows)
    Path(args.output).write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        "TARGETED_MAPS_EMAIL_FALLBACK=green "
        f"contacts={result['contact_found_count']} "
        f"changed={result['safety']['google_maps_fallback_changed_count']} "
        "contact_basis_auto_pass=false email_send=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
