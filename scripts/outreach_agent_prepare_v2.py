#!/usr/bin/env python3
from __future__ import annotations

import json
import os

import outreach_agent_prepare as legacy
from outreach_copy_preflight import followup_copy_errors, initial_copy_errors
from prospect_agent_qualification import AGENT_CATALOG
from prospect_target_policy import canonical_country

AUTOMATION_ID = "agent_sales_prepare_v2"
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

PLAIN_VALUE_NL = {
    "front_desk_sales": "eerste vragen worden opgevangen, de belangrijkste gegevens worden verzameld en geschikte aanvragen kunnen naar je team of richting een afspraak worden doorgestuurd",
    "quote_intake": "klanten beantwoorden een paar gerichte vragen, ontbrekende gegevens worden aangevuld en je team krijgt een completere offerteaanvraag om te beoordelen",
    "customer_support": "veelvoorkomende vragen krijgen antwoord uit goedgekeurde informatie en complexere vragen komen met de juiste context bij je team terecht",
    "commerce": "bezoekers krijgen hulp bij productvragen en vergelijken, terwijl order- of retourvragen op basis van echte gegevens worden afgehandeld of doorgestuurd",
    "review_concierge": "na een afgeronde klantactie kan een passend reviewverzoek worden gestuurd en blijft je team in controle over eventuele opvolging",
    "lead_reactivation": "alleen een goedgekeurde lijst met eerdere leads wordt benaderd, interesse wordt herkend en geïnteresseerden worden terug naar sales geleid",
}
PLAIN_VALUE_EN = {
    "front_desk_sales": "first questions are handled, the details you need are collected, and suitable enquiries can be passed to your team or moved toward booking",
    "quote_intake": "customers answer a few straightforward questions, missing details are collected, and your team receives a more complete quote request to review",
    "customer_support": "common questions are answered from approved information, while more complex requests reach your team with the useful context already attached",
    "commerce": "visitors get help with product questions and comparisons, while order or return questions are handled from real data or passed to your team",
    "review_concierge": "after a completed customer action, a relevant review request can be sent while your team stays in control of any follow-up",
    "lead_reactivation": "only an approved list of previous leads is contacted, interest is identified, and interested people are routed back to sales",
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


def _plain_value_summary(*, company: str, agent_type: str, language: str, fallback: str) -> str:
    del company
    catalog = PLAIN_VALUE_NL if language == "nl" else PLAIN_VALUE_EN
    value = catalog.get(agent_type, "")
    return value or legacy._text(fallback)


def build_copy(*, company: str, country: str, fact: str, idea: str, agent_type: str, postal_address: str = "") -> tuple[str, str, str, str, int]:
    company = legacy._mail_name(company)
    fact = legacy._text(fact)
    idea = legacy._text(idea)
    agent_type = legacy._text(agent_type).casefold()
    if not company or not fact or not idea or agent_type not in AGENT_CATALOG:
        raise ValueError("company, evidence-bound fact/idea and approved agent_type are required")
    language = legacy._language(country)
    variant = _cta_variant()
    website = _sender_website()
    plain_value = _plain_value_summary(company=company, agent_type=agent_type, language=language, fallback=idea)
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
            "Ik help bedrijven dit soort processen eenvoudiger te maken met een kleine AI-ondersteunde workflow, "
            "terwijl het team de belangrijke stappen zelf blijft controleren.\n\n"
            f"Voor {company} zou dat bijvoorbeeld kunnen betekenen: {plain_value}.\n\n"
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
            "I help businesses make processes like this a little easier with a small AI-assisted workflow, "
            "while your team stays in control of the important steps.\n\n"
            f"For {company}, that could mean: {plain_value}.\n\n"
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
        raise ValueError("generated copy violates LeadPromo v13.4: " + "; ".join(errors[:5]))
    return subject, body, "", followup, 4


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
    language = legacy._language(str(candidate.get("country", "")))
    metadata["automation"] = AUTOMATION_ID
    metadata["campaign_target_agent_type"] = found if target == "auto" else target
    metadata["value_asset_type"] = "process_flow"
    metadata["value_asset_status"] = "concept_ready"
    metadata["value_asset_summary"] = _plain_value_summary(
        company=str(candidate.get("company", "")),
        agent_type=found,
        language=language,
        fallback=str(metadata.get("idea", "")),
    )
    metadata["cta_variant"] = _cta_variant()
    metadata["copy_contract"] = "human_v13_4"
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
