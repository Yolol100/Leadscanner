from __future__ import annotations

import re

ADVISORY_ONLY_NOTE = "advisory_only: requires Leads/operator review; never canonical sales outcome or send permission"

OOO_TERMS = (
    "out of office", "automatic reply", "auto reply", "away from the office",
    "on vacation", "on holiday", "afwezig", "automatisch antwoord", "vakantie",
)
POSITIVE_TERMS = (
    "interested", "sounds good", "tell me more", "send more info", "more information",
    "schedule a call", "book a call", "let's talk", "lets talk", "afspraak", "meer informatie",
    "meer info", "interesse", "klinkt goed",
)
NOT_INTERESTED_TERMS = (
    "not interested", "no interest", "not a priority", "geen interesse", "niet geinteresseerd",
    "niet geïnteresseerd", "geen prioriteit",
)
REFERRAL_TERMS = (
    "contact my colleague", "contact our", "reach out to", "speak with", "talk to",
    "neem contact op met", "stuur dit naar", "mijn collega",
)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").casefold()).strip()


def classify_reply_intent(text: str, subject: str = "") -> str:
    combined = _normalize(f"{subject} {text}")
    if not combined:
        return "neutral"
    if any(term in combined for term in OOO_TERMS):
        return "out_of_office"
    if any(term in combined for term in REFERRAL_TERMS):
        return "referral"
    if any(term in combined for term in NOT_INTERESTED_TERMS):
        return "not_interested"
    if any(term in combined for term in POSITIVE_TERMS):
        return "positive_interest"
    if "?" in combined or any(term in combined for term in ("price", "pricing", "kosten", "tarief", "how does", "hoe werkt")):
        return "question"
    return "neutral"


def advisory_reply_triage(text: str, subject: str = "") -> dict[str, str]:
    return {
        "intent": classify_reply_intent(text, subject),
        "note": ADVISORY_ONLY_NOTE,
    }
