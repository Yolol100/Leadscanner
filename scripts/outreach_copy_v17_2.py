from __future__ import annotations

import re
from dataclasses import dataclass

CONTRACT_ID = "curiosity_first_v17_2"
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
PRICE_PATTERNS = (
    re.compile(r"(?i)(?:€|\$|£)\s*\d"),
    re.compile(r"(?i)\b(?:prijs|prijzen|kosten|fee|tarief|korting|price|pricing|cost|costs|discount)\b"),
)
HYPE_PATTERNS = (
    re.compile(r"(?i)\b(?:gegarandeerd|garantie|guaranteed|guarantees|last chance|laatste kans|only today|alleen vandaag)\b"),
)
MEETING_PATTERNS = (
    re.compile(r"(?i)\b(?:plan|boek|reserveer|schedule|book)\b.{0,60}\b(?:call|meeting|gesprek|agenda|minuten|minutes)\b"),
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
    # First paragraph is salutation in the canonical shape.
    return parts[1]


def initial_copy_errors(subject: str, body: str) -> list[str]:
    text = str(body or "").strip()
    errors = _subject_errors(subject)
    if not text:
        return errors + ["missing body"]

    words = _word_count(text)
    if words < 50 or words > 100:
        errors.append("first-touch body must stay within about 50-100 words")

    if re.search(r"https?://", text):
        errors.append("first-touch body may not contain external URLs by default")
    if any(pattern.search(text) for pattern in HYPE_PATTERNS):
        errors.append("first-touch body contains hype or unsupported pressure")
    if any(pattern.search(text) for pattern in MEETING_PATTERNS):
        errors.append("first-touch body may not use a default meeting ask")
    if any(pattern.search(text) for pattern in PRICE_PATTERNS):
        errors.append("first-touch body may not contain price or discount language")
    if any(pattern.search(text) for pattern in SOLUTION_SPOILER_PATTERNS):
        errors.append("first-touch body reveals implementation or the full solution")

    language = _language_from_body(text)
    if not language:
        errors.append("first-touch body must use the canonical NL or EN disclosure shape")
        return errors

    observation = _observation_from_body(text)
    if not observation or any(pattern.fullmatch(observation.strip()) for pattern in GENERIC_OBSERVATION_PATTERNS):
        errors.append("first-touch observation is too vague to be evidence-bound")

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
        re.compile(r"(?i)\béén klein\b.{0,55}\b(?:voorbeeld|schets|mini-flow|postplan|uitwerking)\b"),
        re.compile(r"(?i)\bone small\b.{0,55}\b(?:example|sketch|mini-flow|outline)\b"),
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
    if any(pattern.search(text) for pattern in MEETING_PATTERNS):
        errors.append("follow-up may not use a default meeting ask")
    language = _language_from_body(text)
    if not language:
        # Follow-up does not repeat the commercial disclosure, so infer from opt-out.
        language = "nl" if OPT_OUT_NL in text else "en" if OPT_OUT_EN in text else ""
    if language == "nl":
        if sum(text.count(cta) for cta in CTA_NL) != 1:
            errors.append("follow-up must contain exactly one permission CTA")
        if text.count(OPT_OUT_NL) != 1:
            errors.append("follow-up must contain the canonical easy opt-out exactly once")
        if SIGNATURE_NL not in text:
            errors.append("follow-up must contain the approved Andrew Baeten signature")
    elif language == "en":
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
    if any(pattern.search(text) for pattern in PRICE_PATTERNS):
        raise ValueError(f"{field} contains price language")
    return text.rstrip(".!?")


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
    company = _clean_fragment(company, field="company")
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

    if lang == "nl":
        cta = CTA_NL[0]
        body = (
            "Beste team,\n\n"
            f"{observation}.\n\n"
            f"{friction}.\n\n"
            f"Ik heb voor {company} één klein {example_label} gemaakt dat de mogelijke verbetering concreet maakt.\n\n"
            f"{cta}\n\n"
            f"{OPT_OUT_NL}\n\n"
            f"{COMMERCIAL_NL}\n\n"
            f"{SIGNATURE_NL}\n{website}"
        )
        followup = (
            "Beste team,\n\n"
            f"Ik kom hier nog één keer op terug. Het kleine {example_label} voor {company} ligt klaar.\n\n"
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
            f"I made one small {example_label} for {company} that makes the opportunity concrete.\n\n"
            f"{cta}\n\n"
            f"{OPT_OUT_EN}\n\n"
            f"{COMMERCIAL_EN}\n\n"
            f"{signature}\n{website}"
        )
        followup = (
            "Hi team,\n\n"
            f"Just following up once. The small {example_label} for {company} is ready.\n\n"
            f"{cta}\n\n"
            f"{OPT_OUT_EN}\n\n"
            f"{SIGNATURE_EN}"
        )

    errors = initial_copy_errors(subject, body) + followup_copy_errors(followup)
    if errors:
        raise ValueError("generated copy violates V17.2: " + "; ".join(errors))
    return CopyDraft(subject, body, "", followup, 4)
