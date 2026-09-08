#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence
from urllib.parse import urlparse

from outreach_sender import build_sheets_service, ensure_expected_headers, get_values, rows_from_values
from prospect_discovery import BoundedHttpClient, DiscoveryError, match_terms, parse_page, root_url
from prospect_intelligence import SIGNAL_HEADERS
from prospect_signal_recency import active_signal_score
from prospect_source_semantics import obvious_non_target, source_semantic_target_check
from prospect_target_policy import DEFAULT_AGENCY_EXCLUDE_TERMS, canonical_country, is_excluded_domain

PROSPECT_SHEET = "ProspectCandidates"
AGENT_QUALIFICATION_SHEET = "AgentProspectQualifications"
SIGNAL_SHEET = "ProspectSignals"
PROSPECT_HEADERS = [
    "candidate_id", "discovered_at", "company", "website", "source_url",
    "source_id", "source_type", "country", "matched_terms", "status", "reason",
]
AGENT_QUALIFICATION_HEADERS = [
    "candidate_id", "assessed_at", "company", "website", "country",
    "icp_score", "agent_opportunity_score", "signal_score", "value_integration_fit_score",
    "customer_potential", "tier", "evidence_url", "fact", "idea", "offer_family",
    "agent_type", "business_process", "kpi_candidate", "integration_hint", "status", "reason",
]
RECHECKABLE_STATUSES = {"discovered", "hold", "qualified", "rejected"}
HARD_MAX_PER_RUN = 25
DEFAULT_MAX_PER_RUN = 10
DEFAULT_RECHECK_DAYS = 30

AGENT_CATALOG = {
    "front_desk_sales": "AI Front Desk & Sales Agent",
    "lead_reactivation": "AI Comeback Agent",
    "review_concierge": "AI Review Agent",
    "customer_support": "AI Customer Support Agent",
    "commerce": "AI Commerce Agent",
    "quote_intake": "AI Quote & Intake Agent",
}

BOOKING_HINTS = (
    "book appointment", "book an appointment", "make an appointment", "schedule appointment",
    "schedule a call", "book now", "book online", "booking", "appointment", "appointments",
    "afspraak", "afspraken", "plan een afspraak", "maak een afspraak", "reserveren", "reservation",
)
QUOTE_HINTS = (
    "request a quote", "get a quote", "free quote", "request pricing", "get estimate", "estimate",
    "offerte", "offerte aanvragen", "prijs aanvragen", "prijsopgave", "aanvraag", "intake",
)
SHOP_HINTS = (
    "woocommerce", "shopify", "add to cart", "checkout", "shopping cart", "cart", "buy now",
    "webshop", "winkelwagen", "bestellen", "online shop", "shop online",
)
SUPPORT_HINTS = (
    "customer support", "customer service", "help center", "help centre", "support", "faq",
    "frequently asked questions", "returns", "return policy", "order status", "klantenservice",
    "veelgestelde vragen", "retour", "retourneren", "service desk",
)
REVIEW_HINTS = (
    "reviews", "testimonials", "customer stories", "what customers say", "trustpilot",
    "google reviews", "beoordelingen", "klantreviews", "ervaringen", "wat klanten zeggen",
)
REACTIVATION_HINTS = (
    "existing customers", "returning customers", "customer portal", "newsletter", "follow-up",
    "follow up", "bestaande klanten", "terugkerende klanten", "klantportaal", "nieuwsbrief",
)
CONTACT_HINTS = (
    "contact", "contact us", "contacteer", "call us", "bel ons", "phone", "telefoon",
    "enquiry", "inquiry", "get in touch",
)
COMMERCIAL_HINTS = (
    "services", "diensten", "products", "producten", "solutions", "oplossingen", "pricing",
    "prijzen", "contact", "quote", "offerte", "shop", "webshop",
)


@dataclass(frozen=True)
class AgentFit:
    agent_type: str
    score: int
    evidence_kind: str
    business_process: str
    kpi_candidate: str
    integration_hint: str


@dataclass(frozen=True)
class Assessment:
    icp_score: int
    agent_opportunity_score: int
    signal_score: int
    value_integration_fit_score: int
    customer_potential: int
    tier: str
    evidence_url: str
    fact: str
    idea: str
    offer_family: str
    agent_type: str
    business_process: str
    kpi_candidate: str
    integration_hint: str
    status: str
    reason: str


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clamp_int(raw: object, default: int, low: int, high: int) -> int:
    try:
        value = int(str(raw).strip()) if str(raw or "").strip() else default
    except (TypeError, ValueError):
        value = default
    return max(low, min(value, high))


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"{name} must be true or false")


def _language(country: str) -> str:
    return "nl" if canonical_country(country) in {"NL", "BE"} else "en"


def _contains_any(value: str, needles: Sequence[str]) -> bool:
    haystack = value.casefold()
    return any(needle.casefold() in haystack for needle in needles)


def _page_context(page, html: str) -> str:
    links = " ".join(f"{urlparse(target).path} {label}" for target, label in page.links[:200])
    return f"{page.title} {page.site_name} {page.text} {links} {html[:100000]}"


def classify_agent_fit(page, html: str) -> AgentFit:
    context = _page_context(page, html)
    if _contains_any(context, BOOKING_HINTS):
        return AgentFit("front_desk_sales", 3, "booking", "new_lead_to_qualified_appointment", "qualified_conversation_to_appointment", "phone/chat + calendar + CRM")
    if _contains_any(context, QUOTE_HINTS):
        return AgentFit("quote_intake", 3, "quote_intake", "request_to_complete_intake", "complete_intake_to_quote", "form/chat + CRM + quote workflow")
    if _contains_any(context, SHOP_HINTS):
        return AgentFit("commerce", 3, "commerce", "product_question_to_supported_purchase", "assisted_product_journey", "catalog/order data + support handoff")
    if _contains_any(context, SUPPORT_HINTS):
        return AgentFit("customer_support", 3, "support", "customer_question_to_resolution_or_handoff", "resolved_or_correctly_escalated_request", "knowledge base + ticketing/order data")
    if _contains_any(context, REVIEW_HINTS):
        return AgentFit("review_concierge", 2, "reviews", "completed_service_to_review_request", "completed_service_to_review_request", "CRM/order completion + review platform")
    if _contains_any(context, REACTIVATION_HINTS):
        return AgentFit("lead_reactivation", 2, "reactivation", "approved_old_lead_to_requalified_opportunity", "reactivated_conversation_to_qualified_opportunity", "approved CRM segment + messaging channel + suppression")
    if _contains_any(context, CONTACT_HINTS):
        return AgentFit("front_desk_sales", 2, "contact", "new_enquiry_to_qualified_handoff", "qualified_conversation_to_handoff", "phone/chat + CRM + human handoff")
    return AgentFit("", 0, "none", "", "", "")


def _fact_and_idea(fit: AgentFit, company: str, language: str) -> tuple[str, str]:
    company = _text(company)
    if language == "nl":
        facts = {
            "booking": f"De website van {company} biedt bezoekers een afspraak- of boekingsroute.",
            "quote_intake": f"De website van {company} nodigt bezoekers uit om een offerte, prijs of intake aan te vragen.",
            "commerce": f"De website van {company} bevat duidelijke online winkel- of checkoutcontext.",
            "support": f"De website van {company} bevat een support-, service- of veelgestelde-vragenroute.",
            "reviews": f"De website van {company} toont klantreviews, beoordelingen of testimonials.",
            "reactivation": f"De website van {company} bevat context voor terugkerende klanten of structurele follow-up.",
            "contact": f"De website van {company} stuurt bezoekers naar contact of telefonisch vervolg.",
        }
        ideas = {
            "front_desk_sales": f"Een AI Front Desk & Sales Agent kan voor {company} eerste vragen beantwoorden, relevante gegevens verzamelen, leads kwalificeren en een afspraak of menselijke overdracht voorbereiden.",
            "lead_reactivation": f"Een AI Comeback Agent kan uitsluitend op een door {company} goedgekeurde lijst oude leads opnieuw contact starten, interesse herkennen en geïnteresseerden terug naar sales of een afspraak sturen.",
            "review_concierge": f"Een AI Review Agent kan na een door {company} vastgelegde afronding een reviewverzoek sturen, één nette follow-up doen en reacties voor menselijk toezicht klaarzetten.",
            "customer_support": f"Een AI Customer Support Agent kan voor {company} standaardvragen beantwoorden uit goedgekeurde kennis, context verzamelen en complexe gevallen met samenvatting overdragen.",
            "commerce": f"Een AI Commerce Agent kan bezoekers van {company} helpen producten te vinden en vergelijken en order- of retourvragen afhandelen op basis van echte catalogus- en orderdata.",
            "quote_intake": f"Een AI Quote & Intake Agent kan voor {company} aanvraaggegevens compleet verzamelen, ontbrekende informatie navragen en een conceptofferte of intake voor menselijke goedkeuring voorbereiden.",
        }
    else:
        facts = {
            "booking": f"The website of {company} gives visitors an appointment or booking path.",
            "quote_intake": f"The website of {company} invites visitors to request a quote, pricing or an intake.",
            "commerce": f"The website of {company} contains clear online store or checkout context.",
            "support": f"The website of {company} contains a support, service or FAQ path.",
            "reviews": f"The website of {company} displays customer reviews, ratings or testimonials.",
            "reactivation": f"The website of {company} contains context for returning customers or structured follow-up.",
            "contact": f"The website of {company} directs visitors to contact or phone follow-up.",
        }
        ideas = {
            "front_desk_sales": f"An AI Front Desk & Sales Agent can answer first questions for {company}, collect relevant details, qualify the lead and prepare an appointment or human handoff.",
            "lead_reactivation": f"An AI Comeback Agent can work only from an old-lead list approved by {company}, restart conversations, detect interest and route interested people back to sales or booking.",
            "review_concierge": f"An AI Review Agent can use a completion event defined by {company} to request a review, send one polite follow-up and prepare responses for human oversight.",
            "customer_support": f"An AI Customer Support Agent can answer standard questions for {company} from approved knowledge, collect context and hand complex cases to a person with a summary.",
            "commerce": f"An AI Commerce Agent can help visitors of {company} find and compare products and handle order or return questions using real catalog and order data.",
            "quote_intake": f"An AI Quote & Intake Agent can collect complete request details for {company}, ask for missing information and prepare a quote or intake draft for human approval.",
        }
    return facts.get(fit.evidence_kind, ""), ideas.get(fit.agent_type, "")


def assess_candidate(row: Mapping[str, object], html: str, signals: Sequence[Mapping[str, object]] = ()) -> Assessment:
    candidate_id = _text(row.get("candidate_id"))
    company = _text(row.get("company"))
    website = root_url(_text(row.get("website")))
    source_url = _text(row.get("source_url"))
    source_id = _text(row.get("source_id"))
    country = canonical_country(_text(row.get("country")))
    def reject(reason: str) -> Assessment:
        return Assessment(0, 0, 0, 0, 0, "C", website, "", "", "ai_agent", "", "", "", "", "rejected", reason)
    if not candidate_id or not company or not website:
        return reject("missing candidate identity or official website")
    if is_excluded_domain(website):
        return reject("self/excluded domain")
    direct_reason = obvious_non_target(company, website, source_url)
    if direct_reason:
        return reject(f"source_semantic_target_policy: {direct_reason}")
    semantic_allowed, semantic_reason = source_semantic_target_check(
        source_id=source_id, source_url=source_url, company=company, website=website, html=html,
    )
    if not semantic_allowed:
        return reject(f"source_semantic_target_policy: {semantic_reason}")

    page = parse_page(html, website)
    context = _page_context(page, html)
    accepted, _ = match_terms(context, (), DEFAULT_AGENCY_EXCLUDE_TERMS)
    if not accepted:
        return reject("agency/provider target policy blocked")

    fit = classify_agent_fit(page, html)
    commercial = _contains_any(context, COMMERCIAL_HINTS) or fit.score > 0
    icp_score = 3 if commercial and fit.score >= 2 else 2 if commercial else 1
    signal_score = active_signal_score(candidate_id, signals)
    value_fit = 2 if fit.score == 3 and fit.integration_hint else 1 if fit.score > 0 else 0
    total = max(0, min(icp_score + fit.score + signal_score + value_fit, 10))
    tier = "A" if total >= 8 else "B" if total >= 6 else "C"
    status = "qualified" if tier == "A" else "hold" if tier == "B" else "rejected"
    fact, idea = _fact_and_idea(fit, company, _language(country)) if fit.agent_type else ("", "")
    reason = (
        f"customer_potential={total}; icp={icp_score}; agent_opportunity={fit.score}; signal={signal_score}; "
        f"value_integration_fit={value_fit}; agent_type={fit.agent_type or 'none'}; evidence={fit.evidence_kind}"
    )
    if tier == "A" and (not fact or not idea or fit.agent_type not in AGENT_CATALOG):
        tier, status = "B", "hold"
        reason += "; downgraded=no evidence-bound agent fact/idea"
    return Assessment(
        icp_score, fit.score, signal_score, value_fit, total, tier, website, fact, idea,
        "ai_agent", fit.agent_type, fit.business_process, fit.kpi_candidate, fit.integration_hint,
        status, reason,
    )


def _sheet_titles(service, spreadsheet_id: str) -> set[str]:
    metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties").execute()
    return {item["properties"]["title"] for item in metadata.get("sheets", [])}


def ensure_agent_qualification_tab(service, spreadsheet_id: str, *, create: bool) -> bool:
    titles = _sheet_titles(service, spreadsheet_id)
    if AGENT_QUALIFICATION_SHEET not in titles:
        if not create:
            return False
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": AGENT_QUALIFICATION_SHEET}}}]},
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id, range=f"'{AGENT_QUALIFICATION_SHEET}'!A1",
            valueInputOption="RAW", body={"values": [AGENT_QUALIFICATION_HEADERS]},
        ).execute()
        return True
    values = get_values(service, spreadsheet_id, AGENT_QUALIFICATION_SHEET)
    current = [str(value).strip() for value in values[0]] if values else []
    if not current and create:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id, range=f"'{AGENT_QUALIFICATION_SHEET}'!A1",
            valueInputOption="RAW", body={"values": [AGENT_QUALIFICATION_HEADERS]},
        ).execute()
    elif current and current[:len(AGENT_QUALIFICATION_HEADERS)] != AGENT_QUALIFICATION_HEADERS:
        raise DiscoveryError(f"{AGENT_QUALIFICATION_SHEET} headers do not match the required contract")
    return True


def _replace_rows(service, spreadsheet_id: str, sheet: str, headers: Sequence[str], rows: Sequence[Mapping[str, object]]) -> None:
    values = [list(headers)] + [[str(row.get(header, "")) for header in headers] for row in rows]
    service.spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range=f"'{sheet}'!A:ZZ", body={}).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"'{sheet}'!A1", valueInputOption="RAW", body={"values": values},
    ).execute()


def _parse_iso(raw: object) -> datetime | None:
    value = _text(raw)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _eligible_candidates(candidates, existing_by_id, *, force_recheck: bool, recheck_days: int):
    cutoff = datetime.now(timezone.utc) - timedelta(days=recheck_days)
    ranked = []
    for index, candidate in enumerate(candidates):
        if _text(candidate.get("status")).casefold() not in RECHECKABLE_STATUSES:
            continue
        candidate_id = _text(candidate.get("candidate_id"))
        previous = existing_by_id.get(candidate_id)
        assessed_at = _parse_iso(previous.get("assessed_at")) if previous else None
        if previous and not force_recheck and assessed_at and assessed_at > cutoff:
            continue
        ranked.append((0 if previous is None else 1, assessed_at or datetime.min.replace(tzinfo=timezone.utc), index, candidate))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return [candidate for _, _, _, candidate in ranked]


def _write_report(path: str, payload: Mapping[str, object]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def run(mode: str, report_path: str) -> int:
    mode = (mode or "validate").strip().casefold()
    if mode not in {"validate", "qualify"}:
        raise DiscoveryError("mode must be validate or qualify")
    spreadsheet_id = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        raise DiscoveryError("OUTREACH_SPREADSHEET_ID is required")
    if not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise DiscoveryError("GOOGLE_SERVICE_ACCOUNT_JSON is required")

    service = build_sheets_service()
    headers, candidates = rows_from_values(get_values(service, spreadsheet_id, PROSPECT_SHEET))
    ensure_expected_headers(headers, PROSPECT_HEADERS, PROSPECT_SHEET)
    signal_headers, signals = rows_from_values(get_values(service, spreadsheet_id, SIGNAL_SHEET))
    ensure_expected_headers(signal_headers, SIGNAL_HEADERS, SIGNAL_SHEET)
    qualification_exists = ensure_agent_qualification_tab(service, spreadsheet_id, create=(mode == "qualify"))

    if mode == "validate":
        _write_report(report_path, {"mode": mode, "status": "ready", "agent_qualification_tab_present": qualification_exists, "send_permission": "none"})
        print(f"PROSPECT_AGENT_QUALIFICATION=validated qualification_tab_present={str(qualification_exists).lower()}")
        return 0

    existing_headers, existing = rows_from_values(get_values(service, spreadsheet_id, AGENT_QUALIFICATION_SHEET))
    ensure_expected_headers(existing_headers, AGENT_QUALIFICATION_HEADERS, AGENT_QUALIFICATION_SHEET)
    existing_by_id = {_text(row.get("candidate_id")): dict(row) for row in existing if _text(row.get("candidate_id"))}
    max_rows = clamp_int(os.getenv("PROSPECT_QUALIFICATION_MAX_PER_RUN", ""), DEFAULT_MAX_PER_RUN, 1, HARD_MAX_PER_RUN)
    recheck_days = clamp_int(os.getenv("PROSPECT_QUALIFICATION_RECHECK_DAYS", ""), DEFAULT_RECHECK_DAYS, 1, 365)
    force_recheck = env_bool("PROSPECT_QUALIFICATION_FORCE_RECHECK", False)
    candidate_pool = _eligible_candidates(candidates, existing_by_id, force_recheck=force_recheck, recheck_days=recheck_days)
    client = BoundedHttpClient(
        user_agent=os.getenv("PROSPECT_QUALIFICATION_USER_AGENT", "WebactueelAgentQualification/1.0 (+https://andrewbaeten.nl)"),
        timeout=float(os.getenv("PROSPECT_QUALIFICATION_TIMEOUT_SECONDS", "10") or "10"),
        max_bytes=clamp_int(os.getenv("PROSPECT_QUALIFICATION_MAX_BYTES", ""), 524288, 65536, 2097152),
        min_interval=float(os.getenv("PROSPECT_QUALIFICATION_MIN_INTERVAL_SECONDS", "0.5") or "0.5"),
    )

    assessed = qualified = held = rejected = unscored = 0
    for candidate in candidate_pool[:max_rows]:
        candidate_id = _text(candidate.get("candidate_id"))
        website = root_url(_text(candidate.get("website")))
        if not candidate_id or not website:
            continue
        assessed += 1
        direct_reason = obvious_non_target(_text(candidate.get("company")), website, _text(candidate.get("source_url")))
        if direct_reason:
            assessment = Assessment(0, 0, 0, 0, 0, "C", website, "", "", "ai_agent", "", "", "", "", "rejected", f"source_semantic_target_policy: {direct_reason}")
        else:
            try:
                assessment = assess_candidate(candidate, client.fetch_text(website), signals)
            except (DiscoveryError, RuntimeError, ValueError) as exc:
                assessment = Assessment(0, 0, active_signal_score(candidate_id, signals), 0, 0, "UNSCORED", website, "", "", "ai_agent", "", "", "", "", "hold", f"agent qualification fetch/evidence unavailable: {type(exc).__name__}: {_text(exc)[:180]}")
                unscored += 1

        candidate["status"] = assessment.status
        candidate["reason"] = assessment.reason
        if assessment.status == "qualified":
            qualified += 1
        elif assessment.status == "hold":
            held += 1
        else:
            rejected += 1
        existing_by_id[candidate_id] = {
            "candidate_id": candidate_id,
            "assessed_at": utc_iso(),
            "company": _text(candidate.get("company")),
            "website": _text(candidate.get("website")),
            "country": canonical_country(_text(candidate.get("country"))),
            "icp_score": assessment.icp_score,
            "agent_opportunity_score": assessment.agent_opportunity_score,
            "signal_score": assessment.signal_score,
            "value_integration_fit_score": assessment.value_integration_fit_score,
            "customer_potential": assessment.customer_potential,
            "tier": assessment.tier,
            "evidence_url": assessment.evidence_url,
            "fact": assessment.fact,
            "idea": assessment.idea,
            "offer_family": assessment.offer_family,
            "agent_type": assessment.agent_type,
            "business_process": assessment.business_process,
            "kpi_candidate": assessment.kpi_candidate,
            "integration_hint": assessment.integration_hint,
            "status": assessment.status,
            "reason": assessment.reason,
        }

    _replace_rows(service, spreadsheet_id, PROSPECT_SHEET, PROSPECT_HEADERS, candidates)
    qualification_rows = [existing_by_id[key] for key in sorted(existing_by_id)]
    _replace_rows(service, spreadsheet_id, AGENT_QUALIFICATION_SHEET, AGENT_QUALIFICATION_HEADERS, qualification_rows)
    _write_report(report_path, {
        "mode": mode, "status": "completed", "assessed": assessed, "qualified": qualified,
        "hold": held, "rejected": rejected, "unscored": unscored, "force_recheck": force_recheck,
        "recheck_days": recheck_days, "offer_family": "ai_agent", "send_permission": "none",
        "note": "Agent qualification is deterministic, evidence-bound and bounded. It selects only from the six approved Webactueel agent offers and never grants compliance or send permission.",
    })
    print(f"PROSPECT_AGENT_QUALIFICATION=complete assessed={assessed} qualified={qualified} hold={held} rejected={rejected} unscored={unscored}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evidence-bound qualification for Webactueel AI agent offers.")
    parser.add_argument("--mode", default=os.getenv("PROSPECT_QUALIFICATION_MODE", "validate"), choices=["validate", "qualify"])
    parser.add_argument("--report", default="prospect-agent-qualification-report.json")
    args = parser.parse_args(argv)
    try:
        return run(args.mode, args.report)
    except (DiscoveryError, RuntimeError, ValueError) as exc:
        _write_report(args.report, {"mode": args.mode, "status": "blocked", "error": str(exc), "send_permission": "none"})
        print(f"PROSPECT_AGENT_QUALIFICATION=blocked detail={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())