#!/usr/bin/env python3
"""Phase 15: build one compact run manifest for preview or draft execution."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load(path: str | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"manifest_input_must_be_object:{path}")
    return data


def build_manifest(
    *,
    mode: str,
    request: dict,
    filtered: dict,
    dedupe: dict,
    verified: dict,
    research: dict,
    reasons: dict,
    values: dict,
    mail: dict,
    draft_batch: dict,
    review_queue: dict | None = None,
    approved_batch: dict | None = None,
    draft_readback: dict | None = None,
    registry_update: dict | None = None,
) -> dict:
    if mode not in {"preview", "draft"}:
        raise ValueError("mode_must_be_preview_or_draft")

    review_queue = review_queue or {}
    approved_batch = approved_batch or {}
    draft_readback = draft_readback or {}
    registry_update = registry_update or {}
    draft_count = int(draft_batch.get("draft_candidate_count") or 0)
    review_queue_count = int(review_queue.get("review_candidate_count") or 0)
    approved_count = int((approved_batch.get("approval") or {}).get("approved_count") or 0)
    operator_rejected_count = int((approved_batch.get("approval") or {}).get("rejected_by_operator_count") or 0)

    if mode == "preview":
        if draft_readback or registry_update:
            raise ValueError("preview_must_not_include_mutation_results")
        closure = {
            "status": "preview_ready",
            "mailbox_mutation": False,
            "registry_mutation": False,
            "automatic_send": False,
            "smtp_send": "not_available",
        }
    else:
        if draft_count:
            if draft_readback.get("status") != "green":
                raise ValueError("draft_mode_requires_green_mailbox_readback")
            if registry_update.get("status") != "green":
                raise ValueError("draft_mode_requires_green_registry_update")
            if not registry_update.get("exact_readback"):
                raise ValueError("draft_mode_requires_exact_registry_readback")
        closure = {
            "status": "closed",
            "mailbox_mutation": bool(draft_count),
            "registry_mutation": bool(int(registry_update.get("appended_count") or 0)),
            "automatic_send": False,
            "smtp_send": "not_available",
        }

    return {
        "schema_version": "leadscanner-cold-run-manifest/1.0",
        "execution_mode": mode,
        "request": {
            "region": request.get("region"),
            "keywords": request.get("keywords") or [],
            "target_candidates": request.get("target_candidates"),
            "verify_limit": request.get("verify_limit"),
            "radius_km": request.get("radius_km"),
        },
        "counts": {
            "discovery_after_cheap_filters": int(filtered.get("candidate_count") or 0),
            "dedupe_kept": int(dedupe.get("kept_count") or 0),
            "verified_for_research": int(verified.get("ready_for_research_count") or 0),
            "research_ready": int(research.get("research_ready_count") or 0),
            "outreach_reason_ready": int(reasons.get("ready_count") or 0),
            "value_action_ready": int(values.get("ready_count") or 0),
            "mail_ready_for_human_review": int(mail.get("ready_for_human_review_count") or 0),
            "review_queue_candidates": review_queue_count,
            "approved_for_draft": approved_count,
            "operator_rejected": operator_rejected_count,
            "review_draft_candidates": draft_count,
            "draft_created": int(draft_readback.get("created_count") or 0),
            "draft_existing_exact": int(draft_readback.get("existing_count") or 0),
            "registry_appended": int(registry_update.get("appended_count") or 0),
            "registry_already_present": int(registry_update.get("already_present_count") or 0),
        },
        "safety": {
            "human_review_required": True,
            "automatic_send": False,
            "smtp_send": "not_available",
            "changed_existing_draft_policy": "reject",
            "historical_registry_role": "suppression_only",
        },
        "closure": closure,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("preview", "draft"))
    parser.add_argument("--request", required=True)
    parser.add_argument("--filtered", required=True)
    parser.add_argument("--dedupe", required=True)
    parser.add_argument("--verified", required=True)
    parser.add_argument("--research", required=True)
    parser.add_argument("--reasons", required=True)
    parser.add_argument("--values", required=True)
    parser.add_argument("--mail", required=True)
    parser.add_argument("--draft-batch", required=True)
    parser.add_argument("--review-queue")
    parser.add_argument("--approved-batch")
    parser.add_argument("--draft-readback")
    parser.add_argument("--registry-update")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = build_manifest(
        mode=args.mode,
        request=_load(args.request),
        filtered=_load(args.filtered),
        dedupe=_load(args.dedupe),
        verified=_load(args.verified),
        research=_load(args.research),
        reasons=_load(args.reasons),
        values=_load(args.values),
        mail=_load(args.mail),
        draft_batch=_load(args.draft_batch),
        review_queue=_load(args.review_queue),
        approved_batch=_load(args.approved_batch),
        draft_readback=_load(args.draft_readback),
        registry_update=_load(args.registry_update),
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    counts = result["counts"]
    print(
        "COLD_RUN_MANIFEST=green "
        f"mode={result['execution_mode']} "
        f"mail_ready={counts['mail_ready_for_human_review']} "
        f"draft_candidates={counts['review_draft_candidates']} "
        f"closure={result['closure']['status']} "
        "automatic_send=false smtp_send=not_available"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
