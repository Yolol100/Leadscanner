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
    re.compile(r"^home$", re.I),
    re.compile(r"^\[\[.+\]\]$", re.I),
    re.compile(r"\bjob\s*board\b", re.I),
    re.compile(r"\bchamber\b", re.I),
    re.compile(r"^city\s+of\b", re.I),
    re.compile(r"\bofficial\s+website\b", re.I),
)


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _manufacturing_source(source_id: str, source_url: str) -> bool:
    value = f"{source_id} {source_url}".casefold()
    return "manufactur" in value


def obvious_non_target(company: str, website: str) -> str:
    company = _text(company)
    host = (urlparse(website).hostname or "").casefold().strip(".")
    if host.endswith(".gov") or host.endswith(".gov.uk"):
        return "government domain"
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
    blocked = obvious_non_target(company, website)
    if blocked:
        return False, blocked
    if not _manufacturing_source(source_id, source_url):
        return True, ""
    page = parse_page(html, website)
    evidence = f"{company} {page.title} {page.site_name} {page.text[:120000]}".casefold()
    if any(term in evidence for term in MANUFACTURING_TERMS):
        return True, ""
    return False, "manufacturing-directory candidate lacks manufacturing/industrial self-description on official site"
