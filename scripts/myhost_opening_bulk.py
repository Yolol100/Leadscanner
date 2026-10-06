"""One-trigger orchestrator for bounded opening remediation shards."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from myhost_content_remediation import load_source_rows
from myhost_opening_remediation import run, validate_request
from opening_fastpath import audit_website_shards


def _selected_rows(req: dict, source_root: Path) -> list[dict]:
    rows = list(load_source_rows(source_root, req["source_artifact_ids"]).values())
    selected = rows[req["offset"]:req["offset"] + req["limit"]]
    if len(selected) != req["limit"]:
        raise ValueError("bulk source slice incomplete")
    return selected


def _split_rows(rows: list[dict], shard_size: int) -> list[list[dict]]:
    shards = [rows[start:start + shard_size] for start in range(0, len(rows), shard_size)]
    if any(not shard or len(shard) > 100 for shard in shards):
        raise ValueError("invalid bounded shard")
    return shards


def _shard_request(req: dict, rows: list[dict], absolute_offset: int) -> dict:
    ids = {row["lead_id"] for row in rows}
    result = {
        key: value
        for key, value in req.items()
        if key not in {"orchestrator", "shard_size", "observations", "holds"}
    }
    result["offset"] = absolute_offset
    result["limit"] = len(rows)
    if req.get("observations"):
        result["observations"] = {
            lead_id: value for lead_id, value in req["observations"].items() if lead_id in ids
        }
    if req.get("holds"):
        result["holds"] = {
            lead_id: value for lead_id, value in req["holds"].items() if lead_id in ids
        }
    return result


def _combine(req: dict, reports: list[dict]) -> dict:
    items = [item for report in reports for item in report.get("items", [])]
    combined = {
        "mode": req["mode"],
        "orchestrated": True,
        "shard_size": req.get("shard_size", 90),
        "shard_count": len(reports),
        "source_artifact_ids": req["source_artifact_ids"],
        "offset": req["offset"],
        "audited_count": len(items),
        "automatic_send": False,
        "send_capability": "unavailable",
        "read_only": req["mode"] != "apply",
        "shards": reports,
        "items": items,
        "website_network_rows": sum(r.get("website_network_rows", 0) for r in reports),
        "website_reused_rows": sum(r.get("website_reused_rows", 0) for r in reports),
        "final_mailbox_only": req["mode"] == "final",
    }
    for key in ("ready_count", "hold_count", "absent_count", "changed_count", "already_correct_count", "removed_count"):
        combined[key] = sum(int(report.get(key, 0)) for report in reports)
    combined["blockers"] = [blocker for report in reports for blocker in report.get("blockers", [])]
    return combined


def run_bulk(req: dict, source_root: Path, audit: dict | None = None) -> dict:
    req = validate_request(req)
    if req.get("orchestrator") is not True:
        raise ValueError("bulk runner requires orchestrator=true")
    rows = _selected_rows(req, source_root)
    shard_size = req.get("shard_size", 90)
    row_shards = _split_rows(rows, shard_size)
    shard_requests = []
    absolute_offset = req["offset"]
    for shard in row_shards:
        shard_requests.append(_shard_request(req, shard, absolute_offset))
        absolute_offset += len(shard)

    reports: list[dict] = []
    if req["mode"] == "audit":
        website_shards = audit_website_shards(row_shards)
        for shard_req, website_results in zip(shard_requests, website_shards):
            report = run(
                shard_req,
                source_root,
                None,
                precomputed_website_results=website_results,
            )
            report["website_network_rows"] = len(website_results)
            report["website_reused_rows"] = 0
            report["bulk_shared_url_cache"] = True
            reports.append(report)
    else:
        if not isinstance(audit, dict) or audit.get("orchestrated") is not True:
            raise ValueError("bulk apply/final requires immutable orchestrated audit")
        audit_shards = audit.get("shards") or []
        if len(audit_shards) != len(row_shards):
            raise ValueError("bulk audit shard count mismatch")
        for shard_req, shard_audit in zip(shard_requests, audit_shards):
            reports.append(run(shard_req, source_root, shard_audit))

    combined = _combine(req, reports)
    if combined["audited_count"] != req["limit"]:
        raise ValueError("bulk result count mismatch")
    return combined


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--audit")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    req = json.loads(Path(args.request).read_text())
    audit = json.loads(Path(args.audit).read_text()) if args.audit else None
    report = run_bulk(req, Path(args.source_root), audit)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        f"OPENING_BULK=green mode={report['mode']} audited={report['audited_count']} "
        f"shards={report['shard_count']} ready={report['ready_count']} hold={report['hold_count']} "
        f"absent={report['absent_count']} changed={report['changed_count']} "
        "automatic_send=false send_capability=unavailable"
    )
    return 1 if report["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
