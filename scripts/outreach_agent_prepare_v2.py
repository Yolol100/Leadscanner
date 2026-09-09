#!/usr/bin/env python3
from __future__ import annotations

import json
import os

import outreach_agent_prepare as legacy
from outreach_copy_preflight import followup_copy_errors, initial_copy_errors
from outreach_site_personalization import personalize_from_evidence
from prospect_agent_qualification import AGENT_CATALOG
from prospect_target_policy import canonical_country

AUTOMATION_ID = "agent_sales_prepare_v2"
COPY_CONTRACT = "evidence_personalized_v13_5"
POSTAL_PLACEHOLDER = legacy.POSTAL_PLACEHOLDER
_original_build_prepared_row = legacy.build_prepared_row

SUBJECT_NL = {
    "front_desk_sales": "Afspraken bij {company}",
    "quote_intake": "Offerteaanvragen bij {company}",
    "customer_support": "Klantvragen bij {company}",
    "commerce": "Productvragen bij {company}",
    "review_concierge": "Reviews bij {company}",
    "lead_reactivation": "Opvolging bij {company}",
}
SUBJECT_EN = {
    "front_desk_sales": "Appointments at {company}",
    "quote_intake": "Quote requests at {company}",
    "customer_support": "Customer questions at {company}",
    "commerce": "Product questions at {company}",
    "review_concierge": "Reviews at {company}",
    "lead_reactivation": "Follow-up at {company}",
}

# These values are used only by the legacy row constructor before the v13.5
# evidence-personalization pass replaces fact, idea and final copy.
PROVISIONAL_VALUE_NL = {
    "front_desk_sales": "eerste vragen worden opgevangen, relevante gegevens worden verzameld en geschikte aanvragen kunnen naar het team of de bestaande afspraakroute worden doorgestuurd",
    "quote_intake": "klanten beantwoorden een paar gerichte vragen, ontbrekende gegevens worden aangevuld en het team krijgt een completere aanvraag om te beoordelen",
    "customer_support": "veelvoorkomende vragen krijgen antwoord uit goedgekeurde informatie en complexere vragen komen met context bij het team terecht",
    "commerce": "bezoekers krijgen hulp bij productvragen en kunnen daarna doorgaan via de bestaande shop- of orderroute",
    "review_concierge": "na een passende afgeronde klantactie kan een reviewverzoek worden gestart met maximaal een goedgekeurde follow-up",
    "lead_reactivation": "alleen een goedgekeurde lijst met eerdere leads wordt benaderd en geïnteresseerden worden terug naar sales geleid",
}
PROVISIONAL_VALUE_EN = {
    "front_desk_sales": "first questions are handled, relevant details are collected, and suitable enquiries can continue to the team or existing booking path",
    "quote_intake": "customers answer a few focused questions, missing details are collected, and the team receives a more complete request to review",
    "customer_support": "common questions are answered from approved information while more complex requests reach the team with context",
    "commerce": "visitors get help with product questions and can then continue through the existing shop or order path",
    "review_concierge": "after a relevant completed customer action, a review request can be started with at most one approved follow-up",
    "lead_reactivation": "only an approved list of previous leads is contacted and interested people are routed back to sales",
}


def _cta_variant() -> str:
    value = os.getenv("OUTREACH_CTA_VARIANT", "A").strip().upper() or "A"
    if value not in {"A", "B"}:
        raise ValueError("OUTREACH_CTA_VARIANT must be A or B")
    return value


def _sender_website() -> str:
    value = os.getenv("OUTREACH_SENDER_WEBSITE", "andrewbaeten.nl").strip()
    if not value or any(ch.isspace() for ch in value):
        raise ValueError("OUTREACH_SENDER_WEBSITE must be a non-empty single website/domain value")
    return value


def _provisional_value(agent_type: str, language: str, fallback: str) -> str:
    catalog = PROVISIONAL_VALUE_NL if language == "nl" else PROVISIONAL_VALUE_EN
    return catalog.get(agent_type, "") or legacy._text(fallback)


def _copy_with_value(
    *,
    company: str,
    country: str,
    fact: str,
    value: str,
    agent_type: str,
    postal_address: str = "",
) -> tuple[str, str, str, str, int]:
    company = legacy._mail_name(company)
    fact = legacy._text(fact)
    value = legacy._text(value)
    agent_type = legacy._text(agent_type).casefold()
    if not company or not fact or not value or agent_type not in AGENT_CATALOG:
        raise ValueError("company, evidence-bound fact/value and approved agent_type are required")
    language = legacy._language(country)
    variant = _cta_variant()
    website = _sender_website()
    if language == "nl":
        subject = SUBJECT_NL.get(agent_type, "Idee voor {company}").format(company=company)
        cta = (
            f"Zal ik een kort voorbeeld sturen van hoe dat er voor {company} uit kan zien?"
            if variant == "A"
            else f"Zal ik dat korte voorbeeld voor {company} sturen?"
        )
        body = (
            f"Beste team van {company},\n\n"
            f"{fact}\n\n"
            "Ik bouw kleine workflows die het repetitieve deel van dit soort processen opvangen, "
            "terwijl het team de belangrijke beslissingen zelf houdt.\n\n"
            f"In de praktijk zou dat bijvoorbeeld kunnen betekenen: {value}.\n\n"
            f"{cta}\n\n"
            "Geen interesse? Een kort \"nee\" is genoeg.\n\n"
            "Dit is een commercieel bericht.\n\n"
            f"Met vriendelijke groet,\nAndrew Baeten\n{website}"
        )
        followup = (
            f"Beste team van {company},\n\n"
            f"Ik kom hier nog één keer op terug. Ik heb het korte voorbeeld voor {company} nog liggen.\n\n"
            f"{cta}\n\n"
            "Geen interesse? Een kort \"nee\" is genoeg.\n\n"
            "Met vriendelijke groet,\nAndrew Baeten"
        )
    else:
        subject = SUBJECT_EN.get(agent_type, "Quick idea for {company}").format(company=company)
        cta = (
            f"Would it be useful if I sent over a short example of how that could work for {company}?"
            if variant == "A"
            else f"Want me to send over that short example for {company}?"
        )
        signature = "Best regards,\nAndrew Baeten"
        if canonical_country(country) == "US":
            if not legacy._text(postal_address):
                raise ValueError("OUTREACH_POSTAL_ADDRESS is required to prepare US commercial copy")
            signature += f"\n{POSTAL_PLACEHOLDER}"
        signature += f"\n{website}"
        body = (
            f"Hi {company} team,\n\n"
            f"{fact}\n\n"
            "I build small workflows that handle the repetitive part of processes like this, "
            "while the team keeps the important decisions.\n\n"
            f"In practice, that could mean: {value}.\n\n"
            f"{cta}\n\n"
            "Not interested? A quick \"no\" is enough.\n\n"
            "This is a commercial message.\n\n"
            f"{signature}"
        )
        followup = (
            f"Hi {company} team,\n\n"
            f"Just following up once. I still have the short example for {company} ready.\n\n"
            f"{cta}\n\n"
            "Not interested? A quick \"no\" is enough.\n\n"
            "Best regards,\nAndrew Baeten"
        )
    errors = initial_copy_errors(subject, body) + followup_copy_errors(followup)
    if errors:
        raise ValueError("generated copy violates LeadPromo v13.5: " + "; ".join(errors[:5]))
    return subject, body, "", followup, 4


def build_copy(*, company: str, country: str, fact: str, idea: str, agent_type: str, postal_address: str = "") -> tuple[str, str, str, str, int]:
    language = legacy._language(country)
    value = _provisional_value(legacy._text(agent_type).casefold(), language, idea)
    return _copy_with_value(
        company=company, country=country, fact=fact, value=value,
        agent_type=agent_type, postal_address=postal_address,
    )


def _with_legacy_v2_globals(callable_, *args, **kwargs):
    old = {
        "AUTOMATION_ID": legacy.AUTOMATION_ID,
        "build_copy": legacy.build_copy,
        "build_prepared_row": legacy.build_prepared_row,
        "initial_copy_errors": legacy.initial_copy_errors,
        "followup_copy_errors": legacy.followup_copy_errors,
    }
    legacy.AUTOMATION_ID = AUTOMATION_ID
    legacy.build_copy = build_copy
    legacy.initial_copy_errors = initial_copy_errors
    legacy.followup_copy_errors = followup_copy_errors
    try:
        return callable_(*args, **kwargs)
    finally:
        legacy.AUTOMATION_ID = old["AUTOMATION_ID"]
        legacy.build_copy = old["build_copy"]
        legacy.build_prepared_row = old["build_prepared_row"]
        legacy.initial_copy_errors = old["initial_copy_errors"]
        legacy.followup_copy_errors = old["followup_copy_errors"]


def build_prepared_row(candidate, qualification, contact, **kwargs):
    row = _with_legacy_v2_globals(_original_build_prepared_row, candidate, qualification, contact, **kwargs)
    source = str(row.get("source", ""))
    if not source.startswith("agent_offer:"):
        raise ValueError("prepared row must contain agent_offer evidence")
    metadata = json.loads(source.split(":", 1)[1])
    target = os.getenv("AGENT_SALES_TARGET_TYPE", "auto").strip().casefold() or "auto"
    found = str(metadata.get("agent_type", "")).strip().casefold()
    if target not in {"auto", found}:
        raise ValueError(f"campaign target mismatch: target={target} found={found}")
    if found == "lead_reactivation":
        raise ValueError("lead_reactivation prepare requires separately approved first-party personalization context")

    company = str(candidate.get("company", ""))
    country = str(candidate.get("country", ""))
    language = legacy._language(country)
    evidence_url = str(metadata.get("evidence_url", "")).strip() or str(candidate.get("website", "")).strip()
    personalization = personalize_from_evidence(
        company=company,
        agent_type=found,
        language=language,
        evidence_url=evidence_url,
    )

    metadata["automation"] = AUTOMATION_ID
    metadata["campaign_target_agent_type"] = found if target == "auto" else target
    metadata["fact"] = personalization.observation
    metadata["idea"] = personalization.value
    metadata["evidence_url"] = personalization.evidence_url
    metadata["value_asset_type"] = "process_flow"
    metadata["value_asset_status"] = "concept_ready"
    metadata["value_asset_summary"] = personalization.value
    metadata["personalization_anchor"] = personalization.anchor
    metadata["personalization_process_label"] = personalization.process_label
    metadata["personalization_evidence_url"] = personalization.evidence_url
    metadata["cta_variant"] = _cta_variant()
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


def main(argv=None) -> int:
    old_build = legacy.build_prepared_row
    legacy.build_prepared_row = build_prepared_row
    try:
        return _with_legacy_v2_globals(legacy.main, argv)
    finally:
        legacy.build_prepared_row = old_build


if __name__ == "__main__":
    raise SystemExit(main())
