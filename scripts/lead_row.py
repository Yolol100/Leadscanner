from __future__ import annotations

import re
from email.utils import parseaddr
from urllib.parse import urlparse

REQUIRED = ("lead_id", "company", "website", "email", "subject", "body")
PLACEHOLDER_RE = re.compile(r"\{\{|\}\}|\[NAME\]|\[BEDRIJF\]", re.I)


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"\s+", text.strip()) if w]


def validate_row(row: dict[str, str]) -> dict[str, str]:
    clean = {k: str(v or "").strip() for k, v in row.items()}
    missing = [k for k in REQUIRED if not clean.get(k)]
    if missing:
        raise ValueError("Missing required fields: " + ", ".join(missing))

    parsed = urlparse(clean["website"])
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("website must be an absolute http(s) URL")

    email = parseaddr(clean["email"])[1]
    if not email or "@" not in email or email != clean["email"]:
        raise ValueError("email must be one plain email address")

    subject_words = _words(clean["subject"])
    if not 2 <= len(subject_words) <= 8:
        raise ValueError("subject must contain 2-8 words")

    body_words = _words(clean["body"])
    if not 35 <= len(body_words) <= 180:
        raise ValueError("body must contain 35-180 words")

    if PLACEHOLDER_RE.search(clean["subject"] + "\n" + clean["body"]):
        raise ValueError("mail still contains a placeholder")

    lowered = clean["body"].casefold()
    if "andrew baeten" not in lowered:
        raise ValueError("body must identify Andrew Baeten")
    if "andrewbaeten.nl" not in lowered:
        raise ValueError("body must include andrewbaeten.nl")
    if not any(marker in lowered for marker in ["geen interesse", "no interest", "not interested"]):
        raise ValueError("body must include a simple opt-out line")

    return clean
