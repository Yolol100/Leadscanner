from __future__ import annotations

import re
from urllib.parse import urlparse

from prospect_discovery import parse_page

MANUFACTURING_TERMS = (
    "manufacturer", "manufacturing", "manufacture", "fabrication", "fabricator",
    "factory", "production", "industrial", "machinery", "machine builder", "oem",
    "components", "metal roofing", "hersteller", "fertigung", "produktion", "maschinen",
    "fabrikant", "productie", "fabricage",
)
INSTITUTION_NAME_PATTERNS = (
    re.compile(r"^(?:home|homepage|welcome)$", re.I),
    re.compile(r"^\[\[.+\]\]$", re.I),
    re.compile(r"\bjob\s*board\b", re.I),
    re.compile(r"\bchamber\b", re.I),
    re.compile(r"^city\s+of\b", re.I),
    re.compile(r"\bofficial\s+website\b", re.I),
    re.compile(r"\btrustmark\b.*\b(?:review|reviews)\b", re.I),
    re.compile(r"\b(?:review|reviews)\b.*\btrustmark\b", re.I),
)


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").casefold().strip(".")


def _registrable_hint(host: str) -> str:
    parts = [part for part in host.split(".") if part]
    if len(parts) < 2:
        return host
    # Bounded directory sources are currently ordinary public hosts. This is a
    # conservative provider-self check, not a public-suffix implementation.
    return ".".join(parts[-2:])


def _manufacturing_source(source_id: str, source_url: str) -> bool:
    value = f"{source_id} {source_url}".casefold()
    return "manufactur" in value


def obvious_non_target(company: str, website: str, source_url: str = "") -> str:
    company = _text(company)
    host = _host(website)
    source_host = _host(source_url)
    if host.endswith(".gov") or host.endswith(".gov.uk"):
        return "government domain"
    if source_host and host and _registrable_hint(source_host) == _registrable_hint(host):
        return "directory provider infrastructure/domain"
    for pattern in INSTITUTION_NAME_PATTERNS:
        if pattern.search(company):
            return f"institution/navigation identity: {company[:80]}"
    return ""


def source_semantic_target_check(
    *,
    source_id: str,
    source_url: str,
    company: str,
    website: str,
    html: str,
) -> tuple[bool, str]:
    blocked = obvious_non_target(company, website, source_url)
    if blocked:
        return False, blocked
    if not _manufacturing_source(source_id, source_url):
        return True, ""
    page = parse_page(html, website)
    evidence = f"{company} {page.title} {page.site_name} {page.text[:120000]}".casefold()
    if any(term in evidence for term in MANUFACTURING_TERMS):
        return True, ""
    return False, "manufacturing-directory candidate lacks manufacturing/industrial self-description on official site"
