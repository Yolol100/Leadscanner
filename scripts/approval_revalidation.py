#!/usr/bin/env python3
"""Phase 21: re-check approved preview leads against the live dedupe registry."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from dedupe_preflight import load_registry, match_candidate

MAX_APPROVALS = 100


def revalidate_approved(batch: dict, registry_rows: list[dict]) -> dict:
    rows = batch.get("rows") or []
    approval = batch.get("approval") or {}
    if not isinstance(rows, list):
        raise ValueError("approved_rows_must_be_list")
    if len(rows) > MAX_APPROVALS:
        raise ValueError("approval_limit_exceeded")
    if int(approval.get("approved_count") or len(rows)) != len(rows):
        raise ValueError("approved_count_mismatch")

    remaining: list[dict] = []
    suppressed: list[dict] = []
    seen_lead_ids: set[str] = set()

    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("approved_row_must_be_object")
        lead_id = str(row.get("lead_id") or "").strip()
        if not lead_id or lead_id in seen_lead_ids:
            raise ValueError("missing_or_duplicate_approved_lead_id")
        seen_lead_ids.add(lead_id)

        candidate = {
            "company": row.get("company"),
            "official_domain": row.get("official_domain"),
            "website": row.get("website"),
            "email": row.get("email"),
            "lead_id": lead_id,
        }
        match = match_candidate(candidate, registry_rows)
        if match:
            suppressed.append({
                "lead_id": lead_id,
                "company": row.get("company"),
                "email": row.get("email"),
                "dedupe_match": match,
            })
        else:
            remaining.append(row)

    return {
        "schema_version": "leadscanner-approved-revalidation/1.0",
        "status": "green",
        "input_approved_count": len(rows),
        "remaining_count": len(remaining),
        "suppressed_after_preview_count": len(suppressed),
        "suppressed_after_preview": suppressed,
        "rows": remaining,
        "approval": {
            **approval,
            "approved_before_revalidation": len(rows),
            "eligible_after_revalidation": len(remaining),
            "suppressed_after_preview_count": len(suppressed),
            "automatic_send": False,
        },
        "safety": {
            "automatic_send": False,
            "smtp_available": False,
            "historical_registry_role": "suppression_only",
            "dedupe_rechecked_immediately_before_mutation": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", required=True)
    parser.add_argument("--registry-csv", type=Path, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    batch = json.loads(Path(args.batch).read_text(encoding="utf-8"))
    registry = load_registry(args.registry_csv)
    result = revalidate_approved(batch, registry)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "APPROVAL_DEDUPE_REVALIDATION=green "
        f"approved={result['input_approved_count']} "
        f"remaining={result['remaining_count']} "
        f"suppressed_after_preview={result['suppressed_after_preview_count']} "
        "automatic_send=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
