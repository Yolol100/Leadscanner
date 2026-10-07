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

MAX_CANDIDATES = 100
MAX_BODY_WORDS = 100
MAX_SUBJECT_WORDS = 8

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
        ("afspraak", "afspraken", "appointment", "appointments", "booking", "book an appointment"),
        {"nl": "afspraakroute", "en": "booking flow"},
    ),
    (
        "quote_request",
        95,
        ("offerte", "offerteaanvraag", "quote request", "request a quote", "quotation"),
        {"nl": "offerte-aanvraag", "en": "quote-request flow"},
    ),
    (
        "reservation",
        90,
        ("reserver", "reservation", "reserveer", "reserve a table", "book a table"),
        {"nl": "reserveringsroute", "en": "reservation flow"},
    ),
    (
        "ordering",
        85,
        ("bestel", "bestellen", "order online", "online order", "ordering", "online bestellen"),
        {"nl": "bestelroute", "en": "ordering flow"},
    ),
    (
        "treatment_offer",
        72,
        ("behandeling", "behandelingen", "treatment", "treatments"),
        {"nl": "behandelingsaanbod", "en": "treatment section"},
    ),
    (
        "service_offer",
        65,
        ("dienst", "diensten", "service", "services", "werkwijze", "how we work"),
        {"nl": "dienstenpresentatie", "en": "services section"},
    ),
    (
        "product_offer",
        60,
        ("product", "producten", "assortiment", "menu", "collection", "range"),
        {"nl": "aanbodpresentatie", "en": "offer section"},
    ),
)

SUBJECTS = {
    "appointment": {"nl": "idee voor jullie afspraakroute", "en": "idea for your booking flow"},
    "quote_request": {"nl": "idee voor jullie offerte-aanvraag", "en": "idea for your quote flow"},
    "reservation": {"nl": "idee voor jullie reserveringsroute", "en": "idea for your reservation flow"},
    "ordering": {"nl": "idee voor jullie bestelroute", "en": "idea for your ordering flow"},
    "treatment_offer": {"nl": "idee voor jullie behandelingsaanbod", "en": "idea for your treatment section"},
    "service_offer": {"nl": "idee voor jullie dienstenpagina", "en": "idea for your services section"},
    "product_offer": {"nl": "idee voor jullie aanbod", "en": "idea for your offer section"},
}


def _text(value: object) -> str:
    return str(value or "").strip()


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", _text(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().casefold()


def detect_language(candidate: dict, observation: str) -> str:
    haystack = " " + normalize_text(observation) + " "
    nl_score = sum(haystack.count(marker) for marker in NL_MARKERS)
    en_score = sum(haystack.count(marker) for marker in EN_MARKERS)
    if nl_score > en_score:
        return "nl"
    if en_score > nl_score:
        return "en"
    domain = _text(candidate.get("official_domain")).casefold()
    return "nl" if domain.endswith(".nl") else "en"


def evidence_is_usable(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    if _text(item.get("source_type")) != "official_site":
        return False
    text = re.sub(r"\s+", " ", _text(item.get("text"))).strip()
    words = text.split()
    if not 6 <= len(words) <= 40:
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
    text = normalize_text(item.get("text"))
    page_type = _text(item.get("page_type")).casefold()
    best = None
    for signal_type, base_score, terms, labels in SIGNALS:
        hits = [term for term in terms if normalize_text(term) in text]
        if not hits:
            continue
        score = base_score
        if page_type == "process" and signal_type in {"appointment", "quote_request", "reservation", "ordering"}:
            score += 15
        elif page_type in {"services", "products"} and signal_type in {"treatment_offer", "service_offer", "product_offer"}:
            score += 8
        candidate = {
            "signal_type": signal_type,
            "signal_score": score,
            "matched_terms": hits[:3],
            "value_labels": labels,
        }
        if best is None or candidate["signal_score"] > best["signal_score"]:
            best = candidate
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
    })
    if candidate.get("research_status") != "ready":
        result["outreach_hold_reason"] = "research_not_ready"
        return result

    ranked: list[tuple[int, int, dict, dict]] = []
    for index, item in enumerate(candidate.get("evidence_candidates") or []):
        classification = classify_evidence(item)
        if classification:
            ranked.append((-classification["signal_score"], index, item, classification))
    if not ranked:
        result["outreach_hold_reason"] = "no_outreach_worthy_first_party_signal"
        return result

    ranked.sort(key=lambda entry: (entry[0], entry[1]))
    _, _, item, classification = ranked[0]
    observation = re.sub(r"\s+", " ", _text(item["text"])).strip()
    language = detect_language(candidate, observation)
    result.update({
        "outreach_status": "ready",
        "outreach_hold_reason": None,
        "verified_observation": observation,
        "verified_observation_source_url": _text(item["source_url"]),
        "verified_observation_source_type": "official_site",
        "signal_type": classification["signal_type"],
        "signal_score": classification["signal_score"],
        "reason_for_outreach": observation,
        "language": language,
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

    signal = _text(candidate.get("signal_type"))
    language = _text(candidate.get("language")) or "nl"
    match = next((entry for entry in SIGNALS if entry[0] == signal), None)
    if not match:
        result["value_action_hold_reason"] = "unsupported_signal_type"
        return result

    label = match[3][language]
    if language == "nl":
        action = f"een korte voorbeeldvariant voor de {label}"
    else:
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
    language = _text(candidate.get("language")) or "nl"
    return SUBJECTS[signal][language].casefold()


def body_for(candidate: dict) -> str:
    language = _text(candidate.get("language")) or "nl"
    observation = _text(candidate.get("verified_observation"))
    action = _text(candidate.get("value_first_action"))
    if language == "nl":
        return (
            "Hallo,\n\n"
            f"Op jullie site viel me dit op: {observation}\n\n"
            f"Ik kan vrijblijvend {action} maken om te laten zien hoe ik dit online zou aanpakken.\n\n"
            "Zal ik die sturen?\n\n"
            "Geen interesse? Laat het gerust weten.\n\n"
            "Groet,\nAndrew"
        )
    return (
        "Hello,\n\n"
        f"This stood out to me on your site: {observation}\n\n"
        f"I can create {action} with no obligation to show how I would approach this online.\n\n"
        "Want me to send it?\n\n"
        "Not interested? Just let me know.\n\n"
        "Best,\nAndrew"
    )


def validate_mail(candidate: dict, subject: str, body: str) -> list[str]:
    reasons: list[str] = []
    subject_words = subject.split()
    body_words = body.split()

    if not subject or subject != subject.casefold():
        reasons.append("subject_must_be_lowercase")
    if len(subject_words) > MAX_SUBJECT_WORDS:
        reasons.append("subject_too_long")
    if "!" in subject or re.match(r"^(re|fwd):", subject, flags=re.I):
        reasons.append("subject_trick_or_exclamation_not_allowed")
    if len(body_words) > MAX_BODY_WORDS:
        reasons.append("body_too_long")
    if body.count("?") != 1:
        reasons.append("exactly_one_question_cta_required")
    if _text(candidate.get("verified_observation")) not in body:
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

    subject = subject_for(candidate)
    body = body_for(candidate)
    reasons = validate_mail(candidate, subject, body)
    result.update({
        "subject": subject,
        "body": body,
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
            "next": "review_draft_storage_not_yet_implemented",
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
