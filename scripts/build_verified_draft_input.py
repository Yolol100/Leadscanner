from __future__ import annotations

import argparse
import json
from pathlib import Path

from extract_public_contacts import email_business_priority, valid_email
from prepare_growth_batch import stable_lead_id


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(value: object) -> str:
    return str(value or "").strip().casefold()


SECONDARY_SURFACE_MARKERS = (
    "werkenbij",
    "careers",
    "jobs",
    "vacature",
    "vacatures",
    "recruit",
)


def _is_secondary_surface(candidate: dict) -> bool:
    domain = _norm(candidate.get("official_domain_hint"))
    website = _norm(candidate.get("website_hint"))
    haystack = f"{domain} {website}"
    return domain.startswith("stores.") or any(marker in haystack for marker in SECONDARY_SURFACE_MARKERS)


def build_contacts(
    source_dirs: list[Path],
    inventory: dict,
    requested_count: int,
    excluded_companies: set[str] | None = None,
    excluded_domains: set[str] | None = None,
) -> dict:
    if not 1 <= requested_count <= 100:
        raise ValueError("requested_count must be 1-100")

    duplicate_inventory_ids = sorted(
        str(value).strip()
        for value in (inventory.get("duplicate_growth_lead_ids") or [])
        if str(value).strip()
    )
    duplicate_inventory_emails = sorted(
        _norm(value)
        for value in (inventory.get("duplicate_growth_emails") or [])
        if _norm(value)
    )
    if duplicate_inventory_ids or duplicate_inventory_emails:
        raise RuntimeError(
            "Mailbox growth inventory contains duplicate drafts; resolve duplicates before selection "
            f"(lead_ids={len(duplicate_inventory_ids)} emails={len(duplicate_inventory_emails)})"
        )

    existing_ids = {
        str(value).strip()
        for value in (inventory.get("growth_lead_ids") or [])
        if str(value).strip()
    }
    existing_emails = {
        _norm(value)
        for value in (inventory.get("growth_emails") or [])
        if _norm(value)
    }
    request_excluded_companies = {
        _norm(value) for value in (excluded_companies or set()) if _norm(value)
    }
    request_excluded_domains = {
        _norm(value).removeprefix("www.")
        for value in (excluded_domains or set())
        if _norm(value)
    }

    selected: list[dict] = []
    seen_emails: set[str] = set()
    seen_domains: set[str] = set()
    seen_lead_ids: set[str] = set()
    verified_ready_total = 0
    inventory_excluded = 0
    request_excluded = 0
    invalid_or_unmatched = 0

    for source_dir in source_dirs:
        ready_payload = load_json(source_dir / "verification-ready.json")
        contacts_payload = load_json(source_dir / "public-contacts.json")

        ready_company_domains: set[tuple[str, str]] = set()
        for row in ready_payload.get("ready_for_copy") or []:
            company = _norm(row.get("company"))
            domain = _norm(row.get("official_domain"))
            if company and domain:
                ready_company_domains.add((company, domain))
        verified_ready_total += len(ready_company_domains)

        source_candidates = []
        primary_companies: set[str] = set()
        for candidate in contacts_payload.get("candidates") or []:
            company = _norm(candidate.get("name_hint"))
            domain = _norm(candidate.get("official_domain_hint"))
            if not company or not domain or (company, domain) not in ready_company_domains:
                continue
            if company in request_excluded_companies or domain in request_excluded_domains:
                request_excluded += 1
                continue
            source_candidates.append(candidate)
            if not _is_secondary_surface(candidate):
                primary_companies.add(company)

        for candidate in source_candidates:
            company = _norm(candidate.get("name_hint"))
            domain = _norm(candidate.get("official_domain_hint"))
            if _is_secondary_surface(candidate) and company in primary_companies:
                invalid_or_unmatched += 1
                continue

            emails = list(candidate.get("public_business_emails") or [])
            valid_candidates = [
                (index, _norm(value))
                for index, value in enumerate(emails)
                if valid_email(_norm(value))
            ]
            if not valid_candidates:
                invalid_or_unmatched += 1
                continue
            chosen_index, email = min(
                valid_candidates,
                key=lambda item: (
                    email_business_priority(
                        item[1],
                        candidate.get("official_domain_hint"),
                        candidate.get("name_hint"),
                    ),
                    item[0],
                ),
            )

            candidate = dict(candidate)
            candidate["public_business_emails"] = [email]
            for key in ("email_source_urls", "email_source_types", "email_source_refs"):
                values = list(candidate.get(key) or [])
                candidate[key] = [values[chosen_index]] if chosen_index < len(values) else []

            website = str(candidate.get("website_hint") or "").strip()
            observation = str(candidate.get("verified_observation") or "").strip()
            observation_url = str(candidate.get("verified_observation_source_url") or "").strip()
            observation_type = str(candidate.get("verified_observation_source_type") or "").strip()
            language = _norm(candidate.get("language"))

            if (
                candidate.get("excluded_competitor")
                or candidate.get("contact_basis_status") != "review_required"
                or language not in {"nl", "en"}
                or not website
                or not observation
                or not observation_url
                or observation_type != "official_site"
            ):
                invalid_or_unmatched += 1
                continue

            lead_id = stable_lead_id(email, website)
            if lead_id in existing_ids or email in existing_emails:
                inventory_excluded += 1
                continue
            if email in seen_emails or domain in seen_domains or lead_id in seen_lead_ids:
                continue

            seen_emails.add(email)
            seen_domains.add(domain)
            seen_lead_ids.add(lead_id)
            selected.append(candidate)
            if len(selected) == requested_count:
                break

        if len(selected) == requested_count:
            break

    if len(selected) != requested_count:
        raise RuntimeError(
            f"Need exactly {requested_count} new verified prospects after mailbox inventory, found {len(selected)}"
        )

    return {
        "schema_version": "webactueel-verified-draft-input/1.0",
        "requested_count": requested_count,
        "selected_count": len(selected),
        "verified_ready_seen": verified_ready_total,
        "inventory_excluded_count": inventory_excluded,
        "request_excluded_count": request_excluded,
        "invalid_or_unmatched_count": invalid_or_unmatched,
        "candidates": selected,
        "safety": {
            "source_phase": "phase3_verified_ready",
            "existing_growth_ids_excluded": True,
            "existing_growth_emails_excluded": True,
            "mailbox_inventory_duplicate_free": True,
            "request_company_domain_exclusions_applied": True,
            "contact_basis_review_required": True,
            "automatic_send": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", action="append", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--requested-count", type=int, required=True)
    parser.add_argument("--exclude-company", action="append", default=[])
    parser.add_argument("--exclude-domain", action="append", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = build_contacts(
        [Path(value) for value in args.source_dir],
        load_json(Path(args.inventory)),
        args.requested_count,
        excluded_companies=set(args.exclude_company),
        excluded_domains=set(args.exclude_domain),
    )
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "VERIFIED_DRAFT_INPUT=green "
        f"requested={result['requested_count']} selected={result['selected_count']} "
        f"inventory_excluded={result['inventory_excluded_count']} "
        f"request_excluded={result['request_excluded_count']} "
        "automatic_send=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
