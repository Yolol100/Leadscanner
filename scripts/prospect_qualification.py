#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence
from urllib.parse import urlparse

from outreach_sender import build_sheets_service, ensure_expected_headers, get_values, rows_from_values
from prospect_discovery import BoundedHttpClient, DiscoveryError, match_terms, parse_page, root_url
from prospect_intelligence import SIGNAL_HEADERS
from prospect_target_policy import DEFAULT_AGENCY_EXCLUDE_TERMS, canonical_country, is_excluded_domain

PROSPECT_SHEET = "ProspectCandidates"
QUALIFICATION_SHEET = "ProspectQualifications"
SIGNAL_SHEET = "ProspectSignals"
PROSPECT_HEADERS = [
    "candidate_id", "discovered_at", "company", "website", "source_url",
    "source_id", "source_type", "country", "matched_terms", "status", "reason",
]
QUALIFICATION_HEADERS = [
    "candidate_id", "assessed_at", "company", "website", "country",
    "icp_score", "website_opportunity_score", "signal_score", "offer_fit_score",
    "customer_potential", "tier", "evidence_url", "fact", "idea",
    "analysis_type", "status", "reason",
]
ELIGIBLE_STATUSES = {"discovered", "hold"}
HARD_MAX_PER_RUN = 25
DEFAULT_MAX_PER_RUN = 10

CONTACT_HINTS = (
    "contact", "contacteer", "contact-us", "get-in-touch", "offerte", "quote",
    "afspraak", "enquiry", "inquiry",
)
STRONG_SHOP_HINTS = (
    "woocommerce", "shopify", "winkelwagen", "checkout", "add to cart", "cart",
    "bestellen", "order now", "webshop", "online shop", "shop online", "buy now",
)
SHOP_PATH_RE = re.compile(r"/(?:shop|store|webshop|winkel)(?:/|$)", re.I)
COMMERCIAL_HINTS = (
    "diensten", "services", "producten", "products", "shop", "webshop", "offerte",
    "quote", "contact", "pricing", "prijzen", "solutions", "oplossingen",
)
META_DESCRIPTION_RE = re.compile(
    r"<meta\b[^>]*\bname\s*=\s*(['\"])description\1[^>]*\bcontent\s*=\s*(['\"])(.*?)\2",
    re.I | re.S,
)
VIEWPORT_RE = re.compile(r"<meta\b[^>]*\bname\s*=\s*(['\"])viewport\1", re.I | re.S)
H1_RE = re.compile(r"<h1\b", re.I)
OPPORTUNITY_WEIGHT = {
    "shop_no_checkout": 3,
    "no_contact_link": 2,
    "no_meta_description": 1,
    "no_viewport": 1,
    "no_h1": 1,
}


@dataclass(frozen=True)
class Assessment:
    icp_score: int
    website_opportunity_score: int
    signal_score: int
    offer_fit_score: int
    customer_potential: int
    tier: str
    evidence_url: str
    fact: str
    idea: str
    analysis_type: str
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


def _language(country: str) -> str:
    return "nl" if canonical_country(country) in {"NL", "BE"} else "en"


def _contains_any(value: str, needles: Sequence[str]) -> bool:
    haystack = value.casefold()
    return any(needle.casefold() in haystack for needle in needles)


def _contact_link_present(page) -> bool:
    for target, label in page.links:
        parsed = urlparse(target)
        context = f"{parsed.path} {label}".casefold()
        if any(hint in context for hint in CONTACT_HINTS):
            return True
    return False


def _checkout_link_present(page) -> bool:
    for target, label in page.links:
        parsed = urlparse(target)
        context = f"{parsed.path} {label}".casefold()
        if any(hint in context for hint in ("cart", "checkout", "winkelwagen", "afrekenen", "basket")):
            return True
    return False


def _explicit_shop_context(page, html: str) -> bool:
    haystack = f"{page.title} {page.site_name} {page.text} {html[:100000]}"
    if _contains_any(haystack, STRONG_SHOP_HINTS):
        return True
    for target, label in page.links:
        parsed = urlparse(target)
        if SHOP_PATH_RE.search(parsed.path or ""):
            return True
        label_text = _text(label).casefold()
        if label_text in {"shop", "store", "webshop", "winkel"}:
            return True
    return False


def _active_signal_score(candidate_id: str, signals: Sequence[Mapping[str, object]]) -> int:
    score = 0
    for row in signals:
        if _text(row.get("candidate_id")) != candidate_id:
            continue
        if _text(row.get("status")).casefold() != "active":
            continue
        try:
            strength = int(_text(row.get("strength")) or "0")
        except ValueError:
            continue
        score = max(score, max(0, min(strength, 2)))
    return score


def _fact_and_idea(issue: str, company: str, language: str, page_title: str = "") -> tuple[str, str]:
    company = _text(company)
    page_title = _text(page_title)[:120]
    if language == "nl":
        title_context = f" op de pagina ‘{page_title}’" if page_title else ""
        pairs = {
            "shop_no_checkout": (
                f"De homepage van {company}{title_context} toont duidelijke winkelcontext, maar in de begrensde homepagecheck is geen duidelijke winkelwagen- of checkoutlink gevonden.",
                f"Maak vanuit de homepage van {company} één zichtbare route naar winkelwagen of checkout, zodat bezoekers vanuit deze concrete winkelroute direct een volgende koopstap kunnen zetten.",
            ),
            "no_contact_link": (
                f"In de begrensde homepagecheck van {company}{title_context} is geen duidelijke interne contact- of offertelink gevonden.",
                f"Voeg op de homepage van {company} één vaste contact- of offerteknop toe die aansluit op de huidige pagina-inhoud, zodat bezoekers in één stap kunnen reageren.",
            ),
            "no_meta_description": (
                f"De homepage van {company}{title_context} bevat in de opgehaalde HTML geen meta description.",
                f"Voeg voor de huidige homepage van {company} een korte, specifieke meta description toe die het getoonde aanbod samenvat en zoekers naar de belangrijkste bezoekersactie leidt.",
            ),
            "no_viewport": (
                f"De homepage van {company}{title_context} bevat in de opgehaalde HTML geen viewport-metatag.",
                f"Voeg voor de huidige homepage van {company} een correcte responsive viewport-instelling toe en controleer daarna de belangrijkste mobiele bezoekersroute.",
            ),
            "no_h1": (
                f"De homepage van {company}{title_context} bevat in de opgehaalde HTML geen H1-element.",
                f"Geef de huidige homepage van {company} één duidelijke H1 die het primaire aanbod van deze pagina benoemt en bezoekers naar de belangrijkste actie stuurt.",
            ),
        }
    else:
        title_context = f" on the page ‘{page_title}’" if page_title else ""
        pairs = {
            "shop_no_checkout": (
                f"The homepage of {company}{title_context} shows clear shopping context, but the bounded homepage check found no clear cart or checkout link.",
                f"Add one visible cart or checkout path from the homepage of {company} so visitors on this specific shopping route can take the next purchase step directly.",
            ),
            "no_contact_link": (
                f"The bounded homepage check for {company}{title_context} found no clear internal contact or quote link.",
                f"Add one persistent contact or quote call-to-action to the homepage of {company} that fits the current page content so visitors can respond in one step.",
            ),
            "no_meta_description": (
                f"The fetched homepage HTML for {company}{title_context} contains no meta description.",
                f"Add a concise, company-specific meta description for the current homepage of {company} that summarizes the displayed offer and points searchers toward the primary visitor action.",
            ),
            "no_viewport": (
                f"The fetched homepage HTML for {company}{title_context} contains no viewport meta tag.",
                f"Add a correct responsive viewport configuration for the current homepage of {company} and then verify the primary mobile visitor path.",
            ),
            "no_h1": (
                f"The fetched homepage HTML for {company}{title_context} contains no H1 element.",
                f"Give the current homepage of {company} one clear H1 that names the page's primary offer and directs visitors toward the main action.",
            ),
        }
    return pairs[issue]


def assess_candidate(
    row: Mapping[str, object],
    html: str,
    signals: Sequence[Mapping[str, object]] = (),
) -> Assessment:
    candidate_id = _text(row.get("candidate_id"))
    company = _text(row.get("company"))
    website = root_url(_text(row.get("website")))
    country = canonical_country(_text(row.get("country")))
    if not candidate_id or not company or not website:
        return Assessment(0, 0, 0, 0, 0, "C", website, "", "", "website", "rejected", "missing candidate identity or official website")
    if is_excluded_domain(website):
        return Assessment(0, 0, 0, 0, 0, "C", website, "", "", "website", "rejected", "self/excluded domain")

    page = parse_page(html, website)
    haystack = f"{page.title} {page.site_name} {page.text} {html[:100000]}"
    accepted, _ = match_terms(haystack, (), DEFAULT_AGENCY_EXCLUDE_TERMS)
    if not accepted:
        return Assessment(0, 0, 0, 0, 0, "C", website, "", "", "website", "rejected", "agency/provider target policy blocked")

    language = _language(country)
    is_shop = _explicit_shop_context(page, html)
    commercial = is_shop or _contains_any(haystack, COMMERCIAL_HINTS)
    analysis_type = "webshop" if is_shop else "website"

    issues: list[str] = []
    if is_shop and not _checkout_link_present(page):
        issues.append("shop_no_checkout")
    if not _contact_link_present(page):
        issues.append("no_contact_link")
    if not META_DESCRIPTION_RE.search(html or ""):
        issues.append("no_meta_description")
    if not VIEWPORT_RE.search(html or ""):
        issues.append("no_viewport")
    if not H1_RE.search(html or ""):
        issues.append("no_h1")

    primary_issue = max(issues, key=lambda issue: OPPORTUNITY_WEIGHT[issue], default="")
    website_opportunity_score = OPPORTUNITY_WEIGHT.get(primary_issue, 0)
    icp_score = 3 if commercial else 2
    if not _text(page.title) and not commercial:
        icp_score = 1
    offer_fit_score = 2 if commercial else 1
    signal_score = _active_signal_score(candidate_id, signals)
    total = max(0, min(icp_score + website_opportunity_score + signal_score + offer_fit_score, 10))
    tier = "A" if total >= 8 else "B" if total >= 6 else "C"
    status = "qualified" if tier == "A" else "hold" if tier == "B" else "rejected"

    fact = idea = ""
    if primary_issue:
        fact, idea = _fact_and_idea(primary_issue, company, language, _text(page.title))
    reason = (
        f"customer_potential={total}; icp={icp_score}; opportunity={website_opportunity_score}; "
        f"signal={signal_score}; offer_fit={offer_fit_score}; primary_evidence={primary_issue or 'no_concrete_gap'}; "
        f"supporting_evidence={','.join(issues[:5]) if issues else 'none'}"
    )
    if not fact or not idea:
        if tier == "A":
            tier, status = "B", "hold"
            reason += "; downgraded=no evidence-bound fact/idea"
    return Assessment(
        icp_score,
        website_opportunity_score,
        signal_score,
        offer_fit_score,
        total,
        tier,
        website,
        fact,
        idea,
        analysis_type,
        status,
        reason,
    )


def _sheet_titles(service, spreadsheet_id: str) -> set[str]:
    metadata = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields="sheets.properties"
    ).execute()
    return {item["properties"]["title"] for item in metadata.get("sheets", [])}


def ensure_qualification_tab(service, spreadsheet_id: str, *, create: bool) -> bool:
    titles = _sheet_titles(service, spreadsheet_id)
    if QUALIFICATION_SHEET not in titles:
        if not create:
            return False
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": QUALIFICATION_SHEET}}}]},
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{QUALIFICATION_SHEET}'!A1",
            valueInputOption="RAW",
            body={"values": [QUALIFICATION_HEADERS]},
        ).execute()
        return True
    values = get_values(service, spreadsheet_id, f"'{QUALIFICATION_SHEET}'!1:1")
    current = [str(value).strip() for value in values[0]] if values else []
    if not current and create:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{QUALIFICATION_SHEET}'!A1",
            valueInputOption="RAW",
            body={"values": [QUALIFICATION_HEADERS]},
        ).execute()
    elif current and current != QUALIFICATION_HEADERS:
        raise DiscoveryError(f"{QUALIFICATION_SHEET} headers do not match the required contract")
    return True


def _replace_rows(service, spreadsheet_id: str, sheet: str, headers: Sequence[str], rows: Sequence[Mapping[str, object]]) -> None:
    values = [list(headers)] + [[str(row.get(header, "")) for header in headers] for row in rows]
    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range=f"'{sheet}'!A:ZZ", body={}
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet}'!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


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
    headers, candidates = rows_from_values(get_values(service, spreadsheet_id, f"'{PROSPECT_SHEET}'!A:K"))
    ensure_expected_headers(headers, PROSPECT_HEADERS, PROSPECT_SHEET)
    signal_headers, signals = rows_from_values(get_values(service, spreadsheet_id, f"'{SIGNAL_SHEET}'!A:K"))
    ensure_expected_headers(signal_headers, SIGNAL_HEADERS, SIGNAL_SHEET)
    qualification_exists = ensure_qualification_tab(service, spreadsheet_id, create=(mode == "qualify"))

    if mode == "validate":
        _write_report(report_path, {
            "mode": mode,
            "status": "ready",
            "qualification_tab_present": qualification_exists,
            "send_permission": "none",
        })
        print(f"PROSPECT_QUALIFICATION=validated qualification_tab_present={str(qualification_exists).lower()}")
        return 0

    existing_headers, existing = rows_from_values(get_values(service, spreadsheet_id, f"'{QUALIFICATION_SHEET}'!A:Q"))
    ensure_expected_headers(existing_headers, QUALIFICATION_HEADERS, QUALIFICATION_SHEET)
    existing_by_id = {_text(row.get("candidate_id")): dict(row) for row in existing if _text(row.get("candidate_id"))}
    max_rows = clamp_int(os.getenv("PROSPECT_QUALIFICATION_MAX_PER_RUN", ""), DEFAULT_MAX_PER_RUN, 1, HARD_MAX_PER_RUN)
    client = BoundedHttpClient(
        user_agent=os.getenv("PROSPECT_QUALIFICATION_USER_AGENT", "WebactueelQualification/1.0 (+https://andrewbaeten.nl)"),
        timeout=float(os.getenv("PROSPECT_QUALIFICATION_TIMEOUT_SECONDS", "10") or "10"),
        max_bytes=clamp_int(os.getenv("PROSPECT_QUALIFICATION_MAX_BYTES", ""), 524288, 65536, 2097152),
        min_interval=float(os.getenv("PROSPECT_QUALIFICATION_MIN_INTERVAL_SECONDS", "0.5") or "0.5"),
    )

    assessed = qualified = held = rejected = 0
    for candidate in candidates:
        if assessed >= max_rows:
            break
        current_status = _text(candidate.get("status")).casefold()
        if current_status not in ELIGIBLE_STATUSES:
            continue
        candidate_id = _text(candidate.get("candidate_id"))
        website = root_url(_text(candidate.get("website")))
        if not candidate_id or not website:
            continue
        assessed += 1
        try:
            html = client.fetch_text(website)
            assessment = assess_candidate(candidate, html, signals)
        except (DiscoveryError, RuntimeError, ValueError) as exc:
            assessment = Assessment(
                0, 0, _active_signal_score(candidate_id, signals), 0, 0, "B", website,
                "", "", "website", "hold", f"qualification fetch/evidence unavailable: {type(exc).__name__}: {_text(exc)[:180]}",
            )

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
            "website_opportunity_score": assessment.website_opportunity_score,
            "signal_score": assessment.signal_score,
            "offer_fit_score": assessment.offer_fit_score,
            "customer_potential": assessment.customer_potential,
            "tier": assessment.tier,
            "evidence_url": assessment.evidence_url,
            "fact": assessment.fact,
            "idea": assessment.idea,
            "analysis_type": assessment.analysis_type,
            "status": assessment.status,
            "reason": assessment.reason,
        }

    _replace_rows(service, spreadsheet_id, PROSPECT_SHEET, PROSPECT_HEADERS, candidates)
    qualification_rows = [existing_by_id[key] for key in sorted(existing_by_id)]
    _replace_rows(service, spreadsheet_id, QUALIFICATION_SHEET, QUALIFICATION_HEADERS, qualification_rows)
    _write_report(report_path, {
        "mode": mode,
        "status": "completed",
        "assessed": assessed,
        "qualified": qualified,
        "hold": held,
        "rejected": rejected,
        "send_permission": "none",
        "note": "Qualification is deterministic, evidence-bound and bounded. It never grants compliance or send permission.",
    })
    print(f"PROSPECT_QUALIFICATION=complete assessed={assessed} qualified={qualified} hold={held} rejected={rejected}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evidence-bound bounded prospect qualification.")
    parser.add_argument("--mode", default=os.getenv("PROSPECT_QUALIFICATION_MODE", "validate"), choices=["validate", "qualify"])
    parser.add_argument("--report", default="prospect-qualification-report.json")
    args = parser.parse_args(argv)
    try:
        return run(args.mode, args.report)
    except (DiscoveryError, RuntimeError, ValueError) as exc:
        _write_report(args.report, {"mode": args.mode, "status": "blocked", "error": str(exc), "send_permission": "none"})
        print(f"PROSPECT_QUALIFICATION=blocked detail={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
