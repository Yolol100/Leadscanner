from __future__ import annotations

import sys

import outreach_daily_prepare_new as base
from outreach_agent_prepare_v16 import build_prepared_row, qualification_evidence_ok


def eligible(candidate, qualification, contact, *, agent_type: str, country: str, queued_ids: set[str], lead_statuses: dict[str, set[str]]) -> bool:
    candidate_id = base.text(candidate.get("candidate_id"))
    domain = base.canonical_domain(candidate.get("website"))
    if not candidate_id or candidate_id in queued_ids or not domain:
        return False
    statuses = lead_statuses.get(domain, set())
    if statuses and not statuses.issubset(base.ALLOWED_EXISTING_LEAD_STATUSES):
        return False
    if base.canonical_country(base.text(candidate.get("country"))) != country:
        return False
    if not qualification_evidence_ok(candidate, qualification, agent_type=agent_type):
        return False
    if base.text(contact.get("candidate_id")) != candidate_id:
        return False
    if base.text(contact.get("status")).casefold() not in {"ready", "manual_review"}:
        return False
    if base.text(contact.get("mx_status")).casefold() != "present":
        return False
    if not base._official_contact(candidate, contact):
        return False
    return True


def run() -> int:
    old_builder = base.build_prepared_row
    old_eligible = base.eligible
    base.build_prepared_row = build_prepared_row
    base.eligible = eligible
    try:
        return base.run()
    finally:
        base.build_prepared_row = old_builder
        base.eligible = old_eligible


def main() -> int:
    try:
        return run()
    except (RuntimeError, ValueError) as exc:
        print(f"DAILY_PREPARE_V16=blocked detail={exc} send_permission=none", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
