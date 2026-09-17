from __future__ import annotations

import re
from dataclasses import dataclass

CONTRACT_ID = "curiosity_first_v17_2"
POLICY_VERSION = "17.2.3"
OPT_OUT_NL = 'Geen interesse? Een kort "nee" is genoeg.'
OPT_OUT_EN = 'Not interested? A quick "no" is enough.'
COMMERCIAL_NL = "Dit is een commercieel bericht."
COMMERCIAL_EN = "This is a commercial message."
SIGNATURE_NL = "Met vriendelijke groet,\nAndrew Baeten"
SIGNATURE_EN = "Best regards,\nAndrew Baeten"
POSTAL_PLACEHOLDER = "{{OUTREACH_POSTAL_ADDRESS}}"

CTA_NL = ("Zal ik het voorbeeld sturen?", "Mag ik het voorbeeld sturen?")
CTA_EN = ("Want me to send the example?", "Would you like me to send the example?")

GENERIC_OBSERVATION_PATTERNS = (
    re.compile(r"(?i)^ik zag (?:jullie|uw) website[.! ]*$"),
    re.compile(r"(?i)^ik zag iets interessants[.! ]*$"),
    re.compile(r"(?i)^i (?:saw|looked at) your website[.! ]*$"),
    re.compile(r"(?i)^i noticed something interesting[.! ]*$"),
)
SOLUTION_SPOILER_PATTERNS = (
    re.compile(r"(?i)zou dat bijvoorbeeld kunnen betekenen\s*:"),
    re.compile(r"(?i)that could mean\s*:"),
    re.compile(r"(?i)\b(?:stap|step)\s*1\b"),
    re.compile(r"(?i)\beerst\b.{0,80}\bdaarna\b"),
    re.compile(r"(?i)\bfirst\b.{0,80}\bthen\b"),
    re.compile(r"(?i)\b(?:ik|we)\s+(?:zou(?:den)?\s+)?(?:automatiseren|implementeren|bouwen|integreren)\b"),
    re.compile(r"(?i)\b(?:i|we)\s+(?:would\s+)?(?:automate|implement|build|integrate)\b"),
    re.compile(r"(?i)\bklanten\s+beantwoorden\b.{0,80}\bvragen\b"),
    re.compile(r"(?i)\bcustomers?\s+answer\b.{0,80}\bquestions?\b"),
)

HARD_PRICE_PATTERNS = (
    re.compile(r"(?i)(?:€|\$|£)\s*\d"),
    re.compile(r"(?i)\b(?:korting|discount)\b"),
)
SOFT_PRICE_TERM = re.compile(r"(?i)\b(?:prijs|prijzen|kosten|fee|tarief|price|pricing|cost|costs)\b")
OBSERVATION_EVIDENCE_CONTEXT = re.compile(
    r"(?i)\b(?:site|website|pagina|page|faq|formulier|form|route|flow|offerte|quote|request|aanvraag|"
    r"upload|print|part|product|service|section|sectie|knop|button|checkout|cart|retour|return)\b"
)
SELLER_PRICE_CLAIM = re.compile(
    r"(?i)\b(?:ik|wij|we|i)\b.{0,35}\b(?:prijs|prijzen|kosten|fee|tarief|price|pricing|cost|costs)\b"
)

PRESSURE_PATTERNS = (
    re.compile(r"(?i)\b(?:gegarandeerd|guaranteed|guarantees|last chance|laatste kans|only today|alleen vandaag)\b"),
)
GUARANTEE_TERM = re.compile(r"(?i)\b(?:garantie|guarantee|guarantees|warranty)\b")
GUARANTEE_CLAIM_PATTERNS = (
    re.compile(r"(?i)\b(?:ik|wij|we|i)\b.{0,30}\b(?:garandeer|garanderen|guarantee|guarantees)\b"),
    re.compile(r"(?i)\bgarantie\s+(?:op|voor)\s+(?:resultaat|resultaten|omzet|klanten|aanvragen|leads)\b"),
    re.compile(r"(?i)\bguarantee(?:d|s)?\s+(?:results?|revenue|sales|customers?|leads?)\b"),
)

PRICE_PATTERNS = HARD_PRICE_PATTERNS + (SOFT_PRICE_TERM,)
HYPE_PATTERNS = PRESSURE_PATTERNS + (GUARANTEE_TERM,)

UNSUPPORTED_SEVERITY_LOSS_PATTERNS = (
    re.compile(r"(?i)\b(?:cruciaal|kritiek|kritisch|urgent|dringend|crucial|critical)\b"),
    re.compile(r"(?i)\b(?:moet|moeten)\s+(?:direct|meteen|onmiddellijk)\b"),
    re.compile(r"(?i)\b(?:must|needs? to)\s+(?:be\s+)?(?:fixed|fix|solved|resolved)\s+(?:immediately|right now|urgently)\b"),
    re.compile(r"(?i)\b(?:direct|meteen|onmiddellijk)\s+(?:fixen|oplossen|repareren)\b"),
    re.compile(r"(?i)\b(?:verlies|verliest|verliezen|mislopen|misloopt)\b.{0,50}\b(?:klanten|omzet|geld|aanvragen|leads)\b"),
    re.compile(r"(?i)\b(?:klanten|omzet|geld|aanvragen|leads)\b.{0,50}\b(?:verlies|verliest|verliezen|mislopen|misloopt)\b"),
    re.compile(r"(?i)\b(?:laat|laten)\b.{0,35}\b(?:geld|omzet|klanten|aanvragen|leads)\b.{0,20}\bliggen\b"),
    re.compile(r"(?i)\b(?:losing|lose|lost)\b.{0,50}\b(?:customers?|revenue|money|leads?|sales)\b"),
    re.compile(r"(?i)\b(?:customers?|revenue|money|leads?|sales)\b.{0,50}\b(?:losing|lose|lost)\b"),
    re.compile(r"(?i)\bleav(?:e|ing)\b.{0,25}\b(?:money|revenue|sales)\b.{0,20}\bon the table\b"),
)
MEETING_PATTERNS = (
    re.compile(r"(?i)\b(?:plan|boek|reserveer|schedule|book)\b.{0,60}\b(?:call|meeting|gesprek|agenda|minuten|minutes)\b"),
)

# V17.2.3 human-language gate. These patterns are deliberately narrow: they block
# common scrape/navigation residue and internal labels without treating ordinary
# prospect vocabulary as an error.
SCRAPE_RESIDUE_PATTERNS = (
    re.compile(r"(?i)\bskip\s+to\s+content\b"),
    re.compile(r"(?i)^\s*(?:menu|home|search|contact)\s*$"),
    re.compile(r"^\s*(?:\+?\d[\d\s().-]{6,})\s*$"),
)
INTERNAL_LABEL_PATTERNS = (
    re.compile(r"(?i)\brequest-pricing\b"),
    re.compile(r"(?i)\brequest-quote\b"),
    re.compile(r"(?i)\b(?:request_pricing|request_quote)\b"),
)
REDUNDANT_EXAMPLE_PATTERNS = (
    re.compile(r"(?i)\béén\s+klein\s+mini[- ]?flow\b"),
    re.compile(r"(?i)\bone\s+small\s+mini[- ]?flow\b"),
    re.compile(r"(?i)\bsmall\s+mini[- ]?flow\b"),
)
NL_IN_EN_PATTERNS = (
    re.compile(r"(?i)\b(?:op jullie site|daar viel me|ik heb|zal ik|mag ik)\b"),
)
EN_IN_NL_PATTERNS = (
    re.compile(r"(?i)\b(?:i noticed|one point|i made|want me to|would you like me to)\b"),
)


@dataclass(frozen=True)
class CopyDraft:
    subject: str
    body: str
    followup_subject: str
    followup_body: str
    followup_delay_days: int
    contract_id: str = CONTRACT_ID


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\wÀ-ÿ'-]+\b", text or ""))


def _subject_errors(subject: str) -> list[str]:
    value = str(subject or "").strip()
    if not value:
        return ["missing subject"]
    errors: list[str] = []
    words = _word_count(value)
    if words < 2 or words > 6:
        errors.append("subject must contain 2-6 ordinary words")
    if re.match(r"(?i)^(?:re|fw|fwd)\s*:", value):
        errors.append("fake reply or forward subject is not allowed")
    if re.search(r"(?i)\b(?:AI|A\.I\.|automation|automatisering|bot|chatbot)\b", value):
        errors.append("subject must describe the prospect signal, not AI or automation")
    if any(pattern.search(value) for pattern in HYPE_PATTERNS):
        errors.append("clickbait or pressure subject is not allowed")
    if any(pattern.search(value) for pattern in UNSUPPORTED_SEVERITY_LOSS_PATTERNS):
        errors.append("subject may not use unsupported severity or loss language")
    return errors


def _paragraphs(body: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", str(body or "").strip()) if part.strip()]


def _language_from_body(body: str) -> str:
    text = str(body or "")
    if OPT_OUT_NL in text or COMMERCIAL_NL in text:
        return "nl"
    if OPT_OUT_EN in text or COMMERCIAL_EN in text:
        return "en"
    return ""


def _observation_from_body(body: str) -> str:
    parts = _paragraphs(body)
    if len(parts) < 2:
        return ""
    return parts[1]


def _body_without_observation(body: str) -> str:
    parts = _paragraphs(body)
    if len(parts) < 2:
        return str(body or "")
    return "\n\n".join(parts[:1] + parts[2:])


def _observation_allows_soft_price_term(observation: str) -> bool:
    text = str(observation or "")
    return bool(
        SOFT_PRICE_TERM.search(text)
        and OBSERVATION_EVIDENCE_CONTEXT.search(text)
        and not SELLER_PRICE_CLAIM.search(text)
        and not any(pattern.search(text) for pattern in HARD_PRICE_PATTERNS)
    )


def _observation_allows_guarantee_term(observation: str) -> bool:
    text = str(observation or "")
    return bool(
        GUARANTEE_TERM.search(text)
        and OBSERVATION_EVIDENCE_CONTEXT.search(text)
        and not any(pattern.search(text) for pattern in GUARANTEE_CLAIM_PATTERNS)
        and not any(pattern.search(text) for pattern in PRESSURE_PATTERNS)
    )


def _human_language_errors(text: str, *, language: str, observation: str) -> list[str]:
    errors: list[str] = []
    if any(pattern.search(observation) for pattern in SCRAPE_RESIDUE_PATTERNS):
        errors.append("first-touch observation contains scrape or navigation residue")
    if any(pattern.search(text) for pattern in INTERNAL_LABEL_PATTERNS):
        errors.append("first-touch contains an internal or machine-like label")
    if any(pattern.search(text) for pattern in REDUNDANT_EXAMPLE_PATTERNS):
        errors.append("first-touch contains redundant mini-flow wording")
    if language == "nl" and any(pattern.search(text) for pattern in EN_IN_NL_PATTERNS):
        errors.append("first-touch contains unnecessary language mixing")
    if language == "en" and any(pattern.search(text) for pattern in NL_IN_EN_PATTERNS):
        errors.append("first-touch contains unnecessary language mixing")

    # Exact repeated content paragraphs are a strong signal of templating residue.
    parts = _paragraphs(text)
    content_parts = [p.casefold().strip(" .!?") for p in parts[1:-3] if len(p.split()) >= 4]
    if len(content_parts) != len(set(content_parts)):
        errors.append("first-touch repeats the same content")
    return errors


def initial_copy_errors(subject: str, body: str) -> list[str]:
    text = str(body or "").strip()
    errors = _subject_errors(subject)
    if not text:
        return errors + ["missing body"]

    words = _word_count(text)
    if words < 50 or words > 100:
        errors.append("first-touch body must stay within about 50-100 words")

    observation = _observation_from_body(text)
    non_observation = _body_without_observation(text)

    if re.search(r"https?://", text):
        errors.append("first-touch body may not contain external URLs by default")
    if any(pattern.search(text) for pattern in PRESSURE_PATTERNS):
        errors.append("first-touch body contains hype or unsupported pressure")
    if any(pattern.search(text) for pattern in GUARANTEE_CLAIM_PATTERNS):
        errors.append("first-touch body contains hype or unsupported pressure")
    if GUARANTEE_TERM.search(non_observation):
        errors.append("first-touch body contains hype or unsupported pressure")
    elif GUARANTEE_TERM.search(observation) and not _observation_allows_guarantee_term(observation):
        errors.append("first-touch body contains hype or unsupported pressure")
    if any(pattern.search(text) for pattern in UNSUPPORTED_SEVERITY_LOSS_PATTERNS):
        errors.append("first-touch body contains unsupported severity or loss claim")
    if any(pattern.search(text) for pattern in MEETING_PATTERNS):
        errors.append("first-touch body may not use a default meeting ask")
    if any(pattern.search(text) for pattern in HARD_PRICE_PATTERNS):
        errors.append("first-touch body may not contain price or discount language")
    if SOFT_PRICE_TERM.search(non_observation):
        errors.append("first-touch body may not contain price or discount language")
    elif SOFT_PRICE_TERM.search(observation) and not _observation_allows_soft_price_term(observation):
        errors.append("first-touch body may not contain price or discount language")
    if any(pattern.search(text) for pattern in SOLUTION_SPOILER_PATTERNS):
        errors.append("first-touch body reveals implementation or the full solution")

    language = _language_from_body(text)
    if not language:
        errors.append("first-touch body must use the canonical NL or EN disclosure shape")
        return errors

    if not observation or any(pattern.fullmatch(observation.strip()) for pattern in GENERIC_OBSERVATION_PATTERNS):
        errors.append("first-touch observation is too vague to be evidence-bound")

    errors.extend(_human_language_errors(text, language=language, observation=observation))

    ctas = CTA_NL if language == "nl" else CTA_EN
    cta_count = sum(text.count(cta) for cta in ctas)
    if cta_count != 1:
        errors.append("first-touch must contain exactly one permission CTA")

    opt_out = OPT_OUT_NL if language == "nl" else OPT_OUT_EN
    commercial = COMMERCIAL_NL if language == "nl" else COMMERCIAL_EN
    signature = SIGNATURE_NL if language == "nl" else SIGNATURE_EN
    if text.count(opt_out) != 1:
        errors.append("first-touch must contain the canonical easy opt-out exactly once")
    if text.count(commercial) != 1:
        errors.append("first-touch must identify itself as a commercial message exactly once")
    if signature not in text:
        errors.append("first-touch must contain the approved Andrew Baeten signature")

    promise_patterns = (
        re.compile(r"(?i)\béén\s+(?:klein|kort|concreet|korte|kleine|concrete)\b.{0,55}\b(?:voorbeeld|schets|flow|postplan|uitwerking)\b"),
        re.compile(r"(?i)\bone\s+(?:small|short|concrete)\b.{0,55}\b(?:example|sketch|flow|outline|post plan)\b"),
    )
    if sum(bool(pattern.search(text)) for pattern in promise_patterns) != 1:
        errors.append("first-touch must promise exactly one small concrete example")

    return errors


def followup_copy_errors(body: str) -> list[str]:
    text = str(body or "").strip()
    if not text:
        return ["missing follow-up body"]
    errors: list[str] = []
    if re.search(r"https?://", text):
        errors.append("follow-up may not contain external URLs")
    if any(pattern.search(text) for pattern in SOLUTION_SPOILER_PATTERNS):
        errors.append("follow-up reveals implementation before permission")
    if any(pattern.search(text) for pattern in PRICE_PATTERNS):
        errors.append("follow-up may not contain price or discount language")
    if any(pattern.search(text) for pattern in UNSUPPORTED_SEVERITY_LOSS_PATTERNS):
        errors.append("follow-up contains unsupported severity or loss claim")
    if any(pattern.search(text) for pattern in REDUNDANT_EXAMPLE_PATTERNS):
        errors.append("follow-up contains redundant mini-flow wording")
    if any(pattern.search(text) for pattern in MEETING_PATTERNS):
        errors.append("follow-up may not use a default meeting ask")
    language = _language_from_body(text)
    if not language:
        language = "nl" if OPT_OUT_NL in text else "en" if OPT_OUT_EN in text else ""
    if language == "nl":
        if any(pattern.search(text) for pattern in EN_IN_NL_PATTERNS):
            errors.append("follow-up contains unnecessary language mixing")
        if sum(text.count(cta) for cta in CTA_NL) != 1:
            errors.append("follow-up must contain exactly one permission CTA")
        if text.count(OPT_OUT_NL) != 1:
            errors.append("follow-up must contain the canonical easy opt-out exactly once")
        if SIGNATURE_NL not in text:
            errors.append("follow-up must contain the approved Andrew Baeten signature")
    elif language == "en":
        if any(pattern.search(text) for pattern in NL_IN_EN_PATTERNS):
            errors.append("follow-up contains unnecessary language mixing")
        if sum(text.count(cta) for cta in CTA_EN) != 1:
            errors.append("follow-up must contain exactly one permission CTA")
        if text.count(OPT_OUT_EN) != 1:
            errors.append("follow-up must contain the canonical easy opt-out exactly once")
        if SIGNATURE_EN not in text:
            errors.append("follow-up must contain the approved Andrew Baeten signature")
    else:
        errors.append("follow-up must use the canonical NL or EN opt-out shape")
    return errors


def _clean_fragment(value: str, *, field: str) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        raise ValueError(f"{field} is required")
    if any(pattern.search(text) for pattern in SOLUTION_SPOILER_PATTERNS):
        raise ValueError(f"{field} contains solution-spoiler language")
    if field == "observation":
        if any(pattern.search(text) for pattern in SCRAPE_RESIDUE_PATTERNS):
            raise ValueError(f"{field} contains scrape or navigation residue")
        if any(pattern.search(text) for pattern in INTERNAL_LABEL_PATTERNS):
            raise ValueError(f"{field} contains an internal or machine-like label")
        if any(pattern.search(text) for pattern in HARD_PRICE_PATTERNS):
            raise ValueError(f"{field} contains price language")
        if SOFT_PRICE_TERM.search(text) and not _observation_allows_soft_price_term(text):
            raise ValueError(f"{field} contains price language")
        if any(pattern.search(text) for pattern in PRESSURE_PATTERNS):
            raise ValueError(f"{field} contains hype or pressure language")
        if any(pattern.search(text) for pattern in GUARANTEE_CLAIM_PATTERNS):
            raise ValueError(f"{field} contains guarantee claim")
        if GUARANTEE_TERM.search(text) and not _observation_allows_guarantee_term(text):
            raise ValueError(f"{field} contains guarantee claim")
    else:
        if any(pattern.search(text) for pattern in PRICE_PATTERNS):
            raise ValueError(f"{field} contains price language")
        if any(pattern.search(text) for pattern in HYPE_PATTERNS):
            raise ValueError(f"{field} contains hype or pressure language")
    if any(pattern.search(text) for pattern in UNSUPPORTED_SEVERITY_LOSS_PATTERNS):
        raise ValueError(f"{field} contains unsupported severity or loss claim")
    return text.rstrip(".!?")


def _example_phrase(example_label: str, *, language: str) -> str:
    normalized = example_label.casefold().strip()
    nl = {
        "mini-flow": "één korte flow",
        "flow": "één korte flow",
        "voorbeeld": "één concreet voorbeeld",
        "example": "één concreet voorbeeld",
        "schets": "één korte schets",
        "sketch": "één korte schets",
        "postplan": "één klein postplan",
        "post plan": "één klein postplan",
        "uitwerking": "één korte uitwerking",
        "outline": "één korte uitwerking",
    }
    en = {
        "mini-flow": "one short flow",
        "flow": "one short flow",
        "voorbeeld": "one concrete example",
        "example": "one concrete example",
        "schets": "one short sketch",
        "sketch": "one short sketch",
        "postplan": "one small post plan",
        "post plan": "one small post plan",
        "uitwerking": "one short outline",
        "outline": "one short outline",
    }
    mapping = nl if language == "nl" else en
    if normalized in mapping:
        return mapping[normalized]
    # Unknown labels are permitted only when they already read like ordinary words.
    if re.search(r"[_/]", example_label) or any(pattern.search(example_label) for pattern in INTERNAL_LABEL_PATTERNS):
        raise ValueError("example_label contains an internal or machine-like label")
    return (f"één concreet {example_label}" if language == "nl" else f"one concrete {example_label}")


def build_curiosity_first_copy(
    *,
    company: str,
    language: str,
    subject: str,
    observation: str,
    friction: str,
    example_label: str,
    website: str = "andrewbaeten.nl",
    postal_address: str = "",
) -> CopyDraft:
    # Keep company as an input/evidence field for caller compatibility, but use a
    # stable sentence shape so a dynamic company name cannot break grammar.
    _clean_fragment(company, field="company")
    observation = _clean_fragment(observation, field="observation")
    friction = _clean_fragment(friction, field="friction")
    example_label = _clean_fragment(example_label, field="example_label")
    lang = str(language or "").strip().lower()
    if lang not in {"nl", "en"}:
        raise ValueError("language must be nl or en")
    if _subject_errors(subject):
        raise ValueError("subject violates curiosity-first contract: " + "; ".join(_subject_errors(subject)))
    if any(pattern.fullmatch(observation) for pattern in GENERIC_OBSERVATION_PATTERNS):
        raise ValueError("observation is too vague to be evidence-bound")

    example_phrase = _example_phrase(example_label, language=lang)

    if lang == "nl":
        cta = CTA_NL[0]
        body = (
            "Beste team,\n\n"
            f"{observation}.\n\n"
            f"{friction}.\n\n"
            f"Ik heb {example_phrase} uitgewerkt die dit punt concreet maakt.\n\n"
            f"{cta}\n\n"
            f"{OPT_OUT_NL}\n\n"
            f"{COMMERCIAL_NL}\n\n"
            f"{SIGNATURE_NL}\n{website}"
        )
        followup = (
            "Beste team,\n\n"
            "Ik kom hier nog één keer op terug. Het voorbeeld ligt klaar.\n\n"
            f"{cta}\n\n"
            f"{OPT_OUT_NL}\n\n"
            f"{SIGNATURE_NL}"
        )
    else:
        cta = CTA_EN[0]
        signature = SIGNATURE_EN
        if postal_address:
            signature += f"\n{POSTAL_PLACEHOLDER}"
        body = (
            "Hi team,\n\n"
            f"{observation}.\n\n"
            f"{friction}.\n\n"
            f"I made {example_phrase} to make that point concrete.\n\n"
            f"{cta}\n\n"
            f"{OPT_OUT_EN}\n\n"
            f"{COMMERCIAL_EN}\n\n"
            f"{signature}\n{website}"
        )
        followup = (
            "Hi team,\n\n"
            "Just following up once. The example is ready.\n\n"
            f"{cta}\n\n"
            f"{OPT_OUT_EN}\n\n"
            f"{SIGNATURE_EN}"
        )

    errors = initial_copy_errors(subject, body) + followup_copy_errors(followup)
    if errors:
        raise ValueError("generated copy violates V17.2.3: " + "; ".join(errors))
    return CopyDraft(subject, body, "", followup, 4)
