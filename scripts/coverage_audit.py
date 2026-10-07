#!/usr/bin/env python3
"""Assess whether Overture supplies enough candidates for the requested preview."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"input_must_be_object:{path}")
    return data


def build_coverage(*, request: dict, raw: dict, filtered: dict, dedupe: dict) -> dict:
    verify_limit = int(request.get("verify_limit") or 0)
    target = int(request.get("target_candidates") or 0)
    raw_count = int(raw.get("candidate_count") or 0)
    filtered_count = int(filtered.get("candidate_count") or 0)
    dedupe_count = int(dedupe.get("kept_count") or 0)

    if verify_limit <= 0 or target <= 0:
        raise ValueError("request_limits_must_be_positive")

    if target < verify_limit and raw_count >= target:
        source_status = "measurement_config_limited"
        decision = "increase_target_before_second_source"
    elif raw_count >= verify_limit * 2:
        source_status = "sufficient_buffer"
        decision = "second_source_not_needed"
    elif raw_count >= verify_limit:
        source_status = "sufficient"
        decision = "second_source_not_needed"
    elif raw_count >= max(5, (verify_limit + 1) // 2):
        source_status = "thin"
        decision = "broaden_query_before_second_source"
    else:
        source_status = "gap"
        decision = "repeat_gap_check_before_second_source"

    operational_status = "sufficient" if dedupe_count >= verify_limit else "thin"
    return {
        "schema_version": "leadscanner-overture-coverage/1.0",
        "scope": "operational_candidate_supply_not_market_completeness",
        "source": "Overture Maps Places",
        "request": {
            "region": request.get("region"),
            "keywords": request.get("keywords") or [],
            "target_candidates": target,
            "verify_limit": verify_limit,
            "radius_km": request.get("radius_km"),
        },
        "counts": {
            "overture_candidates": raw_count,
            "after_cheap_filters": filtered_count,
            "after_dedupe": dedupe_count,
        },
        "ratios": {
            "raw_to_verify_limit": round(raw_count / verify_limit, 3),
            "dedupe_to_verify_limit": round(dedupe_count / verify_limit, 3),
        },
        "source_status": source_status,
        "operational_pool_status": operational_status,
        "second_source_decision": decision,
        "rules": {
            "second_source_auto_added": False,
            "require_repeated_independent_gap_evidence": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--filtered", required=True)
    parser.add_argument("--dedupe", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build_coverage(
        request=_load(args.request),
        raw=_load(args.raw),
        filtered=_load(args.filtered),
        dedupe=_load(args.dedupe),
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "OVERTURE_COVERAGE=green "
        f"source_status={result['source_status']} "
        f"raw={result['counts']['overture_candidates']} "
        f"dedupe={result['counts']['after_dedupe']} "
        f"decision={result['second_source_decision']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
