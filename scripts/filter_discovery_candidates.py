from __future__ import annotations

import argparse
import json
from pathlib import Path

from extract_public_contacts import competitor_reason


OUTPUT_FIELDS = (
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
    "discovery_sources",
    "identity_status",
)


def _bounded_candidate(candidate: dict) -> dict:
    return {
        field: candidate.get(field)
        for field in OUTPUT_FIELDS
        if candidate.get(field) not in (None, "", [])
    }


def filter_discovery_candidates(payload: dict) -> dict:
    candidates = payload.get("candidates") or []
    if not isinstance(candidates, list):
        raise ValueError("candidates must be a list")

    source_counts = payload.get("source_counts") or {}
    overture_count = int(source_counts.get("overture_candidates") or 0)
    google_maps_count = int(source_counts.get("google_maps_candidates") or 0)
    source_candidate_count = overture_count + google_maps_count
    deduplicated_count = int(payload.get("candidate_count") or len(candidates))
    dropped_undedupeable_count = int(payload.get("dropped_undedupeable_count") or 0)
    duplicate_count = max(
        source_candidate_count - dropped_undedupeable_count - deduplicated_count,
        0,
    )

    kept: list[dict] = []
    excluded: list[dict] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        bounded = _bounded_candidate(candidate)
        bounded["identity_status"] = "needs_leads_verification"
        reason = competitor_reason(candidate)
        if reason:
            bounded["excluded_reason"] = reason
            excluded.append(bounded)
        else:
            kept.append(bounded)

    return {
        "schema_version": "webactueel-phase2-discovery/1.0",
        "sources": [
            "PDOK",
            "Overture Maps Places",
            "gosom/google-maps-scraper",
        ],
        "source_candidate_count": source_candidate_count,
        "deduplicated_candidate_count": deduplicated_count,
        "duplicate_count": duplicate_count,
        "dropped_undedupeable_count": dropped_undedupeable_count,
        "competitor_excluded_count": len(excluded),
        "candidate_count": len(kept),
        "candidates": kept,
        "excluded_competitors": excluded,
        "competitor_filter_scope": "discovery_hints_only",
        "safety": {
            "verification_performed": False,
            "contact_basis_evaluated": False,
            "copy_created": False,
            "draft_created": False,
            "email_send": False,
            "email_candidates_in_final_output": False,
        },
        "handoff": {
            "owner": "leads",
            "required_next_step": (
                "Verify official company/domain identity, official-site competitor status, "
                "language and public business email before outreach preparation."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = filter_discovery_candidates(payload)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        "PHASE2_DISCOVERY=green "
        f"source={result['source_candidate_count']} "
        f"deduped={result['deduplicated_candidate_count']} "
        f"duplicates={result['duplicate_count']} "
        f"competitors={result['competitor_excluded_count']} "
        f"candidates={result['candidate_count']} "
        "verification=false copy=false draft=false email_send=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
