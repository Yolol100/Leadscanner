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
    "contact_basis_status",
    "contact_basis_type",
    "contact_basis_evidence_ref",
    "outreach_status",
    "draft_queue_eligible",
)
ALLOWED_OFFERS = {
    "ai_agents",
    "social_media",
    "search_visibility",
    "website_webshop",
}
ALLOWED_CONTACT_BASIS_TYPES = {
    "prior_valid_consent",
    "purpose_specific_published_contact",
    "existing_customer_similar_services_exception",
}
PRICE_PATTERNS = [
    re.compile(r"(?:€|\\$|£)\\s*\\d", re.I),
    re.compile(r"\\b(?:eur|euro|usd|dollar|gbp|pond|pound)\\s*\\d", re.I),
    re.compile(r"\\b\\d+(?:[,.]\\d+)?\\s*(?:eur|euro|usd|dollar|gbp|pond|pound)\\b", re.I),
    re.compile(r"\\b\\d+(?:[,.]\\d+)?\\s*(?:€|\\$|£)", re.I),
    re.compile(r"\\b\\d+(?:[,.]\\d+)?\\s*%", re.I),
    re.compile(r"\\bkorting\\b", re.I),
    re.compile(r"\\bvan\\s+(?:(?:€|\\$|£)\\s*)?\\d+(?:[,.]\\d+)?\\s+(?:voor|naar)\\s+(?:(?:€|\\$|£)\\s*)?\\d", re.I),
]
MEETING_PATTERNS = [
    re.compile(r"\\bcalendly\\b", re.I),
    re.compile(r"\\b(?:meeting|afspraak|call|gesprek|kennismaking)\\s+(?:inplannen|plannen|boeken)\\b", re.I),
    re.compile(r"\\b(?:zullen|kunnen)\\s+we\\s+(?:bellen|sparren|afspreken)\\b", re.I),
    re.compile(r"\\b(?:kan|kun|wil|wilt|zou)\\s+(?:je|u)\\b.{0,40}\\b(?:bellen|sparren|afspreken)\\b", re.I),
    re.compile(r"\\b(?:heb|heeft)\\s+(?:je|u)\\b.{0,30}\\b(?:tijd|ruimte)\\b.{0,30}\\b(?:bellen|gesprek|call|afspraak)\\b", re.I),
    re.compile(r"\\b\\d{1,2}\\s*(?:min|minuten)\\b.{0,30}\\b(?:bellen|call|gesprek|sparren)\\b", re.I),
    re.compile(r"\\bboek\\s+(?:een\\s+)?(?:call|afspraak)\\b", re.I),
]
PLACEHOLDER_RE = re.compile(
    r"\\{\\{|\\}\\}|\\$\\{[^{}]+\\}|\\{(?:name|naam|company|bedrijf|first_name|voornaam)\\}"
    r"|\\[(?:name|naam|company|bedrijf|first_name|voornaam)\\]"
    r"|<(?:name|naam|company|bedrijf|first_name|voornaam)>",
    re.I,
)


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

    for field in ("lead_id", "subject"):
        if "\r" in clean[field] or "\n" in clean[field]:
            raise ValueError(f"{field} must not contain CR or LF")

    _host(clean["website"])

    if clean["offer"] not in ALLOWED_OFFERS:
        raise ValueError("offer must be one of: " + ", ".join(sorted(ALLOWED_OFFERS)))

    if clean["contact_basis_status"].casefold() != "pass":
        raise ValueError("contact_basis_status must be pass before DraftQueue runtime")

    if clean["contact_basis_type"] not in ALLOWED_CONTACT_BASIS_TYPES:
        raise ValueError(
            "contact_basis_type must be one of: "
            + ", ".join(sorted(ALLOWED_CONTACT_BASIS_TYPES))
        )

    evidence_ref = clean["contact_basis_evidence_ref"]
    if clean["contact_basis_type"] == "purpose_specific_published_contact":
        if not _same_site(evidence_ref, clean["website"]):
            raise ValueError(
                "purpose-specific contact basis evidence must belong to the official website/webshop"
            )
    else:
        prefix = "first_party:"
        if not evidence_ref.casefold().startswith(prefix) or not evidence_ref[len(prefix):].strip():
            raise ValueError(
                "consent/customer contact basis requires a substantive first_party: evidence reference"
            )

    if clean["outreach_status"].casefold() != "ready_for_draftqueue":
        raise ValueError("outreach_status must be ready_for_draftqueue")

    if clean["draft_queue_eligible"].casefold() != "true":
        raise ValueError("draft_queue_eligible must be true")

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

    mail_text = clean["subject"] + "\n" + clean["body"]
    if any(rx.search(mail_text) for rx in PRICE_PATTERNS):
        raise ValueError("first touch must not contain price or discount")
    if any(rx.search(clean["body"]) for rx in MEETING_PATTERNS):
        raise ValueError("first touch must not contain a default meeting ask")

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
