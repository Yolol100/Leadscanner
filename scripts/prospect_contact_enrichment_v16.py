from __future__ import annotations

import prospect_contact_enrichment_campaign as campaign
from outreach_agent_prepare_v16 import qualification_evidence_ok

_ORIGINAL_CAMPAIGN_ELIGIBLE = campaign.campaign_eligible_prospects


def campaign_eligible_prospects(rows, existing_ids, limit):
    if campaign._target_agent_type == campaign.AUTO_TARGET:
        return _ORIGINAL_CAMPAIGN_ELIGIBLE(rows, existing_ids, limit)
    output = []
    for row in rows:
        candidate_id = str(row.get("candidate_id", "")).strip()
        if not candidate_id or candidate_id in existing_ids:
            continue
        if not str(row.get("website", "")).strip():
            continue
        qualification = campaign._qualification_by_id.get(candidate_id, {})
        if not qualification_evidence_ok(row, qualification, agent_type=campaign._target_agent_type):
            continue
        output.append(row)
        if len(output) >= limit:
            break
    return output


def run(mode: str | None = None):
    old = campaign.campaign_eligible_prospects
    campaign.campaign_eligible_prospects = campaign_eligible_prospects
    try:
        return campaign.run(mode)
    finally:
        campaign.campaign_eligible_prospects = old


def main() -> int:
    try:
        run()
    except (campaign.legacy.ContactDiscoveryError, RuntimeError, ValueError) as exc:
        print(f"CONTACT_ENRICHMENT_V16=blocked detail={exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
