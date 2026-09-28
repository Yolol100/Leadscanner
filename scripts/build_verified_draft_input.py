from __future__ import annotations

import argparse
import json
from pathlib import Path

from prepare_growth_batch import stable_lead_id


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(value: object) -> str:
    return str(value or "").strip().casefold()


def build_contacts(source_dirs: list[Path], inventory: dict, requested_count: int) -> dict:
    if not 1 <= requested_count <= 100:
        raise ValueError("requested_count must be 1-100")

    existing_ids = {
        str(value).strip()
        for value in (inventory.get("growth_lead_ids") or [])
        if str(value).strip()
    }

    selected: list[dict] = []
    seen_emails: set[str] = set()
    seen_domains: set[str] = set()
    seen_lead_ids: set[str] = set()
    verified_ready_total = 0
    inventory_excluded = 0
    invalid_or_unmatched = 0

    for source_dir in source_dirs:
        ready_payload = load_json(source_dir / "verification-ready.json")
        contacts_payload = load_json(source_dir / "public-contacts.json")

        ready_keys: set[tuple[str, str]] = set()
        for row in ready_payload.get("ready_for_copy") or []:
            email = _norm(row.get("email"))
            domain = _norm(row.get("official_domain"))
            if email and domain:
                ready_keys.add((email, domain))
        verified_ready_total += len(ready_keys)

        for candidate in contacts_payload.get("candidates") or []:
            emails = candidate.get("public_business_emails") or []
            email = _norm(emails[0] if emails else "")
            domain = _norm(candidate.get("official_domain_hint"))
            if not email or not domain or (email, domain) not in ready_keys:
                continue

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
            if lead_id in existing_ids:
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
        "invalid_or_unmatched_count": invalid_or_unmatched,
        "candidates": selected,
        "safety": {
            "source_phase": "phase3_verified_ready",
            "existing_growth_ids_excluded": True,
            "contact_basis_review_required": True,
            "automatic_send": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", action="append", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--requested-count", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = build_contacts(
        [Path(value) for value in args.source_dir],
        load_json(Path(args.inventory)),
        args.requested_count,
    )
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "VERIFIED_DRAFT_INPUT=green "
        f"requested={result['requested_count']} selected={result['selected_count']} "
        f"inventory_excluded={result['inventory_excluded_count']} "
        "automatic_send=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
