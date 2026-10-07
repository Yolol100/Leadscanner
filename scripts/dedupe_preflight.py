#!/usr/bin/env python3
"""Fast fail-closed dedupe gate for cold-lead candidates.

The registry is historical suppression state only. It must never be used as
prospect research or as a source for new outreach claims.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

TRUE_VALUES = {"1", "true", "yes", "y", "ja"}
REQUIRED_REGISTRY_HEADERS = {
    "company",
    "website",
    "domain",
    "emails",
    "status",
    "lead_ids",
    "exclude_from_new_leads",
}

COMPANY_FIELDS = ("company", "name", "name_hint")
DOMAIN_FIELDS = (
    "domain",
    "official_domain",
    "official_domain_hint",
    "website",
    "website_hint",
    "official_url",
)
EMAIL_FIELDS = ("email", "emails")
LEAD_ID_FIELDS = ("lead_id", "lead_ids")


def _text(value: object) -> str:
    return str(value or "").strip()


def normalize_company(value: object) -> str:
    text = unicodedata.normalize("NFKD", _text(value)).casefold()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", text)


def normalize_email(value: object) -> str:
    email = _text(value).casefold().strip(" <>\"'.,;:")
    return email if email.count("@") == 1 else ""


def normalize_domain(value: object) -> str:
    raw = _text(value).casefold()
    if not raw:
        return ""
    candidate = raw if "://" in raw else f"//{raw}"
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def domains_match(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return left == right or left.endswith("." + right) or right.endswith("." + left)


def split_values(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        raw = [str(item) for item in value]
    else:
        raw = re.split(r"[;,\n]+", _text(value))
    return [item.strip() for item in raw if item and item.strip()]


def first_value(candidate: dict, fields: Iterable[str]) -> str:
    for field in fields:
        value = _text(candidate.get(field))
        if value:
            return value
    return ""


def candidate_identity(candidate: dict) -> dict:
    company = normalize_company(first_value(candidate, COMPANY_FIELDS))

    domains: set[str] = set()
    for field in DOMAIN_FIELDS:
        for value in split_values(candidate.get(field)):
            domain = normalize_domain(value)
            if domain:
                domains.add(domain)

    emails: set[str] = set()
    for field in EMAIL_FIELDS:
        for value in split_values(candidate.get(field)):
            email = normalize_email(value)
            if email:
                emails.add(email)

    lead_ids: set[str] = set()
    for field in LEAD_ID_FIELDS:
        for value in split_values(candidate.get(field)):
            lead_id = _text(value).casefold()
            if lead_id:
                lead_ids.add(lead_id)

    return {
        "company": company,
        "domains": domains,
        "emails": emails,
        "lead_ids": lead_ids,
    }


def load_registry(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        missing = REQUIRED_REGISTRY_HEADERS - headers
        if missing:
            raise ValueError("registry_missing_headers:" + ",".join(sorted(missing)))

        rows = []
        for row_number, row in enumerate(reader, start=2):
            if _text(row.get("exclude_from_new_leads")).casefold() not in TRUE_VALUES:
                continue
            identity = candidate_identity(
                {
                    "company": row.get("company"),
                    "website": row.get("website"),
                    "domain": row.get("domain"),
                    "emails": row.get("emails"),
                    "lead_ids": row.get("lead_ids"),
                }
            )
            if not any((identity["company"], identity["domains"], identity["emails"], identity["lead_ids"])):
                raise ValueError(f"registry_row_without_identity:{row_number}")
            rows.append(
                {
                    "identity": identity,
                    "status": _text(row.get("status")),
                    "row_number": row_number,
                }
            )

    if not rows:
        raise ValueError("registry_has_no_active_exclusions")
    return rows


def match_candidate(candidate: dict, registry_rows: list[dict]) -> dict | None:
    identity = candidate_identity(candidate)
    if not any((identity["company"], identity["domains"], identity["emails"], identity["lead_ids"])):
        raise ValueError("candidate_without_identity")

    for row in registry_rows:
        stored = row["identity"]
        matched_by: list[str] = []

        if identity["lead_ids"] & stored["lead_ids"]:
            matched_by.append("lead_id")
        if identity["emails"] & stored["emails"]:
            matched_by.append("email")
        if any(domains_match(a, b) for a in identity["domains"] for b in stored["domains"]):
            matched_by.append("domain")
        if identity["company"] and identity["company"] == stored["company"]:
            matched_by.append("company")

        if matched_by:
            return {
                "matched_by": matched_by,
                "registry_row": row["row_number"],
                "registry_status": row["status"],
            }
    return None


def run(registry_csv: Path, candidates_json: Path, output: Path) -> dict:
    registry_rows = load_registry(registry_csv)
    candidates = json.loads(candidates_json.read_text(encoding="utf-8"))
    if not isinstance(candidates, list):
        raise ValueError("candidates_json_must_be_array")
    if len(candidates) > 5000:
        raise ValueError("candidate_limit_exceeded")

    kept: list[dict] = []
    excluded: list[dict] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise ValueError(f"candidate_must_be_object:{index}")
        match = match_candidate(candidate, registry_rows)
        if match:
            excluded.append({"candidate": candidate, "dedupe_match": match})
        else:
            kept.append(candidate)

    result = {
        "status": "green",
        "registry_exclusion_count": len(registry_rows),
        "input_count": len(candidates),
        "excluded_count": len(excluded),
        "kept_count": len(kept),
        "excluded": excluded,
        "kept": kept,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry-csv", type=Path, required=True)
    parser.add_argument("--candidates-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = run(args.registry_csv, args.candidates_json, args.output)
    print(
        "DEDUPE_PREFLIGHT=green "
        f"registry={result['registry_exclusion_count']} "
        f"input={result['input_count']} excluded={result['excluded_count']} kept={result['kept_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
