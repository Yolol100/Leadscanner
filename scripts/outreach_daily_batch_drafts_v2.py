#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import Mapping

import outreach_daily_batch_drafts as base
from prospect_target_policy import canonical_country


_ORIGINAL_CANDIDATE_ERRORS = base.candidate_errors


def hardened_role_is_usable(address: str) -> bool:
    address = base._email(address)
    if "@" not in address:
        return False
    local = address.rsplit("@", 1)[0].casefold()
    compact = re.sub(r"[^a-z0-9]+", "", local)
    tokens = {token for token in re.split(r"[^a-z0-9]+", local) if token}
    blocked_compact = {re.sub(r"[^a-z0-9]+", "", item) for item in base.ROLE_MISMATCH_LOCAL_PARTS}
    blocked_tokens = {
        "hr", "humanresources", "careers", "career", "jobs", "job", "recruiting",
        "recruitment", "recruiter", "privacy", "legal", "billing", "payroll", "press",
        "media", "webmaster", "abuse", "postmaster",
    }
    if compact in blocked_compact or tokens.intersection(blocked_tokens):
        return False
    if compact.endswith("hr") and len(compact) <= 32:
        return False
    return True


def hardened_candidate_errors(
    queue_row: Mapping[str, object], *, agent_type: str, country: str,
    candidate: Mapping[str, object], qualification: Mapping[str, object], contact: Mapping[str, object],
    source: Mapping[str, object], lead_statuses: set[str], suppressed_emails: set[str], suppressed_domains: set[str],
) -> list[str]:
    errors = _ORIGINAL_CANDIDATE_ERRORS(
        queue_row,
        agent_type=agent_type,
        country=country,
        candidate=candidate,
        qualification=qualification,
        contact=contact,
        source=source,
        lead_statuses=lead_statuses,
        suppressed_emails=suppressed_emails,
        suppressed_domains=suppressed_domains,
    )
    queue_country = canonical_country(base._text(queue_row.get("country")))
    source_country = canonical_country(base._text(source.get("country"))) if source else ""
    if source_country and source_country != queue_country:
        errors.append("prospect source country conflicts with campaign")
    return errors


base._role_is_usable = hardened_role_is_usable
base.candidate_errors = hardened_candidate_errors


def main(argv=None) -> int:
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
