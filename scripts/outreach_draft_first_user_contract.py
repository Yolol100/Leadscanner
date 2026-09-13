from __future__ import annotations

import re

from prospect_target_policy import canonical_country

SUBJECT_NL = {
    "front_desk_sales": "Afspraken bij {company}",
    "quote_intake": "Offerteaanvragen bij {company}",
    "customer_support": "Klantvragen bij {company}",
    "commerce": "Productvragen bij {company}",
    "review_concierge": "Reviews bij {company}",
}
SUBJECT_EN = {
    "front_desk_sales": "Appointments at {company}",
    "quote_intake": "Quote requests at {company}",
    "customer_support": "Customer questions at {company}",
    "commerce": "Product questions at {company}",
    "review_concierge": "Reviews at {company}",
}

BANNED_ROLE_STYLE = (
    "Beste team van ",
    "Andrew Baeten",
    "andrewbaeten.nl",
    "Dit is een commercieel bericht.",
    "This is a commercial message.",
)


def _text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _sentence(value: object) -> str:
    return _text(value).rstrip(" .;:")


def build_copy(
    *,
    company: str,
    country: str,
    fact: str,
    value: str,
    agent_type: str,
    postal_address: str = "",
) -> tuple[str, str, str, str, int]:
    """Build review-only copy for the explicit 2026-09-13 draft contract.

    This route intentionally does not include a postal/footer URL or a live-send
    disclosure. Live-send compliance is a separate workflow. No first name is
    injected here because the draft-first ContactCandidates contract does not
    carry a provenance-backed person name.
    """
    del postal_address
    company = _text(company)[:100]
    fact = _sentence(fact)
    value = _sentence(value)
    agent_type = _text(agent_type).casefold()
    if not company or not fact or not value or agent_type not in SUBJECT_NL:
        raise ValueError("company, evidence-bound fact/value and approved draft-first agent_type are required")

    language = "nl" if canonical_country(country) in {"NL", "BE"} else "en"
    if language == "nl":
        subject = SUBJECT_NL[agent_type].format(company=company)
        body = (
            "Hallo,\n\n"
            f"Ik zag op jullie site dat {fact}.\n\n"
            f"Daar zit mogelijk een eenvoudige automatiseringsslag: {value}. "
            "Zo kan het repetitieve deel worden opgevangen, terwijl jullie team de belangrijke beslissingen houdt.\n\n"
            f"Zal ik een kort voorbeeld sturen van hoe dat er voor {company} uit kan zien?\n\n"
            "Geen interesse? Een kort \"nee\" is genoeg.\n\n"
            "Met vriendelijke groet,\n"
            "Andrew"
        )
    else:
        subject = SUBJECT_EN[agent_type].format(company=company)
        body = (
            "Hello,\n\n"
            f"I noticed on your site that {fact}.\n\n"
            f"There may be a simple workflow opportunity here: {value}. "
            "It could handle the repetitive part while your team keeps the important decisions.\n\n"
            f"Would it be useful if I sent over a short example for {company}?\n\n"
            "Not interested? A quick \"no\" is enough.\n\n"
            "Best regards,\n"
            "Andrew"
        )

    errors = initial_copy_errors(subject, body)
    if errors:
        raise ValueError("generated copy violates explicit draft-first contract: " + "; ".join(errors[:5]))
    return subject, body, "", "", 0


def initial_copy_errors(subject: str, body: str) -> list[str]:
    subject = _text(subject)
    text = str(body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    errors: list[str] = []
    if not subject:
        errors.append("missing subject")
    if re.match(r"(?i)^(?:re|fw|fwd)\s*:", subject):
        errors.append("fake reply/forward subject is not allowed")
    if not text:
        return errors + ["missing body"]
    if re.search(r"https?://", text):
        errors.append("draft-first initial may not contain external URLs")
    for banned in BANNED_ROLE_STYLE:
        if banned in text:
            errors.append(f"forbidden draft style token: {banned}")
    if re.search(r"(?im)^Hi .+ team,$", text):
        errors.append("company-team greeting is not allowed")
    if re.search(r"(?i)\b(?:guaranteed|gegarandeerd|last chance|laatste kans|limited time|alleen vandaag)\b", text):
        errors.append("unsupported result or urgency language is not allowed")

    if text.startswith("Hallo,") or re.match(r"^Hallo [^,\n]{1,80},", text):
        if not re.match(r"^Hallo(?: [^,\n]{1,80})?,\n\n", text):
            errors.append("invalid Dutch greeting shape")
        cta = re.findall(r"(?m)^Zal ik een kort voorbeeld sturen van hoe dat er voor .+ uit kan zien\?$", text)
        if len(cta) != 1:
            errors.append("Dutch draft must contain exactly one low-friction CTA")
        if text.count('Geen interesse? Een kort "nee" is genoeg.') != 1:
            errors.append("Dutch draft must contain the easy no exactly once")
        if not text.endswith("Met vriendelijke groet,\nAndrew"):
            errors.append("Dutch draft must end with the approved Andrew-only signature")
    elif text.startswith("Hello,") or re.match(r"^Hello [^,\n]{1,80},", text):
        if not re.match(r"^Hello(?: [^,\n]{1,80})?,\n\n", text):
            errors.append("invalid English greeting shape")
        cta = re.findall(r"(?m)^Would it be useful if I sent over a short example for .+\?$", text)
        if len(cta) != 1:
            errors.append("English draft must contain exactly one low-friction CTA")
        if text.count('Not interested? A quick "no" is enough.') != 1:
            errors.append("English draft must contain the easy no exactly once")
        if not text.endswith("Best regards,\nAndrew"):
            errors.append("English draft must end with the approved Andrew-only signature")
    else:
        errors.append("draft must start with Hallo/Hello, optionally followed by a proven first name")

    words = len(text.split())
    if words < 40 or words > 130:
        errors.append("initial length must stay within the 40-130 word transport guardrail")
    return errors
