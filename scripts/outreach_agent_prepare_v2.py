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
    "customer_support": "Klantenservice bij {company}",
    "commerce": "Productvragen bij {company}",
    "review_concierge": "Reviews bij {company}",
    "lead_reactivation": "Opvolging bij {company}",
}
SUBJECT_EN = {
    "front_desk_sales": "Appointments at {company}",
    "quote_intake": "Quote requests at {company}",
    "customer_support": "Customer support at {company}",
    "commerce": "Product questions at {company}",
    "review_concierge": "Reviews at {company}",
    "lead_reactivation": "Follow-up at {company}",
}


def _cta_variant() -> str:
    value = os.getenv("OUTREACH_CTA_VARIANT", "A").strip().upper() or "A"
    if value not in {"A", "B"}:
        raise ValueError("OUTREACH_CTA_VARIANT must be A or B")
    return value


def build_copy(*, company: str, country: str, fact: str, idea: str, agent_type: str, postal_address: str = "") -> tuple[str, str, str, str, int]:
    company = legacy._mail_name(company)
    fact = legacy._text(fact)
    idea = legacy._text(idea)
    agent_type = legacy._text(agent_type).casefold()
    if not company or not fact or not idea or agent_type not in AGENT_CATALOG:
        raise ValueError("company, evidence-bound fact/idea and approved agent_type are required")
    language = legacy._language(country)
    variant = _cta_variant()
    if language == "nl":
        subject = SUBJECT_NL.get(agent_type, "Idee voor {company}").format(company=company)
        cta = ("Zal" if variant == "A" else "Mag") + f" ik de korte voorbeeldflow voor {company} sturen?"
        body = (
            f"Beste team van {company},\n\n"
            f"{fact}\n\n"
            "Ik bouw afgebakende digitale agents voor dit soort bedrijfsprocessen, met menselijke overdracht waar nodig.\n\n"
            f"Eén concrete voorbeeldflow voor {company}: {idea}\n\n"
            f"{cta}\n\n"
            "Geen interesse? Een kort \"nee\" is genoeg.\n\n"
            "Met vriendelijke groet,\nAndrew Baeten"
        )
        followup = (
            f"Beste team van {company},\n\n"
            f"Ik kom hier nog één keer op terug. De korte voorbeeldflow voor {company} staat klaar.\n\n"
            f"{cta}\n\n"
            "Geen interesse? Een kort \"nee\" is genoeg.\n\n"
            "Met vriendelijke groet,\nAndrew Baeten"
        )
    else:
        subject = SUBJECT_EN.get(agent_type, "Idea for {company}").format(company=company)
        cta = ("Would you like me to" if variant == "A" else "May I") + f" send the short example flow for {company}?"
        legal_lines = ""
        if canonical_country(country) == "US":
            if not legacy._text(postal_address):
                raise ValueError("OUTREACH_POSTAL_ADDRESS is required to prepare US commercial copy")
            legal_lines = f"\n\nThis is a commercial message.\n{POSTAL_PLACEHOLDER}"
        body = (
            f"Hi {company} team,\n\n"
            f"{fact}\n\n"
            "I build bounded digital agents for workflows like this, with human handoff where needed.\n\n"
            f"One concrete example flow for {company}: {idea}\n\n"
            f"{cta}"
            f"{legal_lines}\n\n"
            "Not interested? A quick \"no\" is enough.\n\n"
            "Best regards,\nAndrew Baeten"
        )
        followup = (
            f"Hi {company} team,\n\n"
            f"Just following up once. The short example flow for {company} is ready.\n\n"
            f"{cta}\n\n"
            "Not interested? A quick \"no\" is enough.\n\n"
            "Best regards,\nAndrew Baeten"
        )
    errors = initial_copy_errors(subject, body) + followup_copy_errors(followup)
    if errors:
        raise ValueError("generated copy violates LeadPromo v13.1: " + "; ".join(errors[:5]))
    return subject, body, "", followup, 4


def build_prepared_row(candidate, qualification, contact, **kwargs):
    row = _original_build_prepared_row(candidate, qualification, contact, **kwargs)
    source = str(row.get("source", ""))
    if not source.startswith("agent_offer:"):
        raise ValueError("prepared row must contain agent_offer evidence")
    metadata = json.loads(source.split(":", 1)[1])
    target = os.getenv("AGENT_SALES_TARGET_TYPE", "auto").strip().casefold() or "auto"
    found = str(metadata.get("agent_type", "")).strip().casefold()
    if target not in {"auto", found}:
        raise ValueError(f"campaign target mismatch: target={target} found={found}")
    metadata["automation"] = AUTOMATION_ID
    metadata["campaign_target_agent_type"] = found if target == "auto" else target
    metadata["value_asset_type"] = "process_flow"
    metadata["value_asset_status"] = "concept_ready"
    metadata["value_asset_summary"] = str(metadata.get("idea", "")).strip()
    metadata["cta_variant"] = _cta_variant()
    row["source"] = "agent_offer:" + json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    return row


legacy.AUTOMATION_ID = AUTOMATION_ID
legacy.build_copy = build_copy
legacy.build_prepared_row = build_prepared_row
legacy.initial_copy_errors = initial_copy_errors
legacy.followup_copy_errors = followup_copy_errors


def main(argv=None) -> int:
    return legacy.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())