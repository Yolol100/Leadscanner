#!/usr/bin/env python3
from __future__ import annotations

import os

import prospect_contact_enrichment as legacy
from outreach_sender import get_values, rows_from_values
from prospect_agent_qualification import AGENT_QUALIFICATION_SHEET
from prospect_campaign_gate import AUTO_TARGET, normalize_target
from prospect_discovery import host_key, hosts_related

_original_eligible = legacy.eligible_prospects
_original_contact_output = legacy.contact_output
_qualification_by_id: dict[str, dict[str, str]] = {}
_target_agent_type = AUTO_TARGET


def _score(raw: object) -> int:
    try:
        return int(str(raw or "0").strip() or "0")
    except ValueError:
        return 0


def _draft_qualification_ok(candidate_status: str, q: dict[str, str]) -> bool:
    tier = str(q.get("tier", "")).strip().upper()
    q_status = str(q.get("status", "")).strip().casefold()
    candidate_status = str(candidate_status or "").strip().casefold()
    if _score(q.get("customer_potential")) < 6:
        return False
    if tier == "A":
        return q_status == "qualified" and candidate_status == "qualified"
    if tier == "B":
        return q_status == "hold" and candidate_status == "hold"
    return False


def campaign_eligible_prospects(rows, existing_ids, limit):
    if _target_agent_type == AUTO_TARGET:
        return _original_eligible(rows, existing_ids, limit)
    output = []
    for row in rows:
        candidate_id = str(row.get("candidate_id", "")).strip()
        if not candidate_id or candidate_id in existing_ids:
            continue
        if not str(row.get("website", "")).strip():
            continue
        q = _qualification_by_id.get(candidate_id, {})
        if not _draft_qualification_ok(str(row.get("status", "")), q):
            continue
        if str(q.get("offer_family", "")).strip().casefold() != "ai_agent":
            continue
        if str(q.get("agent_type", "")).strip().casefold() != _target_agent_type:
            continue
        output.append(row)
        if len(output) >= limit:
            break
    return output


def campaign_contact_output(row, *, fetch):
    output, is_ready = _original_contact_output(row, fetch=fetch)
    if is_ready:
        return output, True
    website = str(row.get("website", "")).strip()
    source_url = str(output.get("source_url", "")).strip()
    official_source = bool(
        website
        and source_url
        and host_key(website)
        and host_key(source_url)
        and hosts_related(host_key(website), host_key(source_url))
    )
    if (
        str(output.get("status", "")).strip().casefold() == "manual_review"
        and str(output.get("mx_status", "")).strip().casefold() == "present"
        and official_source
        and legacy.is_allowed_business_address(str(output.get("email", "")))
    ):
        output = dict(output)
        output["status"] = "ready"
        output["reason"] = "public business address found on the official site with MX present; external email domain accepted for draft review"
        return output, True
    return output, False


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
    legacy.contact_output = campaign_contact_output
    try:
        return legacy.run(effective_mode)
    finally:
        legacy.eligible_prospects = _original_eligible
        legacy.contact_output = _original_contact_output


def main() -> int:
    try:
        run()
    except (legacy.ContactDiscoveryError, RuntimeError, ValueError) as exc:
        print(f"CONTACT_ENRICHMENT=blocked detail={exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
