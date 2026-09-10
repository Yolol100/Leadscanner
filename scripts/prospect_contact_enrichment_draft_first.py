#!/usr/bin/env python3
from __future__ import annotations

import os
import re

import prospect_contact_enrichment as legacy
from outreach_sender import get_values, rows_from_values
from prospect_agent_qualification import AGENT_CATALOG, AGENT_QUALIFICATION_SHEET

_original_eligible = legacy.eligible_prospects
_original_allowed = legacy.is_allowed_business_address
_original_definitive = legacy.definitive_contact_ids
_qualification_by_id: dict[str, dict[str, str]] = {}

BLOCKED_ROLE_TOKENS = {
    'noreply', 'no-reply', 'donotreply', 'do-not-reply', 'mailer-daemon',
    'postmaster', 'abuse', 'privacy', 'legal', 'billing', 'payroll',
    'hr', 'humanresources', 'human-resources', 'career', 'careers',
    'job', 'jobs', 'recruiting', 'recruitment', 'press', 'media',
}


def draft_allowed_business_address(raw: str) -> bool:
    address = legacy.normalize_email(raw)
    if not address or '@' not in address:
        return False
    local = address.rsplit('@', 1)[0].casefold()
    compact = re.sub(r'[^a-z0-9]+', '', local)
    blocked_compact = {re.sub(r'[^a-z0-9]+', '', item) for item in BLOCKED_ROLE_TOKENS}
    return local not in BLOCKED_ROLE_TOKENS and compact not in blocked_compact


def draft_definitive_contact_ids(rows):
    return {
        str(row.get('candidate_id', '')).strip()
        for row in rows
        if str(row.get('candidate_id', '')).strip()
        and str(row.get('status', '')).strip().casefold() in {'ready', 'manual_review', 'blocked'}
    }


def draft_eligible_prospects(rows, existing_ids, limit):
    output = []
    for row in rows:
        candidate_id = str(row.get('candidate_id', '')).strip()
        if not candidate_id or candidate_id in existing_ids:
            continue
        if str(row.get('status', '')).strip().casefold() not in {'qualified', 'hold'}:
            continue
        if not str(row.get('website', '')).strip():
            continue
        q = _qualification_by_id.get(candidate_id, {})
        if str(q.get('offer_family', '')).strip().casefold() != 'ai_agent':
            continue
        if str(q.get('tier', '')).strip().upper() not in {'A', 'B'}:
            continue
        if str(q.get('status', '')).strip().casefold() not in {'qualified', 'hold'}:
            continue
        agent_type = str(q.get('agent_type', '')).strip().casefold()
        if agent_type not in AGENT_CATALOG or agent_type == 'lead_reactivation':
            continue
        output.append(row)
        if len(output) >= limit:
            break
    return output


def run(mode: str | None = None):
    global _qualification_by_id
    effective_mode = (mode or os.getenv('CONTACT_ENRICHMENT_MODE', 'validate')).strip().lower()
    if effective_mode == 'discover':
        spreadsheet_id = os.getenv('OUTREACH_SPREADSHEET_ID', '').strip()
        if spreadsheet_id and os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON', '').strip():
            service = legacy.build_sheets_service()
            _, q_rows = rows_from_values(get_values(service, spreadsheet_id, AGENT_QUALIFICATION_SHEET))
            _qualification_by_id = {
                str(row.get('candidate_id', '')).strip(): {str(k): str(v or '') for k, v in row.items()}
                for row in q_rows if str(row.get('candidate_id', '')).strip()
            }
    legacy.eligible_prospects = draft_eligible_prospects
    legacy.is_allowed_business_address = draft_allowed_business_address
    legacy.definitive_contact_ids = draft_definitive_contact_ids
    try:
        return legacy.run(effective_mode)
    finally:
        legacy.eligible_prospects = _original_eligible
        legacy.is_allowed_business_address = _original_allowed
        legacy.definitive_contact_ids = _original_definitive


def main() -> int:
    try:
        run()
    except (legacy.ContactDiscoveryError, RuntimeError, ValueError) as exc:
        print(f'DRAFT_FIRST_CONTACT=blocked detail={exc}')
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
