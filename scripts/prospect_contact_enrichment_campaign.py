#!/usr/bin/env python3
from __future__ import annotations

import os

import prospect_contact_enrichment as legacy
from outreach_sender import get_values, rows_from_values
from prospect_agent_qualification import AGENT_QUALIFICATION_SHEET
from prospect_campaign_gate import AUTO_TARGET, normalize_target

_original_eligible = legacy.eligible_prospects
_qualification_by_id: dict[str, dict[str, str]] = {}
_target_agent_type = AUTO_TARGET


def campaign_eligible_prospects(rows, existing_ids, limit):
    base = _original_eligible(rows, existing_ids, max(limit * 5, limit))
    if _target_agent_type == AUTO_TARGET:
        return base[:limit]
    output = []
    for row in base:
        candidate_id = str(row.get("candidate_id", "")).strip()
        q = _qualification_by_id.get(candidate_id, {})
        if str(q.get("status", "")).strip().casefold() != "qualified":
            continue
        if str(q.get("tier", "")).strip().upper() != "A":
            continue
        if str(q.get("agent_type", "")).strip().casefold() != _target_agent_type:
            continue
        output.append(row)
        if len(output) >= limit:
            break
    return output


def run(mode: str | None = None):
    global _qualification_by_id, _target_agent_type
    effective_mode = (mode or os.getenv("CONTACT_ENRICHMENT_MODE", "validate")).strip().lower()
    _target_agent_type = normalize_target(
        os.getenv("AGENT_SALES_TARGET_TYPE", AUTO_TARGET),
        allow_auto=(effective_mode == "validate"),
    )
    if effective_mode == "discover":
        spreadsheet_id = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
        if not spreadsheet_id or not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
            return legacy.run(effective_mode)
        service = legacy.build_sheets_service()
        _, q_rows = rows_from_values(get_values(service, spreadsheet_id, AGENT_QUALIFICATION_SHEET))
        _qualification_by_id = {
            str(row.get("candidate_id", "")).strip(): {str(k): str(v or "") for k, v in row.items()}
            for row in q_rows
            if str(row.get("candidate_id", "")).strip()
        }
    legacy.eligible_prospects = campaign_eligible_prospects
    try:
        return legacy.run(effective_mode)
    finally:
        legacy.eligible_prospects = _original_eligible


def main() -> int:
    try:
        run()
    except (legacy.ContactDiscoveryError, RuntimeError, ValueError) as exc:
        print(f"CONTACT_ENRICHMENT=blocked detail={exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())