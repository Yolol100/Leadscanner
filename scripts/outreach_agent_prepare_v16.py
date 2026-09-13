from __future__ import annotations

import json
import os

import outreach_agent_prepare_v2 as legacy
from outreach_copy_preflight import followup_copy_errors, initial_copy_errors
from outreach_site_personalization_v16 import personalize_from_evidence
from prospect_agent_qualification import AGENT_CATALOG

COPY_CONTRACT = "evidence_personalized_v16"
NET_NEW_AGENTS = {"front_desk_sales", "quote_intake", "review_concierge", "customer_support", "commerce"}

SUBJECT_NL = {
    "front_desk_sales": "Eerste aanvragen",
    "quote_intake": "Offerte aanvragen",
    "customer_support": "Klantvragen opvangen",
    "commerce": "Productvragen opvangen",
    "review_concierge": "Reviewopvolging verbeteren",
}
SUBJECT_EN = {
    "front_desk_sales": "First enquiries",
    "quote_intake": "Quote requests",
    "customer_support": "Customer questions",
    "commerce": "Product questions",
    "review_concierge": "Review follow-up",
}


def _text(value: object) -> str:
    return legacy.legacy._text(value)


def _score(value: object) -> int:
    try:
        return int(_text(value) or "0")
    except ValueError:
        return 0


def qualification_evidence_ok(candidate, qualification, *, agent_type: str | None = None) -> bool:
    candidate_id = _text(candidate.get("candidate_id"))
    if not candidate_id or _text(qualification.get("candidate_id")) != candidate_id:
        return False
    found_agent = _text(qualification.get("agent_type")).casefold()
    if found_agent not in NET_NEW_AGENTS or found_agent not in AGENT_CATALOG:
        return False
    if agent_type and found_agent != _text(agent_type).casefold():
        return False
    if _text(qualification.get("offer_family")).casefold() != "ai_agent":
        return False
    if _score(qualification.get("agent_opportunity_score")) < 2:
        return False
    required = ("evidence_url", "fact", "idea", "business_process")
    if any(not _text(qualification.get(field)) for field in required):
        return False
    reason = _text(qualification.get("reason")).casefold()
    candidate_reason = _text(candidate.get("reason")).casefold()
    blocked_markers = (
        "source_semantic_target_policy",
        "agency/provider target policy blocked",
        "fetch/evidence unavailable",
        "first_party_reactivation_evidence_required",
    )
    if any(marker in reason or marker in candidate_reason for marker in blocked_markers):
        return False
    return True


def _copy_with_value(*, company: str, country: str, fact: str, value: str, agent_type: str, postal_address: str = ""):
    company = legacy.legacy._mail_name(company)
    fact = _text(fact)
    value = _text(value)
    agent_type = _text(agent_type).casefold()
    if not company or not fact or not value or agent_type not in NET_NEW_AGENTS:
        raise ValueError("company, evidence-bound fact/value and approved net-new agent_type are required")
    language = legacy.legacy._language(country)
    variant = legacy._cta_variant()
    website = legacy._sender_website()
    if language == "nl":
        subject = SUBJECT_NL[agent_type]
        cta = (
            f"Zal ik een kort voorbeeld sturen van hoe dat er voor {company} uit kan zien?"
            if variant == "A"
            else f"Zal ik dat korte voorbeeld voor {company} sturen?"
        )
        body = (
            "Beste team,\n\n"
            f"{fact}\n\n"
            f"Voor jullie zou dat bijvoorbeeld kunnen betekenen: {value}.\n\n"
            f"{cta}\n\n"
            "Geen interesse? Een kort \"nee\" is genoeg.\n\n"
            "Dit is een commercieel bericht.\n\n"
            f"Met vriendelijke groet,\nAndrew Baeten\n{website}"
        )
        followup = (
            "Beste team,\n\n"
            f"Ik kom hier nog één keer op terug. Ik heb het korte voorbeeld voor {company} nog liggen.\n\n"
            f"{cta}\n\n"
            "Geen interesse? Een kort \"nee\" is genoeg.\n\n"
            "Met vriendelijke groet,\nAndrew Baeten"
        )
    else:
        subject = SUBJECT_EN[agent_type]
        cta = (
            f"Would it be useful if I sent over a short example of how that could work for {company}?"
            if variant == "A"
            else f"Want me to send over that short example for {company}?"
        )
        signature = "Best regards,\nAndrew Baeten"
        if legacy.legacy.canonical_country(country) == "US":
            if not _text(postal_address):
                raise ValueError("OUTREACH_POSTAL_ADDRESS is required to prepare US commercial copy")
            signature += f"\n{legacy.POSTAL_PLACEHOLDER}"
        signature += f"\n{website}"
        body = (
            "Hi team,\n\n"
            f"{fact}\n\n"
            f"For you, that could mean: {value}.\n\n"
            f"{cta}\n\n"
            "Not interested? A quick \"no\" is enough.\n\n"
            "This is a commercial message.\n\n"
            f"{signature}"
        )
        followup = (
            "Hi team,\n\n"
            f"Just following up once. I still have the short example for {company} ready.\n\n"
            f"{cta}\n\n"
            "Not interested? A quick \"no\" is enough.\n\n"
            "Best regards,\nAndrew Baeten"
        )
    errors = initial_copy_errors(subject, body) + followup_copy_errors(followup)
    if errors:
        raise ValueError("generated copy violates LeadPromo v16: " + "; ".join(errors[:5]))
    return subject, body, "", followup, 4


def build_prepared_row(candidate, qualification, contact, **kwargs):
    if not qualification_evidence_ok(candidate, qualification):
        raise ValueError("draft preparation requires evidence-bound net-new agent/process qualification")

    actual_tier = _text(qualification.get("tier")) or "EVIDENCE"
    actual_potential = _text(qualification.get("customer_potential")) or "0"
    legacy_candidate = dict(candidate)
    legacy_qualification = dict(qualification)
    legacy_contact = legacy._contact_for_legacy(candidate, contact)

    # The legacy row constructor still carries the retired score gate. Satisfy it
    # only inside that constructor, then restore the real evidence/tier metadata.
    legacy_candidate["status"] = "qualified"
    legacy_qualification["tier"] = "A"
    legacy_qualification["status"] = "qualified"
    legacy_qualification["customer_potential"] = "8"

    row = legacy._with_legacy_v2_globals(
        legacy._original_build_prepared_row,
        legacy_candidate,
        legacy_qualification,
        legacy_contact,
        **kwargs,
    )
    source = str(row.get("source", ""))
    if not source.startswith("agent_offer:"):
        raise ValueError("prepared row must contain agent_offer evidence")
    metadata = json.loads(source.split(":", 1)[1])
    found = _text(qualification.get("agent_type")).casefold()
    target = os.getenv("AGENT_SALES_TARGET_TYPE", "auto").strip().casefold() or "auto"
    if target not in {"auto", found}:
        raise ValueError(f"campaign target mismatch: target={target} found={found}")

    company = str(candidate.get("company", ""))
    country = str(candidate.get("country", ""))
    language = legacy.legacy._language(country)
    evidence_url = _text(qualification.get("evidence_url")) or _text(metadata.get("evidence_url")) or _text(candidate.get("website"))
    personalization = personalize_from_evidence(
        company=company,
        agent_type=found,
        language=language,
        evidence_url=evidence_url,
    )

    metadata["automation"] = "agent_sales_prepare_v16"
    metadata["campaign_target_agent_type"] = found if target == "auto" else target
    metadata["qualification_tier"] = actual_tier
    metadata["customer_potential"] = actual_potential
    metadata["fact"] = personalization.observation
    metadata["idea"] = personalization.value
    metadata["evidence_url"] = personalization.evidence_url
    metadata["value_asset_type"] = "process_example"
    metadata["value_asset_status"] = "concept_ready"
    metadata["value_asset_summary"] = personalization.value
    metadata["personalization_anchor"] = personalization.anchor
    metadata["personalization_process_label"] = personalization.process_label
    metadata["personalization_evidence_url"] = personalization.evidence_url
    metadata["cta_variant"] = legacy._cta_variant()
    metadata["copy_contract"] = COPY_CONTRACT

    subject, body, followup_subject, followup_body, delay = _copy_with_value(
        company=company,
        country=country,
        fact=personalization.observation,
        value=personalization.value,
        agent_type=found,
        postal_address=str(kwargs.get("postal_address", "")),
    )
    row["subject"] = subject
    row["body"] = body
    row["followup_subject"] = followup_subject
    row["followup_body"] = followup_body
    row["followup_delay_days"] = str(delay)
    row["source"] = "agent_offer:" + json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    return row
