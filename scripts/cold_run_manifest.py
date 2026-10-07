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
    revalidation: dict | None = None,
    source_preview_snapshot: dict | None = None,
    funnel: dict | None = None,
    coverage: dict | None = None,
    draft_readback: dict | None = None,
    registry_update: dict | None = None,
) -> dict:
    if mode not in {"preview", "draft"}:
        raise ValueError("mode_must_be_preview_or_draft")

    review_queue = review_queue or {}
    approved_batch = approved_batch or {}
    revalidation = revalidation or {}
    source_preview_snapshot = source_preview_snapshot or {}
    funnel = funnel or {}
    coverage = coverage or {}
    draft_readback = draft_readback or {}
    registry_update = registry_update or {}
    draft_count = int(draft_batch.get("draft_candidate_count") or 0)
    review_queue_count = int(review_queue.get("review_candidate_count") or 0)
    approved_count = int((approved_batch.get("approval") or {}).get("approved_count") or 0)
    operator_rejected_count = int((approved_batch.get("approval") or {}).get("rejected_by_operator_count") or 0)
    suppressed_after_preview = int(revalidation.get("suppressed_after_preview_count") or 0)

    if mode == "draft":
        if approved_batch:
            if approved_count + operator_rejected_count != review_queue_count:
                raise ValueError("draft_mode_review_approval_count_mismatch")
        if revalidation:
            remaining_count = int(revalidation.get("remaining_count") or 0)
            if approved_count - suppressed_after_preview != draft_count or remaining_count != draft_count:
                raise ValueError("draft_mode_approval_revalidation_count_mismatch")

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
            mailbox_count = int(draft_readback.get("created_count") or 0) + int(
                draft_readback.get("existing_count") or 0
            )
            if mailbox_count != draft_count:
                raise ValueError("draft_mode_mailbox_count_mismatch")
            if registry_update.get("status") != "green":
                raise ValueError("draft_mode_requires_green_registry_update")
            if not registry_update.get("exact_readback"):
                raise ValueError("draft_mode_requires_exact_registry_readback")
            registry_count = int(registry_update.get("appended_count") or 0) + int(
                registry_update.get("already_present_count") or 0
            )
            if registry_count != draft_count:
                raise ValueError("draft_mode_registry_count_mismatch")
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
            "suppressed_after_preview": suppressed_after_preview,
            "review_draft_candidates": draft_count,
            "draft_created": int(draft_readback.get("created_count") or 0),
            "draft_existing_exact": int(draft_readback.get("existing_count") or 0),
            "registry_appended": int(registry_update.get("appended_count") or 0),
            "registry_already_present": int(registry_update.get("already_present_count") or 0),
        },
        "diagnostics": {
            "drop_reasons": funnel.get("drop_reasons") or {},
            "ready_signal_types": funnel.get("ready_signal_types") or {},
            "coverage_source_status": coverage.get("source_status"),
            "coverage_operational_pool_status": coverage.get("operational_pool_status"),
            "second_source_decision": coverage.get("second_source_decision"),
        },
        "provenance": {
            "source_preview_id": source_preview_snapshot.get("preview_id"),
            "source_preview_run_id": (source_preview_snapshot.get("source") or {}).get("run_id"),
            "source_preview_head_sha": (source_preview_snapshot.get("source") or {}).get("head_sha"),
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
    parser.add_argument("--request")
    parser.add_argument("--filtered")
    parser.add_argument("--dedupe")
    parser.add_argument("--verified")
    parser.add_argument("--research")
    parser.add_argument("--reasons")
    parser.add_argument("--values")
    parser.add_argument("--mail")
    parser.add_argument("--draft-batch", required=True)
    parser.add_argument("--review-queue")
    parser.add_argument("--approved-batch")
    parser.add_argument("--revalidation")
    parser.add_argument("--source-preview-manifest")
    parser.add_argument("--source-preview-snapshot")
    parser.add_argument("--funnel")
    parser.add_argument("--coverage")
    parser.add_argument("--draft-readback")
    parser.add_argument("--registry-update")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source_manifest = _load(args.source_preview_manifest)
    if args.mode == "preview":
        required_preview_paths = {
            "request": args.request,
            "filtered": args.filtered,
            "dedupe": args.dedupe,
            "verified": args.verified,
            "research": args.research,
            "reasons": args.reasons,
            "values": args.values,
            "mail": args.mail,
        }
        missing = [name for name, path in required_preview_paths.items() if not path]
        if missing:
            raise SystemExit("preview manifest missing inputs: " + ",".join(missing))
    if args.mode == "draft" and source_manifest:
        source_counts = source_manifest.get("counts") or {}
        request = source_manifest.get("request") or {}
        filtered = {"candidate_count": source_counts.get("discovery_after_cheap_filters", 0)}
        dedupe = {"kept_count": source_counts.get("dedupe_kept", 0)}
        verified = {"ready_for_research_count": source_counts.get("verified_for_research", 0)}
        research = {"research_ready_count": source_counts.get("research_ready", 0)}
        reasons = {"ready_count": source_counts.get("outreach_reason_ready", 0)}
        values = {"ready_count": source_counts.get("value_action_ready", 0)}
        mail = {"ready_for_human_review_count": source_counts.get("mail_ready_for_human_review", 0)}
    else:
        request = _load(args.request)
        filtered = _load(args.filtered)
        dedupe = _load(args.dedupe)
        verified = _load(args.verified)
        research = _load(args.research)
        reasons = _load(args.reasons)
        values = _load(args.values)
        mail = _load(args.mail)

    result = build_manifest(
        mode=args.mode,
        request=request,
        filtered=filtered,
        dedupe=dedupe,
        verified=verified,
        research=research,
        reasons=reasons,
        values=values,
        mail=mail,
        draft_batch=_load(args.draft_batch),
        review_queue=_load(args.review_queue),
        approved_batch=_load(args.approved_batch),
        revalidation=_load(args.revalidation),
        source_preview_snapshot=_load(args.source_preview_snapshot),
        funnel=_load(args.funnel),
        coverage=_load(args.coverage),
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
