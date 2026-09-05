from __future__ import annotations

from dataclasses import replace
import re
from typing import Iterable

from prospect_discovery import SourceSpec, host_key, split_terms

DEFAULT_EXCLUDED_COUNTRIES = ("NL", "NLD", "NETHERLANDS", "NEDERLAND")
DEFAULT_PREFERRED_COUNTRIES = (
    "US", "GB", "DE", "FR", "BE", "ES", "IT", "SE", "DK", "NO", "FI",
    "AT", "CH", "IE", "PT", "PL", "CZ",
)
DEFAULT_SELF_EXCLUDED_DOMAINS = ("webactueel.nl",)

COUNTRY_ALIASES = {
    "NL": {"NL", "NLD", "NETHERLANDS", "NEDERLAND"},
    "US": {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"},
    "GB": {"GB", "UK", "GBR", "UNITED KINGDOM", "GREAT BRITAIN"},
    "DE": {"DE", "DEU", "GERMANY", "DEUTSCHLAND"},
    "FR": {"FR", "FRA", "FRANCE"},
    "BE": {"BE", "BEL", "BELGIUM", "BELGIE", "BELGIË"},
    "ES": {"ES", "ESP", "SPAIN", "ESPANA", "ESPAÑA"},
    "IT": {"IT", "ITA", "ITALY", "ITALIA"},
    "SE": {"SE", "SWE", "SWEDEN", "SVERIGE"},
    "DK": {"DK", "DNK", "DENMARK", "DANMARK"},
    "NO": {"NO", "NOR", "NORWAY", "NORGE"},
    "FI": {"FI", "FIN", "FINLAND"},
    "AT": {"AT", "AUT", "AUSTRIA", "OSTERREICH", "ÖSTERREICH"},
    "CH": {"CH", "CHE", "SWITZERLAND", "SCHWEIZ", "SUISSE"},
    "IE": {"IE", "IRL", "IRELAND"},
    "PT": {"PT", "PRT", "PORTUGAL"},
    "PL": {"PL", "POL", "POLAND", "POLSKA"},
    "CZ": {"CZ", "CZE", "CZECHIA", "CZECH REPUBLIC"},
}

# Strong self-description phrases for providers that substantially overlap with
# Webactueel's own website/webshop/app/marketing delivery. They are deliberately
# more specific than generic words like "marketing" or "software" so normal
# retailers and product companies are not rejected because one broad term is
# present in a footer, job title or product description.
DEFAULT_AGENCY_EXCLUDE_TERMS = (
    # English
    "web design agency", "website design agency", "web development agency",
    "website development agency", "app development agency", "mobile app development agency",
    "software development agency", "software agency", "product development agency",
    "ux agency", "ui ux agency", "ux design agency", "digital agency",
    "digital marketing agency", "marketing agency", "advertising agency", "ad agency",
    "seo agency", "branding agency", "creative agency", "ecommerce agency",
    "e-commerce agency", "wordpress agency", "woocommerce agency", "shopify agency",
    "full-service agency", "full service agency",
    # Dutch
    "webdesign bureau", "webdesignbureau", "website bureau", "webbureau",
    "internetbureau", "app bureau", "appbureau", "app ontwikkelbureau",
    "software bureau", "softwarebureau", "ux bureau", "ui ux bureau",
    "marketingbureau", "marketing bureau", "reclamebureau", "reclame bureau",
    "advertentiebureau", "online marketing bureau", "seo bureau", "seo-bureau",
    "branding bureau", "creatief bureau", "communicatiebureau", "wordpress bureau",
    "woocommerce bureau", "webshop bureau",
    # German
    "webdesign agentur", "webagentur", "app agentur", "software agentur",
    "marketingagentur", "werbeagentur", "seo agentur", "seo-agentur",
    "digitalagentur", "wordpress agentur",
    # French
    "agence web", "agence digitale", "agence application mobile", "agence mobile",
    "agence développement logiciel", "agence marketing", "agence de marketing",
    "agence seo", "agence de publicité", "agence publicitaire",
    "agence de communication", "agence wordpress",
    # Spanish
    "agencia web", "agencia digital", "agencia de aplicaciones", "agencia de software",
    "agencia de marketing", "agencia seo", "agencia de publicidad",
    "agencia de comunicación", "agencia wordpress",
    # Italian
    "agenzia web", "agenzia digitale", "agenzia app", "agenzia software",
    "agenzia marketing", "agenzia seo", "agenzia pubblicitaria",
    "agenzia di comunicazione", "agenzia wordpress",
    # Portuguese
    "agência web", "agencia web", "agência digital", "agencia digital",
    "agência de aplicativos", "agencia de aplicativos", "agência de software",
    "agencia de software", "agência de marketing", "agencia de marketing",
    "agência seo", "agencia seo", "agência de publicidade", "agencia de publicidade",
    # Nordic common self-descriptions
    "webbyrå", "digitalbyrå", "appbyrå", "mjukvarubyrå", "marknadsföringsbyrå",
    "reklambyrå", "digitalt bureau", "webbureau", "app bureau", "software bureau",
    "reklamebureau",
)


def _normalized(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().upper()


def canonical_country(value: object) -> str:
    raw = _normalized(value)
    if not raw:
        return ""
    tokens = set(re.findall(r"[A-ZÀ-ÖØ-Þ]{2,}", raw))
    for canonical, aliases in COUNTRY_ALIASES.items():
        for alias in aliases:
            alias_norm = _normalized(alias)
            phrase_match = len(alias_norm) > 3 and alias_norm in raw
            if raw == alias_norm or alias_norm in tokens or phrase_match:
                return canonical
    return raw


def parse_country_list(raw: object, default: Iterable[str]) -> tuple[str, ...]:
    text = str(raw or "").strip()
    values = re.split(r"[,;\n]", text) if text else list(default)
    output: list[str] = []
    for value in values:
        country = canonical_country(value)
        if country and country not in output:
            output.append(country)
    return tuple(output)


def is_excluded_country(country: object, excluded: Iterable[str]) -> bool:
    canonical = canonical_country(country)
    return bool(canonical and canonical in {canonical_country(item) for item in excluded})


def is_excluded_domain(url_or_host: object, excluded_domains: Iterable[str] = DEFAULT_SELF_EXCLUDED_DOMAINS) -> bool:
    raw = str(url_or_host or "").strip()
    host = host_key(raw) if "://" in raw or "/" in raw else raw.casefold().strip(".")
    host = host[4:] if host.startswith("www.") else host
    for item in excluded_domains:
        blocked = str(item or "").casefold().strip().strip(".")
        if blocked and (host == blocked or host.endswith("." + blocked)):
            return True
    return False


def apply_source_policy(
    source: SourceSpec,
    *,
    excluded_countries: Iterable[str] = DEFAULT_EXCLUDED_COUNTRIES,
    excluded_domains: Iterable[str] = DEFAULT_SELF_EXCLUDED_DOMAINS,
    exclude_agencies: bool = True,
    extra_exclude_terms: object = "",
) -> tuple[SourceSpec | None, str]:
    if is_excluded_country(source.country, excluded_countries):
        return None, "country_excluded"
    if is_excluded_domain(source.source_url, excluded_domains):
        return None, "self_domain_excluded"
    if not exclude_agencies:
        return source, ""
    merged: list[str] = []
    for term in (*source.exclude_terms, *DEFAULT_AGENCY_EXCLUDE_TERMS, *split_terms(extra_exclude_terms)):
        normalized = re.sub(r"\s+", " ", str(term)).strip().casefold()
        if normalized and normalized not in merged:
            merged.append(normalized)
    return replace(source, exclude_terms=tuple(merged[:250])), ""


def prioritize_sources(sources: Iterable[SourceSpec], preferred_countries: Iterable[str]) -> list[SourceSpec]:
    order = {canonical_country(country): index for index, country in enumerate(preferred_countries)}
    indexed = list(enumerate(sources))
    indexed.sort(key=lambda pair: (order.get(canonical_country(pair[1].country), len(order) + 1), pair[0]))
    return [source for _, source in indexed]
