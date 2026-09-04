from __future__ import annotations

import re

OPT_OUT_PHRASES = (
    "unsubscribe",
    "remove me",
    "stop emailing",
    "do not email",
    "don't email",
    "no more emails",
    "afmelden",
    "uitschrijven",
    "verwijder mij",
    "geen mails meer",
)
SHORT_OPT_OUT_REPLIES = {"nee", "nee bedankt", "geen interesse"}


def _short_reply(value: str) -> str:
    value = re.sub(r"\s+", " ", value.lower()).strip()
    return value.strip(" .,!?:;\"'")


def message_has_optout(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", (text or "").lower())
    if any(phrase in normalized for phrase in OPT_OUT_PHRASES):
        return True
    for line in (text or "").splitlines():
        candidate = _short_reply(line)
        if candidate in SHORT_OPT_OUT_REPLIES:
            return True
    return False
