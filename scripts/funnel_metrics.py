#!/usr/bin/env python3
"""Build privacy-safe funnel diagnostics for one Leadscanner preview."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def _count(values) -> dict[str, int]:
    counter = Counter(str(v or "unknown") for v in values)
    return dict(sorted(counter.items()))


def _load(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"input_must_be_object:{path}")
    return data


def build_funnel(
    *,
    raw: dict,
    filtered: dict,
    dedupe: dict,
    verified: dict,
    research: dict,
    reasons: dict,
    mail: dict,
) -> dict:
    filter_excluded = filtered.get("excluded") or []
    dedupe_excluded = dedupe.get("excluded") or []
    verified_candidates = verified.get("candidates") or []
    research_candidates = research.get("candidates") or []
    reason_candidates = reasons.get("candidates") or []
    mail_candidates = mail.get("candidates") or []

    dedupe_matches = []
    for item in dedupe_excluded:
        for matched_by in ((item.get("dedupe_match") or {}).get("matched_by") or []):
            dedupe_matches.append(matched_by)

    verification_holds = [
        item.get("contact_status") or "unknown"
        for item in verified_candidates
        if not item.get("ready_for_research")
    ]
    research_holds = [
        item.get("research_status") or "unknown"
        for item in research_candidates
        if item.get("research_status") != "ready"
    ]
    outreach_holds = [
        item.get("outreach_hold_reason") or "unknown"
        for item in reason_candidates
        if item.get("outreach_status") != "ready"
    ]
    signal_types = [
        item.get("signal_type")
        for item in reason_candidates
        if item.get("outreach_status") == "ready" and item.get("signal_type")
    ]
    mail_holds = []
    for item in mail_candidates:
        if item.get("mail_status") == "ready_for_human_review":
            continue
        reasons_list = item.get("copy_validation_reasons") or ["unknown"]
        mail_holds.extend(reasons_list)

    counts = {
        "discovery_raw": int(raw.get("candidate_count") or 0),
        "after_cheap_filters": int(filtered.get("candidate_count") or 0),
        "after_dedupe": int(dedupe.get("kept_count") or 0),
        "verification_checked": int(verified.get("candidate_count") or 0),
        "verified_for_research": int(verified.get("ready_for_research_count") or 0),
        "research_checked": int(research.get("candidate_count") or 0),
        "research_ready": int(research.get("research_ready_count") or 0),
        "outreach_ready": int(reasons.get("ready_count") or 0),
        "mail_ready": int(mail.get("ready_for_human_review_count") or 0),
    }

    return {
        "schema_version": "leadscanner-funnel-metrics/1.0",
        "counts": counts,
        "drop_reasons": {
            "cheap_filter": _count(item.get("reason") for item in filter_excluded),
            "dedupe": _count(dedupe_matches),
            "verification": _count(verification_holds),
            "research": _count(research_holds),
            "outreach": _count(outreach_holds),
            "mail": _count(mail_holds),
        },
        "ready_signal_types": _count(signal_types),
        "privacy": {
            "contains_prospect_copy": False,
            "contains_email_addresses": False,
            "contains_company_names": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in ("raw", "filtered", "dedupe", "verified", "research", "reasons", "mail"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = build_funnel(
        raw=_load(args.raw),
        filtered=_load(args.filtered),
        dedupe=_load(args.dedupe),
        verified=_load(args.verified),
        research=_load(args.research),
        reasons=_load(args.reasons),
        mail=_load(args.mail),
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "FUNNEL_METRICS=green "
        f"raw={result['counts']['discovery_raw']} "
        f"verified={result['counts']['verified_for_research']} "
        f"outreach={result['counts']['outreach_ready']} "
        f"mail={result['counts']['mail_ready']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
