#!/usr/bin/env python3
"""Cold outreach stages 7-9.

Select one first-party outreach signal, map it to one small proposed value-first
artifact, then build and semantically validate a short review-only email payload.
No mailbox mutation happens here.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse
from cold_stages import normalize_domain

MAX_CANDIDATES = 100
MAX_BODY_WORDS = 320
MIN_MAIL_IMPROVEMENTS = 3
MAX_MAIL_IMPROVEMENTS = 6
MAX_SUBJECT_WORDS = 8
MAX_DRAFT_HIGHLIGHTS = 6  # Include every verified finding, never pad weak evidence.

NL_MARKERS = (" jullie ", " onze ", " voor ", " een ", " het ", " met ", " kunnen ", " afspraak ", " offerte ")
EN_MARKERS = (" your ", " our ", " for ", " the ", " with ", " can ", " booking ", " quote ", " services ")

BLOCKED_EVIDENCE_TERMS = (
    "cookie", "privacy", "algemene voorwaarden", "terms and conditions",
    "copyright", "all rights reserved", "vacature", "solliciteer", "newsletter",
    "nieuwsbrief", "review", "testimonial", "beoordeling", "sterren",
)
GENERIC_EVIDENCE_PATTERNS = (
    r"^welkom\b",
    r"\bwij zijn (een|dé|de)\b",
    r"\bwe are (a|the)\b",
    r"\bgevestigd in\b",
    r"\bbased in\b",
    r"\bsinds \d{4}\b",
    r"\bsince \d{4}\b",
    r"^bekijk ons overzicht\b",
    r"^view our overview\b",
    r"\bwij werken op afspraak\b",
    r"\bwe work by appointment\b",
)
OPENING_HOURS_RE = re.compile(
    r"\b(maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b.*\b\d{1,2}[:.]\d{2}\b",
    re.I,
)
PRICE_OR_METRIC_RE = re.compile(r"(?:€|£|\$|\b(?:eur|euro|usd|gbp)\b|\b\d+(?:[.,]\d+)?\s*%)", re.I)
EMAIL_OR_URL_RE = re.compile(r"(?:https?://|www\.|[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63})", re.I)

SIGNALS = (
    (
        "appointment",
        100,
        (
            r"\b(?:online\s+)?(?:een\s+)?[a-z0-9-]*afspraak(?:en)?\s+(?:aanvragen|maken|plannen|boeken)\b",
            r"\b(?:maak|plan|boek|vraag)\b.{0,50}\b[a-z0-9-]*afspraak\b",
            r"\b(?:book|schedule|request)\b.{0,50}\bappointment\b",
            r"\bbook an appointment\b",
        ),
        {"nl": "afspraakroute", "en": "booking flow"},
    ),
    (
        "quote_request",
        95,
        (
            r"\b(?:offerte|offerteaanvraag)\b.{0,60}\b(?:aanvragen|aanvraag|formulier|online)\b",
            r"\b(?:vraag|aanvragen)\b.{0,50}\bofferte\b",
            r"\b(?:request|get)\b.{0,50}\b(?:a\s+)?quote\b",
            r"\bquote request\b",
        ),
        {"nl": "offerte-aanvraag", "en": "quote-request flow"},
    ),
    (
        "reservation",
        90,
        (
            r"\b(?:reserveer|reserveren|reservering)\b",
            r"\b(?:book|reserve)\b.{0,50}\b(?:table|reservation)\b",
        ),
        {"nl": "reserveringsroute", "en": "reservation flow"},
    ),
    (
        "ordering",
        85,
        (
            r"\b(?:online\s+)?bestel(?:len|t|d)?\b",
            r"\b(?:order online|online order|place an order)\b",
        ),
        {"nl": "bestelroute", "en": "ordering flow"},
    ),
)

# Categories help with sorting, but they are not exclusion gates. Every specific,
# sourced sentence can still be considered under "other" (lowest priority).
BROAD_SIGNALS = (
    ("delivery", 84, (r"\b(?:bezorg(?:ing|en)?|verzend(?:ing|en)?|afhalen|afhaalpunt|levering|delivery|shipping|pickup)\b",),
     {"nl": "lever- en afhaalroute", "en": "delivery and pickup flow"}),
    ("returns", 83, (r"\b(?:retourneren|retourbeleid|retourformulier|omruilen|returns?|refund|exchanges?)\b",),
     {"nl": "retour- en omruilroute", "en": "returns and exchange flow"}),
    ("product_information", 77, (r"\b(?:productvarianten|productdetails|producten vergelijken|maattabel|configurator|product filters|product variants|size guide|product comparison)\b",),
     {"nl": "productoriëntatie", "en": "product exploration"}),
    ("support", 73, (r"\b(?:veelgestelde vragen|faq|kennisbank|helpcentrum|supportformulier|knowledge base|help center|support request)\b",),
     {"nl": "informatie- en hulproute", "en": "help and information journey"}),
    ("contact", 71, (r"\b(?:contactformulier|contact form|stuur (?:ons )?een bericht|send us a message|neem contact op via)\b",),
     {"nl": "contactroute", "en": "contact flow"}),
    ("services", 68, (r"\b(?:onderhoudsbeurt aanvragen|reparatie aanvragen|service aanvragen|plan een onderhoud|request a repair|request a service|service request)\b",),
     {"nl": "dienstenroute", "en": "service journey"}),
    ("portfolio", 63, (r"\b(?:bekijk onze projecten|projectoverzicht|praktijkvoorbeelden|bekijk ons portfolio|view our projects|case studies)\b",),
     {"nl": "project- en voorbeeldenroute", "en": "projects and examples journey"}),
    ("navigation", 60, (r"\b(?:zoekfunctie|zoek op categorie|filter op|filter producten|find by category|search our catalog|browse categories)\b",),
     {"nl": "navigatie- en zoekroute", "en": "navigation and search journey"}),
)
ALL_SIGNALS = SIGNALS + BROAD_SIGNALS
OTHER_LABELS = {"nl": "websitebezoekersroute", "en": "website visitor journey"}
# Unknown categories remain possible, but a generic descriptive sentence is
# not by itself an actionable outreach opportunity.
SPECIFIC_OTHER_ACTION_RE = re.compile(
    r"\b(?:ontvang\w*|lever\w*|install\w*|kies|kiezen|selecteer\w*|"
    r"bekijk\w*|download\w*|vergelijk\w*|aanvraag\w*|boek\w*|"
    r"afhaal\w*|opha\w*|bestel\w*|repar\w*|zoek\w*|vind\w*|"
    r"invul\w*|aanmeld\w*|registreer\w*|"
    r"receive\w*|deliver\w*|install\w*|choose|select\w*|"
    r"view\w*|download\w*|compar\w*|request\w*|book\w*|"
    r"order\w*|repair\w*|find|search\w*|register\w*)\b",
    re.I,
)

WEAK_OUTREACH_TERMS = (
    "kwaliteit", "quality", "goede service", "great service", "service staat centraal",
    "maatwerk", "customized", "tailor-made", "vakmanschap", "craftsmanship",
    "persoonlijke aandacht", "personal attention", "betrouwbaar", "reliable",
    "jarenlange ervaring", "years of experience", "tevreden klant", "happy customer",
    "professioneel", "professional", "passie", "passion",
)


SUBJECTS = {
    "appointment": {"nl": "idee voor jullie afspraakroute", "en": "idea for your booking flow"},
    "quote_request": {"nl": "idee voor jullie offerte-aanvraag", "en": "idea for your quote flow"},
    "reservation": {"nl": "idee voor jullie reserveringsroute", "en": "idea for your reservation flow"},
    "ordering": {"nl": "idee voor jullie bestelroute", "en": "idea for your ordering flow"},
}


# Proposals, not claims of existing defects: an official-site observation must
# accompany each proposal. When fewer than 3 independent source-backed routes
# exist, the company stays on hold. Never pad with page titles or generic copy.
IMPROVEMENT_IDEAS = {
    "appointment": {
        "nl": ("Afspraken", "de keuze voor het soort afspraak en de vervolgstappen direct bij het formulier uitleggen"),
        "en": ("Appointments", "explain appointment types and the next steps alongside the form"),
    },
    "quote_request": {
        "nl": ("Offerte aanvragen", "de benodigde informatie en de volgende stap al bij de aanvraag tonen"),
        "en": ("Quote requests", "show required details and next steps by the request form"),
    },
    "reservation": {
        "nl": ("Reserveren", "keuze van tijdstip, groepsgrootte en bevestiging bij de reserveeractie verduidelijken"),
        "en": ("Reservations", "clarify times, party size and confirmation next to the reservation action"),
    },
    "ordering": {
        "nl": ("Bestellen", "bezorging en afhalen eerder als duidelijke keuzestappen tonen"),
        "en": ("Ordering", "make delivery and collection clearer as separate steps"),
    },
    "delivery": {
        "nl": ("Bezorging en afhalen", "bezorgmogelijkheden en afhaalafspraken in één overzicht tonen"),
        "en": ("Delivery and collection", "put delivery and collection options in one clear overview"),
    },
    "returns": {
        "nl": ("Retourneren", "de retourstappen en bijbehorende voorwaarden kort bij elkaar zetten"),
        "en": ("Returns", "bring the return steps and conditions into a concise overview"),
    },
    "product_information": {
        "nl": ("Productinformatie", "belangrijkste productverschillen direct vergelijkbaar maken"),
        "en": ("Product information", "make the key differences between products easy to compare"),
    },
    "support": {
        "nl": ("Veelgestelde vragen", "vragen per onderwerp bundelen met duidelijke vervolglinks"),
        "en": ("Help and FAQs", "group questions by topic with clear next links"),
    },
    "contact": {
        "nl": ("Contact", "de contactkeuzes en de gewenste vervolgstap op één plek tonen"),
        "en": ("Contact", "present contact options and the next step together"),
    },
    "services": {
        "nl": ("Diensten", "een kort keuzeoverzicht toevoegen dat bezoekers naar de juiste dienst leidt"),
        "en": ("Services", "add a short choice guide that leads visitors to the right service"),
    },
    "portfolio": {
        "nl": ("Projecten", "de voorbeelden per soort project makkelijker vindbaar maken"),
        "en": ("Projects", "make examples easier to find by project type"),
    },
    "navigation": {
        "nl": ("Navigatie", "de meest gebruikte zoek- en filterroutes bij elkaar presenteren"),
        "en": ("Navigation", "present the main search and filtering options together"),
    },
}


def looks_like_page_title(text: str) -> bool:
    """Page titles/breadcrumbs are not researched UX findings."""
    observed = re.sub(r"\s+", " ", _text(text)).strip()
    parts = re.split(r"\s+[-–—|]\s+", observed)
    return (
        len(parts) >= 2
        and len(observed.split()) <= 17
        and all(len(part.split()) <= 7 for part in parts)
        and not re.search(r"[.!?]", observed)
    )


def _text(value: object) -> str:
    return str(value or "").strip()


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", _text(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().casefold()


def _language_scores(text: str) -> tuple[int, int]:
    haystack = " " + normalize_text(text) + " "
    return (
        sum(haystack.count(marker) for marker in NL_MARKERS),
        sum(haystack.count(marker) for marker in EN_MARKERS),
    )


def detect_language(candidate: dict, observation: str) -> str:
    nl_score, en_score = _language_scores(observation)
    if nl_score > en_score:
        return "nl"
    if en_score > nl_score:
        return "en"

    # Short, specific observations may contain no reliable language marker.
    # Require corroborating official-site sentences instead of guessing from
    # a region or TLD. Mixed-language evidence remains unclassified.
    domain = normalize_domain(candidate.get("official_domain"))
    nl_total, en_total = 0, 0
    nl_support, en_support = 0, 0
    for item in (candidate.get("evidence_candidates") or [])[:30]:
        if (
            not isinstance(item, dict)
            or item.get("source_type") != "official_site"
            or not domain
            or normalize_domain(item.get("source_url")) != domain
        ):
            continue
        nl, en = _language_scores(str(item.get("text") or "")[:300])
        nl_total += nl
        en_total += en
        if nl > en:
            nl_support += 1
        elif en > nl:
            en_support += 1
    # One stray translated sentence must not choose an outreach language.
    if nl_support >= 2 and nl_total >= en_total + 2:
        return "nl"
    if en_support >= 2 and en_total >= nl_total + 2:
        return "en"
    return "unknown"


def evidence_is_usable(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    if _text(item.get("source_type")) != "official_site":
        return False
    text = re.sub(r"\s+", " ", _text(item.get("text"))).strip()
    words = text.split()
    if not 6 <= len(words) <= 40:
        return False
    if looks_like_page_title(text):
        return False
    low = normalize_text(text)
    if any(term in low for term in BLOCKED_EVIDENCE_TERMS):
        return False
    if any(re.search(pattern, low, flags=re.I) for pattern in GENERIC_EVIDENCE_PATTERNS):
        return False
    if OPENING_HOURS_RE.search(text) or PRICE_OR_METRIC_RE.search(text) or EMAIL_OR_URL_RE.search(text):
        return False
    return bool(_text(item.get("source_url")))


def classify_evidence(item: dict) -> dict | None:
    if not evidence_is_usable(item):
        return None
    observed = normalize_text(item.get("text"))
    page_type = _text(item.get("page_type")).casefold()
    best = None
    for signal_type, base_score, patterns, labels in ALL_SIGNALS:
        hits = [pattern for pattern in patterns if re.search(pattern, observed, flags=re.I)]
        if not hits:
            continue
        # Only transactional journeys benefit from being on a process page;
        # a generic portfolio or navigation mention must not be inflated.
        process_journey = signal_type in {"appointment", "quote_request", "reservation", "ordering", "services"}
        score = base_score + (15 if page_type == "process" and process_journey else 0)
        candidate = {
            "signal_type": signal_type,
            "signal_score": score,
            "matched_terms": hits[:3],
            "value_labels": labels,
        }
        if best is None or candidate["signal_score"] > best["signal_score"]:
            best = candidate
    # A category is NOT required for a factual, source-backed observation.
    # This fallback is deliberately lower priority than recognized journeys.
    if (
        best is None
        and SPECIFIC_OTHER_ACTION_RE.search(observed)
        and not any(term in observed for term in WEAK_OUTREACH_TERMS)
    ):
        best = {
            "signal_type": "other",
            "signal_score": 40 + (5 if page_type != "home" else 0),
            "matched_terms": [],
            "value_labels": OTHER_LABELS,
        }
    return best

def select_one_reason(candidate: dict) -> dict:
    result = dict(candidate)
    result.update({
        "outreach_status": "hold",
        "verified_observation": None,
        "verified_observation_source_url": None,
        "signal_type": None,
        "reason_for_outreach": None,
        "language": None,
        "selected_findings": [],
    })
    if candidate.get("research_status") != "ready":
        result["outreach_hold_reason"] = "research_not_ready"
        return result

    expected_domain = _text(candidate.get("official_domain"))
    ranked = []
    language_unknown = False
    for index, item in enumerate(candidate.get("evidence_candidates") or []):
        if not isinstance(item, dict):
            continue
        source_url = _text(item.get("source_url"))
        if expected_domain and normalize_domain(source_url) != expected_domain:
            continue
        classification = classify_evidence(item)
        if not classification:
            continue
        observation = re.sub(r"\s+", " ", _text(item["text"])).strip()
        language = detect_language(candidate, observation)
        if language not in {"nl", "en"}:
            language_unknown = True
            continue
        ranked.append((-classification["signal_score"], index, item, classification, language, observation))

    if not ranked:
        evidence_text = " ".join(
            normalize_text(item.get("text"))
            for item in candidate.get("evidence_candidates") or []
            if isinstance(item, dict)
        )
        if language_unknown:
            result["outreach_hold_reason"] = "observation_language_ambiguous"
        elif any(term in evidence_text for term in WEAK_OUTREACH_TERMS):
            result["outreach_hold_reason"] = "weak_generic_marketing_signal"
        else:
            result["outreach_hold_reason"] = "no_outreach_worthy_first_party_signal"
        return result

    ranked.sort(key=lambda entry: (entry[0], entry[1]))
    language = ranked[0][4]
    # Rank by importance first: a weak new category must not displace a
    # better-supported observation merely to make the categories diverse.
    # Suppress duplicate observations and use fewer than six when appropriate.
    selected, seen = [], set()
    category_counts: dict[str, int] = {}
    other_count = 0
    low_count = 0
    strong_count = 0
    for entry in ranked:
        if entry[4] != language:
            continue
        score, category = -entry[0], entry[3]["signal_type"]
        # Repeating one website journey is not six distinct opportunities.
        # Do not pad strong observations with unrelated, weak copy.
        if category_counts.get(category, 0) >= 1:
            continue
        if category == "other" and other_count >= 1:
            continue
        if score < 70 and (low_count >= 2 or strong_count >= 2):
            continue
        key = normalize_text(entry[5])
        if key in seen:
            continue
        seen.add(key)
        selected.append(entry)
        category_counts[category] = category_counts.get(category, 0) + 1
        other_count += category == "other"
        low_count += score < 70
        strong_count += score >= 70
        if len(selected) == 6:
            break
    findings = []
    for negative_score, _, item, classification, _, observation in selected:
        score = -negative_score
        findings.append({
            "category": classification["signal_type"],
            "priority": "high" if score >= 90 else "medium" if score >= 70 else "low",
            "score": score,
            "observation": observation,
            "source_url": _text(item["source_url"]),
            "source_type": "official_site",
            "page_type": _text(item.get("page_type")) or "detail",
        })
    result["selected_findings"] = findings
    eligible_categories = [f["category"] for f in findings if f["category"] in IMPROVEMENT_IDEAS]
    if len(eligible_categories) < MIN_MAIL_IMPROVEMENTS:
        result["outreach_hold_reason"] = "fewer_than_three_distinct_verified_improvements"
        return result
    top = findings[0]
    result.update({
        "outreach_status": "ready",
        "outreach_hold_reason": None,
        "verified_observation": top["observation"],
        "verified_observation_source_url": top["source_url"],
        "verified_observation_source_type": "official_site",
        "signal_type": top["category"],
        "signal_score": top["score"],
        "reason_for_outreach": top["observation"],
        "language": language,
        "selected_findings": findings,
    })
    return result

def select_reasons(payload: dict) -> dict:
    candidates = payload.get("candidates") or []
    if not isinstance(candidates, list):
        raise ValueError("candidates_must_be_list")
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError("candidate_limit_exceeded")
    results = [select_one_reason(item) for item in candidates if isinstance(item, dict)]
    return {
        "schema_version": "leadscanner-cold-outreach-reason/1.0",
        "candidate_count": len(results),
        "ready_count": sum(1 for item in results if item.get("outreach_status") == "ready"),
        "candidates": results,
        "handoff": {
            "next": "value_first_action",
            "rule": "three_to_six_distinct_first_party_improvements_or_hold",
        },
    }


def value_action_for(candidate: dict) -> dict:
    """Prepare three to six distinct, traceable improvement ideas or hold."""
    result = dict(candidate)
    result.update({
        "value_action_status": "hold",
        "value_action_type": None,
        "value_first_action": None,
        "value_action_evidence_url": None,
    })
    if candidate.get("outreach_status") != "ready":
        return result
    language = _text(candidate.get("language"))
    if language not in {"nl", "en"}:
        result["value_action_hold_reason"] = "language_not_verified"
        return result
    domain = normalize_domain(candidate.get("official_domain"))
    selected = []
    seen_categories = set()
    for raw in candidate.get("selected_findings") or []:
        if not isinstance(raw, dict):
            continue
        category = _text(raw.get("category"))
        idea = IMPROVEMENT_IDEAS.get(category, {}).get(language)
        if (
            not idea or category in seen_categories
            or raw.get("source_type") != "official_site"
            or not domain or normalize_domain(raw.get("source_url")) != domain
            or not _text(raw.get("observation")) or looks_like_page_title(_text(raw.get("observation")))
        ):
            continue
        selected.append({
            **raw, "topic_label": idea[0], "suggested_improvement": idea[1],
        })
        seen_categories.add(category)
    if not MIN_MAIL_IMPROVEMENTS <= len(selected) <= MAX_MAIL_IMPROVEMENTS:
        result["value_action_hold_reason"] = "fewer_than_three_distinct_verified_improvements"
        return result
    action = (
        "een nieuwe voorbeeldopzet van een van deze onderdelen"
        if language == "nl"
        else "a redesigned example of one of these sections"
    )
    result.update({
        "selected_findings": selected,
        "verified_observation": selected[0]["observation"],
        "verified_observation_source_url": selected[0]["source_url"],
        "verified_observation_source_type": "official_site",
        "signal_type": selected[0]["category"],
        "value_action_status": "proposed",
        "value_action_type": "website_example",
        "value_first_action": action,
        "value_action_evidence_url": selected[0]["source_url"],
        "value_action_hold_reason": None,
    })
    return result


def choose_value_actions(payload: dict) -> dict:
    candidates = payload.get("candidates") or []
    if not isinstance(candidates, list):
        raise ValueError("candidates_must_be_list")
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError("candidate_limit_exceeded")
    results = [value_action_for(item) for item in candidates if isinstance(item, dict)]
    return {
        "schema_version": "leadscanner-cold-value-action/1.0",
        "candidate_count": len(results),
        "ready_count": sum(1 for item in results if item.get("value_action_status") == "proposed"),
        "candidates": results,
        "handoff": {
            "next": "mail_generation",
            "artifact_truth": "proposed_only",
        },
    }


def site_kind(candidate: dict, language: str) -> str:
    """Never infer a webshop just because a restaurant takes online orders."""
    kind = _text(candidate.get("website_type")).casefold()
    if kind in {"webshop", "online_store", "ecommerce"}:
        return "webshop" if language == "nl" else "online store"
    return "website"


def subject_for(candidate: dict) -> str:
    language = _text(candidate.get("language"))
    findings = candidate.get("selected_findings") or []
    if language not in {"nl", "en"} or not MIN_MAIL_IMPROVEMENTS <= len(findings) <= MAX_MAIL_IMPROVEMENTS:
        return ""
    count = len(findings)
    kind = site_kind(candidate, language)
    return (
        f"{count} verbeterideeën voor jullie {kind}"
        if language == "nl" else f"{count} practical ideas for your {kind}"
    ).casefold()


def finding_excerpt(finding: dict, *, max_words: int | None = None) -> str:
    """Preserve actual source text, rather than an awkward cut-off SEO quote."""
    observation = re.sub(r"\s+", " ", _text(finding.get("observation"))).strip()
    if max_words is not None and len(observation.split()) > max_words:
        return " ".join(observation.split()[:max_words]) + "…"
    return observation


def safe_recipient_first_name(value: object) -> str:
    # Only a directly associated publicly stated name; never invent an owner.
    name = _text(value)
    if (
        not 3 <= len(name) <= 72
        or not re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ' -]+", name)
        or len(name.split()) < 2
    ):
        return ""
    first = name.split()[0]
    return first if len(first) >= 2 else ""


def improvement_line(finding: dict, language: str, number: int) -> str:
    """Explicit observation + honest proposed fix; no unsupported defect."""
    category = _text(finding.get("category"))
    expected = IMPROVEMENT_IDEAS.get(category, {}).get(language)
    if expected is None:
        return ""
    label, suggestion = expected
    if (finding.get("topic_label") != label
            or finding.get("suggested_improvement") != suggestion
            or finding.get("source_type") != "official_site"):
        return ""
    observed = finding_excerpt(finding).rstrip(" .")
    if not observed or looks_like_page_title(observed):
        return ""
    if language == "nl":
        return f"{number}. {label}: {observed}.\n   Verbeteridee: {suggestion}."
    return f"{number}. {label}: {observed}.\n   Suggested improvement: {suggestion}."


def body_for(candidate: dict) -> str:
    """A Dutch/English draft with 3–6 independently grounded improvements."""
    language = _text(candidate.get("language"))
    findings = candidate.get("selected_findings") or []
    action = _text(candidate.get("value_first_action"))
    if (
        language not in {"nl", "en"}
        or not MIN_MAIL_IMPROVEMENTS <= len(findings) <= MAX_MAIL_IMPROVEMENTS
        or not action
        or len({_text(f.get("category")) for f in findings if isinstance(f, dict)}) != len(findings)
    ):
        return ""
    lines = [improvement_line(f, language, i) for i, f in enumerate(findings, 1)]
    if any(not line for line in lines):
        return ""
    points = "\n".join(lines)
    first = safe_recipient_first_name(candidate.get("contact_person_name"))
    kind = site_kind(candidate, language)
    if language == "nl":
        greeting = f"Beste {first}," if first else "Beste,"
        return (
            f"{greeting}\n\n"
            f"Ik heb jullie {kind} bekeken en geanalyseerd. "
            f"Dit zijn {len(findings)} concrete punten die me opvielen, "
            "met een verbetervoorstel bij ieder punt:\n\n"
            f"{points}\n\n"
            f"Ik kan vrijblijvend {action} uitwerken en per mail sturen. "
            "Zou je zo'n voorbeeld willen ontvangen?\n\n"
            "Als je geen interesse hebt, hoef je niet te reageren.\n\n"
            "Met vriendelijke groeten,\nAndrew"
        )
    greeting = f"Dear {first}," if first else "Dear team,"
    return (
        f"{greeting}\n\n"
        f"I reviewed and analysed your {kind}. "
        f"These {len(findings)} concrete points stood out, "
        "with a practical improvement idea for each:\n\n"
        f"{points}\n\n"
        f"I can prepare {action} free of charge and email it over. "
        "Would you like to see an example?\n\n"
        "If you're not interested, there's no need to reply.\n\n"
        "Kind regards,\nAndrew"
    )


def review_findings(findings: object, domain: object) -> list[dict]:
    """Return verified, ordered first-party findings; reject unsafe review data.

    Legacy single-observation reviews may pass no list. This one contract is
    shared by mail generation, review queues, approvals and historical drafts.
    """
    if findings is None or findings == []:
        return []
    if not isinstance(findings, list) or len(findings) > 6:
        raise ValueError("review_findings_must_be_list_of_at_most_six")
    expected_domain = normalize_domain(domain)
    if not expected_domain:
        raise ValueError("review_findings_require_official_domain")
    verified = []
    seen = set()
    for item in findings:
        if not isinstance(item, dict):
            raise ValueError("review_finding_must_be_object")
        observation = _text(item.get("observation"))
        url = _text(item.get("source_url"))
        parsed = urlparse(url)
        if (
            item.get("source_type") != "official_site"
            or not observation or not url
            or parsed.scheme not in {"http", "https"}
            or parsed.username is not None or parsed.password is not None
            or normalize_domain(url) != expected_domain
            or any(marker in observation for marker in ("{{", "}}", "{%", "%}", "\x00"))
        ):
            raise ValueError("review_findings_require_verified_official_site")
        key = (normalize_text(observation), url)
        if key in seen:
            raise ValueError("duplicate_review_finding")
        seen.add(key)
        verified.append(dict(item))
    return verified


def draft_for_review(
    observation: str, action: str, signal: str, language: str,
    findings: list[dict] | None = None,
    contact_person_name: str | None = None,
    website_type: str | None = None,
) -> tuple[str, str]:
    """One shared, review-only email renderer for new and historical leads.

    The caller must already have verified first-party identity and contact.
    This function never stages or sends anything.
    """
    if language not in {"nl", "en"} or not observation or not action:
        return "", ""
    if any(markup in observation + action for markup in ("{{", "}}", "{%", "%}", "\x00")):
        return "", ""
    try:
        source_domain = normalize_domain((findings or [{}])[0].get("source_url"))
        selected = review_findings(findings, source_domain)
    except (ValueError, AttributeError, TypeError):
        return "", ""
    candidate = {
        "verified_observation": observation,
        "value_first_action": action,
        "signal_type": signal,
        "language": language,
        "selected_findings": selected,
        "contact_person_name": contact_person_name,
        "website_type": website_type,
    }
    subject, body = subject_for(candidate), body_for(candidate)
    # Website quotes may themselves contain questions; only our own CTA counts.
    quoted_questions = sum(finding_excerpt(item).count("?") for item in selected)
    if (
        not subject or not body or body.count("?") - quoted_questions != 1
        or len(body.split()) > MAX_BODY_WORDS
        or any(markup in body for markup in ("{{", "}}", "{%", "%}", "\x00"))
    ):
        return "", ""
    return subject, body


def validate_mail(candidate: dict, subject: str, body: str) -> list[str]:
    """No green status for generic one-point or unsupported marketing mail."""
    reasons: list[str] = []
    subject_words = subject.split()
    body_words = body.split()
    if not subject or subject != subject.casefold():
        reasons.append("subject_must_be_lowercase")
    if subject != subject_for(candidate):
        reasons.append("subject_must_match_number_of_improvements")
    if len(subject_words) > MAX_SUBJECT_WORDS:
        reasons.append("subject_too_long")
    if "!" in subject or re.match(r"^(re|fwd):", subject, flags=re.I):
        reasons.append("subject_trick_or_exclamation_not_allowed")
    if len(body_words) > MAX_BODY_WORDS:
        reasons.append("body_too_long")
    try:
        findings = review_findings(candidate.get("selected_findings"), candidate.get("official_domain"))
    except (ValueError, TypeError):
        findings = []
        reasons.append("review_findings_missing_or_unverified")
    if not MIN_MAIL_IMPROVEMENTS <= len(findings) <= MAX_MAIL_IMPROVEMENTS:
        reasons.append("requires_three_to_six_sourced_improvements")
    if len({_text(f.get("category")) for f in findings}) != len(findings):
        reasons.append("duplicate_improvement_category")
    lang = _text(candidate.get("language"))
    for n, finding in enumerate(findings, 1):
        line = improvement_line(finding, lang, n)
        if not line or line not in body:
            reasons.append("sourced_improvement_missing_or_unreviewed")
            break
    observed_questions = sum(finding_excerpt(finding).count("?") for finding in findings)
    if body.count("?") - observed_questions != 1:
        reasons.append("exactly_one_question_cta_required")
    if not body.endswith((
        "Met vriendelijke groeten,\nAndrew" if lang == "nl"
        else "Kind regards,\nAndrew" if lang == "en" else ""
    )) or not body.endswith("\nAndrew"):
        reasons.append("verified_andrew_signature_required")
    if not body.startswith("Beste") and lang == "nl":
        reasons.append("dutch_greeting_required")
    if not body.startswith("Dear") and lang == "en":
        reasons.append("english_greeting_required")
    if "Webactueel" in body:
        reasons.append("unapproved_sender_brand")
    if _text(candidate.get("verified_observation_source_type")) != "official_site":
        reasons.append("observation_must_be_first_party")
    if _text(candidate.get("value_action_status")) != "proposed":
        reasons.append("value_action_must_be_proposed")
    if _text(candidate.get("value_first_action")) not in body:
        reasons.append("value_action_missing_from_body")
    if (
        "Als je geen interesse hebt, hoef je niet te reageren." not in body
        if lang == "nl" else
        "If you're not interested, there's no need to reply." not in body
    ):
        reasons.append("no_reply_needed_when_not_interested")
    low = normalize_text(body)
    forbidden = (
        "meeting", "call boeken", "plan een gesprek", "schedule a call",
        "book a call", "demo call", "roi", "return on investment",
        "garantie", "guarantee", "omzet", "revenue",
        "conversie stijgt", "increase conversions",
        "ik heb alvast", "ik heb gemaakt", "i already made", "i have made",
        "op jullie website viel me dit detail op", "i noticed one detail on your website",
    )
    if any(term in low for term in forbidden):
        reasons.append("unsupported_or_robotic_marketing_claim")
    if re.search(r"(?:€|£|\$|\b\d+(?:[.,]\d+)?\s*%)", body):
        reasons.append("price_or_percentage_not_allowed")
    if _text(candidate.get("public_business_email")) and _text(candidate.get("public_business_email")) in body:
        reasons.append("recipient_email_must_not_appear_in_body")
    return list(dict.fromkeys(reasons))


def generate_one_mail(candidate: dict) -> dict:
    result = dict(candidate)
    result.update({
        "mail_status": "hold",
        "subject": None,
        "body": None,
        "copy_validation_status": "not_run",
        "copy_validation_reasons": [],
        "draft_status": "not_created",
        "automatic_send": False,
    })
    if candidate.get("value_action_status") != "proposed":
        result["copy_validation_reasons"] = ["value_action_not_ready"]
        return result
    # Website opportunity research is independent of having an email.
    # A reviewable recipient-specific concept still needs a sourced address.
    if not _text(candidate.get("public_business_email")):
        result["copy_validation_reasons"] = ["no_published_business_contact"]
        return result
    if candidate.get("contact_status") not in {None, "", "verified_official_site"}:
        result["copy_validation_reasons"] = ["unverified_business_contact"]
        return result

    subject, body = draft_for_review(
        _text(candidate.get("verified_observation")),
        _text(candidate.get("value_first_action")),
        _text(candidate.get("signal_type")),
        _text(candidate.get("language")),
        candidate.get("selected_findings"),
        _text(candidate.get("contact_person_name")),
        _text(candidate.get("website_type")),
    )
    reasons = validate_mail(candidate, subject, body) if subject and body else ["draft_quality_hold"]
    result.update({
        "subject": subject if not reasons else None,
        "body": body if not reasons else None,
        "copy_validation_status": "green" if not reasons else "hold",
        "copy_validation_reasons": reasons,
        "mail_status": "ready_for_human_review" if not reasons else "hold",
    })
    return result


def generate_mails(payload: dict) -> dict:
    candidates = payload.get("candidates") or []
    if not isinstance(candidates, list):
        raise ValueError("candidates_must_be_list")
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError("candidate_limit_exceeded")
    results = [generate_one_mail(item) for item in candidates if isinstance(item, dict)]
    return {
        "schema_version": "leadscanner-cold-mail/1.0",
        "candidate_count": len(results),
        "ready_for_human_review_count": sum(1 for item in results if item.get("mail_status") == "ready_for_human_review"),
        "candidates": results,
        "safety": {
            "draft_created": False,
            "mailbox_mutation": False,
            "automatic_send": False,
            "human_review_required": True,
        },
        "handoff": {
            "next": "private_myhost_drafts_after_quality_check",
        },
    }


def _read(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("input_must_be_object")
    return data


def _write(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("select", "value", "mail"):
        child = sub.add_parser(name)
        child.add_argument("--input", required=True)
        child.add_argument("--output", required=True)
    args = parser.parse_args()

    source = _read(args.input)
    if args.command == "select":
        result = select_reasons(source)
        label = f"OUTREACH_REASON=green ready={result['ready_count']}"
    elif args.command == "value":
        result = choose_value_actions(source)
        label = f"VALUE_ACTION=green ready={result['ready_count']}"
    else:
        result = generate_mails(source)
        label = f"COLD_MAIL=green ready_for_human_review={result['ready_for_human_review_count']} draft=false send=false"
    _write(args.output, result)
    print(label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
