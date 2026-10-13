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
MAX_BODY_WORDS = 155
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


def copy_quality_problems(observation: str, action: str) -> list[str]:
    """Fail closed on SEO titles and canned value claims, before any Draft."""
    reasons = []
    observed = _text(observation)
    proposal = _text(action)
    # A web page title, breadcrumb or navigation label is not a business
    # observation, even if it appears on the company's own official website.
    seo_segments = re.split(r"\s+(?:-|–|—|\|)\s+", observed)
    if len(seo_segments) >= 2 and len(observed.split()) <= 16 and not re.search(r"[.!?]", observed):
        reasons.append("page_title_is_not_a_business_observation")
    if len(observed.split()) < 9:
        reasons.append("observation_lacks_usable_context")
    # Existing auto-proposals such as 'een korte voorbeeldvariant voor de
    # reserveringsroute' are promises without a verified improvement. They
    # can no longer pass as actionable, ready-to-review content.
    vague = re.search(
        r"\b(?:voorbeeldvariant|voorbeeldschets|websitebezoekersroute|"
        r"short example|reservation flow|booking flow|visitor journeys)\b",
        normalize_text(proposal),
    )
    if vague or len(proposal.split()) < 8:
        reasons.append("specific_website_improvement_not_verified")
    return reasons


def evidence_is_usable(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    if _text(item.get("source_type")) != "official_site":
        return False
    text = re.sub(r"\s+", " ", _text(item.get("text"))).strip()
    words = text.split()
    if not 6 <= len(words) <= 40:
        return False
    if "page_title_is_not_a_business_observation" in copy_quality_problems(
        text, "een concrete verbetering voor de doelgroep en de pagina"):
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
        if category_counts.get(category, 0) >= 2:
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
            "rule": "exactly_one_first_party_reason_or_hold",
        },
    }


def value_action_for(candidate: dict) -> dict:
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
    findings = candidate.get("selected_findings") or []
    signal = _text(candidate.get("signal_type"))
    match = next((entry for entry in ALL_SIGNALS if entry[0] == signal), None)
    labels = match[3] if match else OTHER_LABELS
    if len(findings) > 1:
        action = ("een korte voorbeeldschets voor de belangrijkste bezoekersroutes"
                  if language == "nl" else "a short example of the main visitor journeys")
    elif language == "nl":
        action = f"een korte voorbeeldvariant voor de {labels['nl']}"
    else:
        label = labels["en"]
        article = "an" if label[:1].lower() in "aeiou" else "a"
        action = f"{article} short example for the {label}"

    result.update({
        "value_action_status": "proposed",
        "value_action_type": "website_example",
        "value_first_action": action,
        "value_action_evidence_url": _text(candidate.get("verified_observation_source_url")),
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


def subject_for(candidate: dict) -> str:
    signal = _text(candidate.get("signal_type"))
    language = _text(candidate.get("language"))
    if language not in {"nl", "en"}:
        return ""
    if len(candidate.get("selected_findings") or []) > 1:
        return {"nl": "ideeën op basis van jullie website", "en": "ideas from your website"}[language]
    return SUBJECTS.get(signal, {"nl": "idee voor jullie website", "en": "idea for your website"})[language].casefold()


def finding_excerpt(finding: dict, *, max_words: int = 11) -> str:
    """A short, literal prefix of the cited observation; not a claimed defect."""
    observation = re.sub(r"\s+", " ", _text(finding.get("observation"))).strip()
    words = observation.replace("?", "").split()
    return " ".join(words[:max_words]) + ("…" if len(words) > max_words else "")


def safe_recipient_first_name(value: object) -> str:
    # Only a directly associated, publicly stated person's first name; never
    # address a generic mailbox as an unconfirmed owner.
    name = _text(value)
    if (
        not 3 <= len(name) <= 72
        or not re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ' -]+", name)
        or len(name.split()) < 2
    ):
        return ""
    first = name.split()[0]
    return first if len(first) >= 2 else ""


def body_for(candidate: dict) -> str:
    language = _text(candidate.get("language"))
    observation = _text(candidate.get("verified_observation"))
    action = _text(candidate.get("value_first_action"))
    findings = candidate.get("selected_findings") or []
    first = safe_recipient_first_name(candidate.get("contact_person_name"))
    greeting_nl = f"Hoi {first}," if first else "Hoi,"
    greeting_en = f"Hi {first}," if first else "Hi,"
    if len(findings) > 1:
        lines = "\n".join("- " + finding_excerpt(item) for item in findings[:MAX_DRAFT_HIGHLIGHTS])
        if language == "nl":
            return (
                f"{greeting_nl}\n\n"
                "Op jullie website vielen me deze concrete punten op:\n"
                f"{lines}\n\n"
                f"Ik kan {action} uitwerken. Zal ik een kort voorbeeld opsturen?\n\n"
                "Geen interesse? Laat het gerust weten; dan stop ik.\n\n"
                "Groet,\nAndrew Baeten"
            ).replace("Geen interesse?", "Geen interesse:")
        return (
            f"{greeting_en}\n\n"
            "I noticed these details on your website:\n"
            f"{lines}\n\n"
            f"I can prepare {action}. May I share a short example?\n\n"
            "Not relevant? Just reply no and I'll stop.\n\n"
            "Best,\nAndrew Baeten"
        ).replace("Not relevant?", "Not relevant:")
    if language == "nl":
        return (
            f"{greeting_nl}\n\n"
            f"Op jullie website viel me dit detail op: {observation}\n\n"
            f"Als je wilt, kan ik {action} maken. Dat is vrijblijvend.\n\n"
            "Zal ik dat voorbeeld per mail sturen?\n\n"
            "Geen interesse, laat het gerust weten; dan stop ik.\n\n"
            "Groet,\nAndrew Baeten"
        )
    return (
        f"{greeting_en}\n\n"
        f"I noticed one detail on your website: {observation}\n\n"
        f"If useful, I can prepare {action} with no obligation.\n\n"
        "Would you like me to email it to you?\n\n"
        "If it isn't relevant, just reply 'no' and I'll stop.\n\n"
        "Best,\nAndrew Baeten"
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
) -> tuple[str, str]:
    """One shared, review-only email renderer for new and historical leads.

    The caller must already have verified first-party identity and contact.
    This function never stages or sends anything.
    """
    if language not in {"nl", "en"} or not observation or not action:
        return "", ""
    if any(markup in observation + action for markup in ("{{", "}}", "{%", "%}", "\x00")):
        return "", ""
    if copy_quality_problems(observation, action):
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
    }
    subject, body = subject_for(candidate), body_for(candidate)
    # Website quotes may themselves contain questions; only our own CTA counts.
    quoted_questions = 0 if len(selected) > 1 else observation.count("?")
    if (
        not subject or not body or body.count("?") - quoted_questions != 1
        or len(body.split()) > MAX_BODY_WORDS
        or any(markup in body for markup in ("{{", "}}", "{%", "%}", "\x00"))
    ):
        return "", ""
    return subject, body


def validate_mail(candidate: dict, subject: str, body: str) -> list[str]:
    reasons: list[str] = []
    subject_words = subject.split()
    body_words = body.split()

    reasons.extend(copy_quality_problems(
        _text(candidate.get("verified_observation")),
        _text(candidate.get("value_first_action")),
    ))
    if (
        "Op jullie website viel me dit detail op:" in body
        or "I noticed one detail on your website:" in body
        or "Dat is vrijblijvend." in body
        or "Zal ik dat voorbeeld per mail sturen?" in body
    ):
        reasons.append("robotic_outreach_template_not_approved")

    if not subject or subject != subject.casefold():
        reasons.append("subject_must_be_lowercase")
    if len(subject_words) > MAX_SUBJECT_WORDS:
        reasons.append("subject_too_long")
    if "!" in subject or re.match(r"^(re|fwd):", subject, flags=re.I):
        reasons.append("subject_trick_or_exclamation_not_allowed")
    if len(body_words) > MAX_BODY_WORDS:
        reasons.append("body_too_long")
    # A literal website observation may include its own question mark; only
    # our call-to-action counts toward the single-question rule.
    quote_questions = 0 if len(candidate.get("selected_findings") or []) > 1 else _text(candidate.get("verified_observation")).count("?")
    if body.count("?") - quote_questions != 1:
        reasons.append("exactly_one_question_cta_required")
    if "Andrew Baeten" not in body or "Webactueel" in body:
        reasons.append("andrew_baeten_sender_identity_required")
    try:
        findings = review_findings(candidate.get("selected_findings"), candidate.get("official_domain"))
    except (ValueError, TypeError):
        findings = []
        reasons.append("review_findings_missing_or_unverified")
    if len(findings) > 1:
        # The review queue and exact approval token retain every finding.
        # A multi-point draft must quote every selected independently verified point.
        if any(finding_excerpt(item) not in body for item in findings[:MAX_DRAFT_HIGHLIGHTS]):
            reasons.append("review_findings_missing_or_unverified")
    elif _text(candidate.get("verified_observation")) not in body:
        reasons.append("verified_observation_missing_from_body")
    if _text(candidate.get("verified_observation_source_type")) != "official_site":
        reasons.append("observation_must_be_first_party")
    if _text(candidate.get("value_action_status")) != "proposed":
        reasons.append("value_action_must_be_proposed")
    if _text(candidate.get("value_first_action")) not in body:
        reasons.append("value_action_missing_from_body")

    low = normalize_text(body)
    forbidden = (
        "meeting", "call boeken", "plan een gesprek", "schedule a call", "book a call",
        "demo call", "roi", "return on investment", "garantie", "guarantee",
        "omzet", "revenue", "conversie stijgt", "increase conversions",
        "ik heb alvast", "ik heb gemaakt", "i already made", "i have made",
    )
    if any(term in low for term in forbidden):
        reasons.append("unsupported_or_high_friction_claim")
    if re.search(r"(?:€|£|\$|\b\d+(?:[.,]\d+)?\s*%)", body):
        reasons.append("price_or_percentage_not_allowed")
    if _text(candidate.get("public_business_email")) and _text(candidate.get("public_business_email")) in body:
        reasons.append("recipient_email_must_not_appear_in_body")
    return reasons


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

    # Keep weak or obviously machine-templated marketing out of the Drafts
    # folder entirely. A real published contact is not sufficient evidence
    # that an offer is interesting, specific or worth sending.
    copy_problems = copy_quality_problems(
        _text(candidate.get("verified_observation")),
        _text(candidate.get("value_first_action")),
    )
    if copy_problems:
        result["copy_validation_reasons"] = copy_problems
        return result

    subject, body = draft_for_review(
        _text(candidate.get("verified_observation")),
        _text(candidate.get("value_first_action")),
        _text(candidate.get("signal_type")),
        _text(candidate.get("language")),
        candidate.get("selected_findings"),
        _text(candidate.get("contact_person_name")),
    )
    reasons = validate_mail(candidate, subject, body) if subject and body else ["draft_quality_hold"]
    result.update({
        # Never pass known weak copy downstream merely marked as hold.
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
