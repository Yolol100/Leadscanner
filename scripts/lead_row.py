from __future__ import annotations

import re
from email.utils import parseaddr
from urllib.parse import urlparse

REQUIRED = (
    "lead_id",
    "company",
    "website",
    "offer",
    "observation",
    "observation_source_url",
    "email",
    "email_source_url",
    "subject",
    "body",
)
ALLOWED_OFFERS = {
    "website_webshop",
    "wordpress_elementor",
    "seo",
    "conversion_contact",
}
PLACEHOLDER_RE = re.compile(r"\{\{|\}\}|\[NAME\]|\[BEDRIJF\]", re.I)


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"\s+", text.strip()) if w]


def _host(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"invalid absolute http(s) URL: {url}")
    host = (parsed.hostname or "").casefold().strip(".")
    return host[4:] if host.startswith("www.") else host


def _same_site(source_url: str, website: str) -> bool:
    source_host = _host(source_url)
    site_host = _host(website)
    return (
        source_host == site_host
        or source_host.endswith("." + site_host)
        or site_host.endswith("." + source_host)
    )


def validate_row(row: dict[str, str]) -> dict[str, str]:
    clean = {k: str(v or "").strip() for k, v in row.items()}
    missing = [k for k in REQUIRED if not clean.get(k)]
    if missing:
        raise ValueError("Missing required fields: " + ", ".join(missing))

    _host(clean["website"])

    if clean["offer"] not in ALLOWED_OFFERS:
        raise ValueError("offer must be one of: " + ", ".join(sorted(ALLOWED_OFFERS)))

    if len(clean["observation"]) < 12:
        raise ValueError("observation is too short to be useful evidence")

    for field in ("observation_source_url", "email_source_url"):
        if not _same_site(clean[field], clean["website"]):
            raise ValueError(f"{field} must belong to the official website/webshop")

    email = parseaddr(clean["email"])[1]
    if not email or "@" not in email or email != clean["email"]:
        raise ValueError("email must be one plain email address")

    subject_words = _words(clean["subject"])
    if not 2 <= len(subject_words) <= 8:
        raise ValueError("subject must contain 2-8 words")

    body_words = _words(clean["body"])
    if not 35 <= len(body_words) <= 180:
        raise ValueError("body must contain 35-180 words")

    if PLACEHOLDER_RE.search(
        "\n".join(
            [
                clean["company"],
                clean["observation"],
                clean["subject"],
                clean["body"],
            ]
        )
    ):
        raise ValueError("lead or mail still contains a placeholder")

    lowered = clean["body"].casefold()
    if "andrew baeten" not in lowered:
        raise ValueError("body must identify Andrew Baeten")
    if "andrewbaeten.nl" not in lowered:
        raise ValueError("body must include andrewbaeten.nl")
    if not any(marker in lowered for marker in ["geen interesse", "no interest", "not interested"]):
        raise ValueError("body must include a simple opt-out line")

    return clean
