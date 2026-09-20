from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from urllib.parse import urlparse

MAX_REQUESTED_ELIGIBLE = 100
MAX_DISCOVERY_BATCH = 100
MAX_REFILL_ATTEMPTS = 50
MAX_TIME_BUDGET_SECONDS = 14_400
MAX_SEEN_CANDIDATES = 10_000


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


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


def _candidate_keys(candidate: dict) -> set[str]:
    keys: set[str] = set()
    overture_id = str(candidate.get("overture_id") or "").strip()
    if overture_id:
        keys.add(f"overture:{overture_id}")

    for field in ("official_domain", "final_url", "website_hint"):
        domain = _normalize_domain(candidate.get(field))
        if domain:
            keys.add(f"domain:{domain}")

    verified_name = candidate.get("verified_company_name")
    normalized_name = _normalize_text(verified_name)
    if normalized_name:
        keys.add(f"company:{normalized_name}")
    return keys


def _safe_candidate(candidate: dict) -> dict:
    allowed = {
        "overture_id",
        "name_hint",
        "category_hint",
        "website_hint",
        "longitude",
        "latitude",
        "confidence",
        "website_probe",
    }
    safe = {key: candidate.get(key) for key in allowed if key in candidate}
    safe["identity_status"] = "needs_leads_verification"
    return safe


def dedupe_candidate_hints(candidate_hints: list[dict], seen_candidates: list[dict]) -> dict:
    seen_keys: set[str] = set()
    for candidate in seen_candidates:
        seen_keys.update(_candidate_keys(candidate))

    accepted: list[dict] = []
    dropped_duplicate_count = 0
    undedupeable_count = 0

    for candidate in candidate_hints:
        if not isinstance(candidate, dict):
            continue
        keys = _candidate_keys(candidate)
        if not keys:
            undedupeable_count += 1
            continue
        if keys & seen_keys:
            dropped_duplicate_count += 1
            continue
        safe = _safe_candidate(candidate)
        accepted.append(safe)
        seen_keys.update(keys)

    return {
        "unique_candidates": accepted,
        "unique_count": len(accepted),
        "dropped_duplicate_count": dropped_duplicate_count,
        "undedupeable_count": undedupeable_count,
    }


def _recommended_batch_size(
    *,
    needed: int,
    eligible_count: int,
    evaluated_count: int,
    previous_batch_size: int,
) -> int:
    if needed <= 0:
        return 0

    if evaluated_count > 0 and eligible_count > 0:
        yield_rate = max(min(eligible_count / evaluated_count, 1.0), 0.01)
        raw = math.ceil((needed / yield_rate) * 1.10)
    else:
        baseline = previous_batch_size * 2 if previous_batch_size else needed
        raw = max(needed, baseline)

    return max(1, min(MAX_DISCOVERY_BATCH, raw))


def plan_refill(state: dict) -> dict:
    requested = int(state.get("requested_eligible_count", 0))
    eligible = int(state.get("eligible_count", 0))
    evaluated = int(state.get("evaluated_count", 0))
    attempt = int(state.get("attempt", 0))
    max_attempts = int(state.get("max_attempts", 10))
    elapsed = float(state.get("elapsed_seconds", 0))
    time_budget = float(state.get("time_budget_seconds", 7_200))
    previous_batch_size = int(state.get("previous_batch_size", 0))
    source_exhausted = state.get("source_exhausted", False)
    candidate_hints = state.get("candidate_hints") or []
    seen_candidates = state.get("seen_candidates") or []

    if not 1 <= requested <= MAX_REQUESTED_ELIGIBLE:
        raise ValueError(f"requested_eligible_count must be 1-{MAX_REQUESTED_ELIGIBLE}")
    if eligible < 0 or evaluated < 0 or attempt < 0 or previous_batch_size < 0:
        raise ValueError("counts must be non-negative")
    if eligible > requested:
        raise ValueError("eligible_count cannot exceed requested_eligible_count")
    if not 1 <= max_attempts <= MAX_REFILL_ATTEMPTS:
        raise ValueError(f"max_attempts must be 1-{MAX_REFILL_ATTEMPTS}")
    if not 1 <= time_budget <= MAX_TIME_BUDGET_SECONDS:
        raise ValueError(f"time_budget_seconds must be 1-{MAX_TIME_BUDGET_SECONDS}")
    if not isinstance(source_exhausted, bool):
        raise ValueError("source_exhausted must be boolean")
    if not isinstance(candidate_hints, list) or len(candidate_hints) > MAX_DISCOVERY_BATCH:
        raise ValueError(f"candidate_hints must contain at most {MAX_DISCOVERY_BATCH} items")
    if not isinstance(seen_candidates, list) or len(seen_candidates) > MAX_SEEN_CANDIDATES:
        raise ValueError(f"seen_candidates must contain at most {MAX_SEEN_CANDIDATES} items")

    needed = requested - eligible
    dedupe = dedupe_candidate_hints(candidate_hints, seen_candidates)

    base = {
        "schema_version": "webactueel-refill-plan/1.0",
        "requested_eligible_count": requested,
        "eligible_count": eligible,
        "remaining_eligible_count": needed,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "elapsed_seconds": elapsed,
        "time_budget_seconds": time_budget,
        "source_exhausted": source_exhausted,
        "unique_candidates": dedupe["unique_candidates"],
        "unique_candidate_count": dedupe["unique_count"],
        "dropped_duplicate_count": dedupe["dropped_duplicate_count"],
        "undedupeable_count": dedupe["undedupeable_count"],
        "safety": {
            "owner_decides_eligibility": "leads",
            "candidate_hints_are_not_prospect_claims": True,
            "identity_verification_required": True,
            "contact_basis_not_evaluated": True,
            "draftqueue_write": False,
            "email_send": False,
            "gates_relaxed_to_hit_target": False,
            "dedupe_basis": [
                "overture_id",
                "normalized_domain",
                "verified_company_name_only",
            ],
        },
    }

    if needed == 0:
        return {
            **base,
            "status": "complete",
            "next_action": "stop",
            "next_discovery_count": 0,
            "reason": "requested eligible count reached",
        }

    if elapsed >= time_budget:
        return {
            **base,
            "status": "time_exhausted",
            "next_action": "stop",
            "next_discovery_count": 0,
            "reason": "time budget exhausted without relaxing eligibility gates",
        }

    if dedupe["unique_count"] > 0:
        return {
            **base,
            "status": "evaluate_batch",
            "next_action": "leads_verify_identity_and_run_existing_gates",
            "next_discovery_count": 0,
            "reason": "new unique candidate hints require owner evaluation before another refill",
        }

    if source_exhausted:
        return {
            **base,
            "status": "source_exhausted",
            "next_action": "stop",
            "next_discovery_count": 0,
            "reason": "authorized discovery source exhausted",
        }

    if attempt >= max_attempts:
        return {
            **base,
            "status": "attempt_exhausted",
            "next_action": "stop",
            "next_discovery_count": 0,
            "reason": "bounded refill attempt limit reached",
        }

    next_count = _recommended_batch_size(
        needed=needed,
        eligible_count=eligible,
        evaluated_count=evaluated,
        previous_batch_size=previous_batch_size,
    )
    return {
        **base,
        "status": "refill",
        "next_action": "discover_more_candidates",
        "next_discovery_count": next_count,
        "reason": "eligible target not reached; request another bounded discovery batch",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    try:
        state = json.loads(Path(args.state).read_text(encoding="utf-8"))
        result = plan_refill(state)
    except Exception as exc:
        print(f"REFILL_PLAN=blocked detail={exc}")
        return 2

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "REFILL_PLAN=green "
        f"status={result['status']} remaining={result['remaining_eligible_count']} "
        f"next_discovery_count={result['next_discovery_count']} "
        "draftqueue_write=false email_send=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
