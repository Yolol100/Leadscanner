#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Mapping, Sequence

from outreach_sender import build_sheets_service, ensure_expected_headers, get_values, rows_from_values
from prospect_agent_qualification import (
    AGENT_CATALOG,
    AGENT_QUALIFICATION_HEADERS,
    AGENT_QUALIFICATION_SHEET,
    PROSPECT_HEADERS,
    PROSPECT_SHEET,
)

AUTO_TARGET = "auto"


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_target(raw: object) -> str:
    value = _text(raw).casefold() or AUTO_TARGET
    if value != AUTO_TARGET and value not in AGENT_CATALOG:
        raise ValueError("AGENT_SALES_TARGET_TYPE must be auto or one of the six approved agent types")
    if value == "lead_reactivation" and os.getenv("AGENT_SALES_FIRST_PARTY_REACTIVATION", "").strip().casefold() not in {"1", "true", "yes", "on"}:
        raise ValueError("lead_reactivation campaign requires AGENT_SALES_FIRST_PARTY_REACTIVATION=true")
    return value


def apply_campaign_gate(
    candidates: Sequence[Mapping[str, object]],
    qualifications: Sequence[Mapping[str, object]],
    *,
    target_agent_type: str,
) -> tuple[list[dict[str, str]], dict[str, int | str]]:
    target = normalize_target(target_agent_type)
    output = [{str(k): str(v or "") for k, v in row.items()} for row in candidates]
    by_id = {
        _text(row.get("candidate_id")): row
        for row in qualifications
        if _text(row.get("candidate_id"))
    }
    matched = held = missing = 0
    if target == AUTO_TARGET:
        return output, {"target_agent_type": target, "matched": 0, "held": 0, "missing": 0}
    for row in output:
        if _text(row.get("status")).casefold() != "qualified":
            continue
        candidate_id = _text(row.get("candidate_id"))
        qualification = by_id.get(candidate_id)
        if not qualification:
            row["status"] = "hold"
            row["reason"] = f"campaign_gate_missing_qualification target={target}"
            missing += 1
            continue
        found = _text(qualification.get("agent_type")).casefold()
        q_status = _text(qualification.get("status")).casefold()
        q_tier = _text(qualification.get("tier")).upper()
        if q_status != "qualified" or q_tier != "A":
            row["status"] = "hold"
            row["reason"] = f"campaign_gate_not_a_qualified target={target}"
            held += 1
            continue
        if found != target:
            row["status"] = "hold"
            row["reason"] = f"campaign_mismatch target={target}; found={found or 'none'}"
            held += 1
            continue
        matched += 1
    return output, {"target_agent_type": target, "matched": matched, "held": held, "missing": missing}


def _replace_rows(service, spreadsheet_id: str, sheet: str, headers: Sequence[str], rows: Sequence[Mapping[str, object]]) -> None:
    values = [list(headers)] + [[str(row.get(header, "")) for header in headers] for row in rows]
    service.spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range=f"'{sheet}'!A:ZZ", body={}).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet}'!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def _write_report(path: str, payload: Mapping[str, object]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def run(mode: str, report_path: str) -> int:
    mode = (mode or "validate").strip().casefold()
    if mode not in {"validate", "apply"}:
        raise ValueError("mode must be validate or apply")
    target = normalize_target(os.getenv("AGENT_SALES_TARGET_TYPE", AUTO_TARGET))
    spreadsheet_id = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        raise ValueError("OUTREACH_SPREADSHEET_ID is required")
    if not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is required")
    service = build_sheets_service()
    candidate_headers, candidates = rows_from_values(get_values(service, spreadsheet_id, PROSPECT_SHEET))
    ensure_expected_headers(candidate_headers, PROSPECT_HEADERS, PROSPECT_SHEET)
    qualification_headers, qualifications = rows_from_values(get_values(service, spreadsheet_id, AGENT_QUALIFICATION_SHEET))
    ensure_expected_headers(qualification_headers, AGENT_QUALIFICATION_HEADERS, AGENT_QUALIFICATION_SHEET)
    if mode == "validate":
        payload = {"mode": mode, "status": "ready", "target_agent_type": target, "send_permission": "none"}
        _write_report(report_path, payload)
        print(f"PROSPECT_CAMPAIGN_GATE=validated target={target} send_permission=none")
        return 0
    updated_rows, stats = apply_campaign_gate(candidates, qualifications, target_agent_type=target)
    _replace_rows(service, spreadsheet_id, PROSPECT_SHEET, PROSPECT_HEADERS, updated_rows)
    payload = {"mode": mode, "status": "completed", **stats, "send_permission": "none"}
    _write_report(report_path, payload)
    print("PROSPECT_CAMPAIGN_GATE=complete " + " ".join(f"{k}={v}" for k, v in stats.items()))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed campaign target gate for AI agent prospecting.")
    parser.add_argument("--mode", default=os.getenv("PROSPECT_CAMPAIGN_GATE_MODE", "validate"), choices=["validate", "apply"])
    parser.add_argument("--report", default="prospect-campaign-gate-report.json")
    args = parser.parse_args(argv)
    try:
        return run(args.mode, args.report)
    except (RuntimeError, ValueError) as exc:
        _write_report(args.report, {"mode": args.mode, "status": "blocked", "error": str(exc), "send_permission": "none"})
        print(f"PROSPECT_CAMPAIGN_GATE=blocked detail={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())