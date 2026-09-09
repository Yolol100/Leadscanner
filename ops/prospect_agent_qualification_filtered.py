from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import prospect_agent_qualification as base

_original_eligible = base._eligible_candidates


def _norm_set(raw: str) -> set[str]:
    return {part.strip().casefold() for part in (raw or "").split(",") if part.strip()}


def _parse_iso(raw: str) -> datetime | None:
    value = (raw or "").strip()
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def filtered_eligible(candidates, existing_by_id, *, force_recheck: bool, recheck_days: int):
    pool = _original_eligible(
        candidates,
        existing_by_id,
        force_recheck=force_recheck,
        recheck_days=recheck_days,
    )
    countries = _norm_set(os.getenv("TEMP_QUAL_COUNTRIES", ""))
    source_ids = _norm_set(os.getenv("TEMP_QUAL_SOURCE_IDS", ""))
    candidate_ids = _norm_set(os.getenv("TEMP_QUAL_CANDIDATE_IDS", ""))
    discovered_after = _parse_iso(os.getenv("TEMP_QUAL_DISCOVERED_AFTER", ""))

    output = []
    for row in pool:
        if countries and str(row.get("country", "")).strip().casefold() not in countries:
            continue
        if source_ids and str(row.get("source_id", "")).strip().casefold() not in source_ids:
            continue
        if candidate_ids and str(row.get("candidate_id", "")).strip().casefold() not in candidate_ids:
            continue
        if discovered_after is not None:
            raw = str(row.get("discovered_at", "")).strip()
            if not raw:
                continue
            try:
                discovered = _parse_iso(raw)
            except ValueError:
                continue
            if discovered is None or discovered < discovered_after:
                continue
        output.append(row)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="qualify", choices=["validate", "qualify"])
    parser.add_argument("--report", default="prospect-agent-qualification-filtered-report.json")
    args = parser.parse_args()
    base._eligible_candidates = filtered_eligible
    try:
        return base.run(args.mode, args.report)
    finally:
        base._eligible_candidates = _original_eligible


if __name__ == "__main__":
    raise SystemExit(main())
