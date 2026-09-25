from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def parse_lead_ids(raw: str) -> set[str]:
    return {
        item.strip()
        for item in re.split(r"[,;\n\r\s]+", raw or "")
        if item.strip()
    }


def approve_batch(batch: dict, approved_lead_ids: set[str]) -> dict:
    approved_count = 0
    rows = batch.get("rows") or []

    for row in rows:
        lead_id = str(row.get("lead_id") or "").strip()
        if lead_id not in approved_lead_ids:
            continue
        if row.get("excluded_competitor"):
            raise RuntimeError(f"Cannot approve excluded competitor {lead_id}")
        if not row.get("email") or not row.get("subject_preview") or not row.get("concept_preview"):
            raise RuntimeError(f"Cannot approve incomplete lead {lead_id}")

        row["contact_basis_status"] = "pass"
        row["contact_basis_hint"] = "explicit_reviewed_lead_id_approval"
        row["status"] = "draft_ready"
        row["subject"] = row["subject_preview"]
        row["body"] = row["concept_preview"]
        approved_count += 1

    unknown = approved_lead_ids - {
        str(row.get("lead_id") or "").strip()
        for row in rows
        if row.get("lead_id")
    }
    if unknown:
        raise RuntimeError(f"Unknown approved lead_ids: {', '.join(sorted(unknown))}")

    result = dict(batch)
    result["rows"] = rows
    result["draft_ready_count"] = sum(1 for row in rows if row.get("status") == "draft_ready")
    result["needs_contact_basis_count"] = sum(
        1 for row in rows if row.get("status") == "needs_contact_basis"
    )
    result["explicitly_approved_count"] = approved_count
    result["approval_mode"] = "explicit_reviewed_lead_ids"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--approved-lead-ids", required=True)
    args = parser.parse_args()

    batch = json.loads(Path(args.input).read_text(encoding="utf-8"))
    approved = parse_lead_ids(args.approved_lead_ids)
    if not approved:
        raise RuntimeError("At least one approved lead_id is required")
    result = approve_batch(batch, approved)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "LEAD_APPROVAL=green "
        f"approved={result['explicitly_approved_count']} "
        "mode=explicit_reviewed_lead_ids"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
