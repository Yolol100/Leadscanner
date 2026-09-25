from __future__ import annotations

import argparse
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests

MAX_WORKERS = 12
MAX_CANDIDATES_PER_RUN = 100
MAX_PAGES_PER_SITE = 3
MAX_BYTES_PER_PAGE = 1_000_000
DEFAULT_TIMEOUT = 12

EMAIL_RE = re.compile(r"(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63})(?![A-Z0-9._%+-])", re.I)
CONTACT_HINT_RE = re.compile(
    r"(contact|contacten|contact-us|contact_us|over-ons|over_ons|about|business|sales|partnership|partners|offerte|aanvraag)",
    re.I,
)
HTML_LANG_RE = re.compile(r"<html[^>]*\blang\s*=\s*['\"]?([a-zA-Z-]{2,12})", re.I)
BLOCKED_LOCAL_PARTS = {"noreply", "no-reply", "donotreply", "do-not-reply", "example", "test"}
PLACEHOLDER_LOCAL_PARTS = {"naam", "name", "yourname", "your.name", "email", "e-mail", "mail", "voorbeeld"}
PLACEHOLDER_DOMAINS = {"voorbeeld.nl", "voorbeeld.com", "example.com", "example.org", "example.net", "jouwdomein.nl", "yourdomain.com"}
PUBLIC_MAIL_DOMAINS = {"gmail.com", "hotmail.com", "outlook.com", "live.nl", "live.com", "icloud.com", "yahoo.com", "proton.me", "protonmail.com"}

HARD_COMPETITOR_PHRASES = (
    "marketingbureau",
    "marketing agency",
    "online marketing bureau",
    "online marketing agency",
    "reclamebureau",
    "communicatiebureau",
    "digital agency",
    "digitaal bureau",
    "webbureau",
    "web agency",
    "webdesign bureau",
    "webdesign agency",
    "webdesigner",
    "web designer",
    "website bouwer",
    "websitebouwer",
    "webshop bouwer",
    "webshopbouwer",
    "web development agency",
    "webdevelopment bureau",
    "seo bureau",
    "seo agency",
    "seo specialist",
    "seo consultant",
    "online marketeer",
    "digital marketer",
    "social media bureau",
    "social media agency",
    "social media manager",
    "social media specialist",
    "content marketing agency",
    "contentmarketingbureau",
    "content creator bureau",
    "content agency",
    "ai agency",
    "ai bureau",
    "automation agency",
    "automation consultant",
    "ai consultant",
    "automatiseringsbureau",
    "no-code agency",
    "nocode agency",
    "wordpress bureau",
    "wordpress agency",
    "wordpress specialist",
    "woocommerce specialist",
    "elementor specialist",
    "elementor agency",
    "hosting provider",
    "hostingprovider",
    "hosting company",
    "hosting bedrijf",
    "hosting reseller",
    "hostingreseller",
    "internetbureau",
    "internet agency",
    "creative agency",
    "branding agency",
    "webhosting bedrijf",
    "webhosting provider",
)

SOFT_COMPETITOR_TERMS = (
    "webdesign",
    "web development",
    "webdevelopment",
    "website bouwen",
    "webshop bouwen",
    "zoekmachine optimalisatie",
    "seo specialist",
    "online marketing",
    "social media marketing",
    "social media beheer",
    "content marketing",
    "wordpress ontwikkeling",
    "woocommerce ontwikkeling",
    "elementor",
    "ai automatisering",
    "bedrijfsautomatisering",
    "workflow automation",
    "webhosting",
)

NL_MARKERS = (
    " de ", " het ", " een ", " voor ", " van ", " met ", " onze ", " wij ",
    " contact ", " diensten ", " over ons ", " bedrijf ", " klanten ",
)
EN_MARKERS = (
    " the ", " and ", " for ", " with ", " our ", " we ", " contact ",
    " services ", " about us ", " company ", " customers ",
)


def _normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().casefold()


def _visible_text(html: str) -> str:
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", html or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return f" {_normalize_text(unescape(text))} "


def normalize_domain(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = text if "://" in text else f"https://{text}"
    try:
        parsed = urlparse(candidate)
    except Exception:
        return None
    host = (parsed.hostname or "").strip().casefold().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def default_language_for_domain(domain: str | None) -> str:
    return "nl" if str(domain or "").casefold().endswith(".nl") else "en"


def detect_language(html: str, *, default: str = "nl") -> tuple[str, str]:
    text = _visible_text(html)
    nl_score = sum(text.count(marker) for marker in NL_MARKERS)
    en_score = sum(text.count(marker) for marker in EN_MARKERS)

    # Visible copy wins when the document language attribute is clearly stale or wrong.
    if nl_score >= en_score + 3:
        return "nl", "page_text"
    if en_score >= nl_score + 3:
        return "en", "page_text"

    match = HTML_LANG_RE.search(html or "")
    if match:
        lang = match.group(1).casefold()
        if lang.startswith("nl"):
            return "nl", "html_lang"
        if lang.startswith("en"):
            return "en", "html_lang"
    return default, "market_fallback"


def competitor_reason(candidate: dict, html: str | None = None) -> str | None:
    hint_text = _normalize_text(
        f"{candidate.get('name_hint') or ''} {candidate.get('category_hint') or ''}"
    )
    for phrase in HARD_COMPETITOR_PHRASES:
        if _normalize_text(phrase) in hint_text:
            return f"discovery_hint:{phrase}"

    if not html:
        return None

    page_text = _visible_text(html)[:180000]
    for phrase in HARD_COMPETITOR_PHRASES:
        if f" {_normalize_text(phrase)} " in page_text:
            return f"official_site:{phrase}"

    soft_hits = [term for term in SOFT_COMPETITOR_TERMS if _normalize_text(term) in page_text]
    if len(set(soft_hits)) >= 2:
        return "official_site:multiple_overlapping_services"
    return None


def valid_email(value: str) -> bool:
    email = str(value or "").strip().lower().strip(".,;:()[]<>")
    if not EMAIL_RE.fullmatch(email):
        return False
    local, domain = email.rsplit("@", 1)
    if local in BLOCKED_LOCAL_PARTS or local in PLACEHOLDER_LOCAL_PARTS:
        return False
    if local.startswith("no-reply") or local.startswith("noreply"):
        return False
    if domain in PLACEHOLDER_DOMAINS or domain.endswith((".example", ".test", ".invalid", ".localhost")):
        return False
    return True


def email_fits_business_context(email: str, official_domain: str | None, source_type: str) -> bool:
    if not valid_email(email):
        return False
    email_domain = email.rsplit("@", 1)[1].casefold().rstrip(".")
    official = str(official_domain or "").casefold().rstrip(".")
    if source_type == "official_site":
        return True
    if official and (email_domain == official or email_domain.endswith("." + official)):
        return True
    return email_domain in PUBLIC_MAIL_DOMAINS


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._active_href: str | None = None
        self._active_text: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag.casefold() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._active_href = str(href)
            self._active_text = []

    def handle_data(self, data: str):
        if self._active_href is not None:
            self._active_text.append(data)

    def handle_endtag(self, tag: str):
        if tag.casefold() == "a" and self._active_href is not None:
            self.links.append((self._active_href, " ".join(self._active_text).strip()))
            self._active_href = None
            self._active_text = []


def extract_emails(html: str) -> list[str]:
    cleaned = unescape(html or "")
    found: list[str] = []

    # Attribute values such as form placeholders are not contact evidence.
    parser = LinkParser()
    try:
        parser.feed(cleaned)
    except Exception:
        pass
    for href, _ in parser.links:
        if not href.casefold().startswith("mailto:"):
            continue
        candidate = unquote(href.split(":", 1)[1].split("?", 1)[0]).strip()
        if valid_email(candidate) and candidate not in found:
            found.append(candidate.lower())

    for match in EMAIL_RE.findall(_visible_text(cleaned)):
        email = match.lower().strip(".,;:()[]<>")
        if valid_email(email) and email not in found:
            found.append(email)
    return found


def discover_contact_links(html: str, base_url: str, official_domain: str) -> list[str]:
    parser = LinkParser()
    try:
        parser.feed(html)
    except Exception:
        return []

    links: list[str] = []
    for href, text in parser.links:
        if href.lower().startswith("mailto:"):
            continue
        if not CONTACT_HINT_RE.search(f"{href} {text}"):
            continue
        absolute = urljoin(base_url, href)
        if normalize_domain(absolute) != official_domain:
            continue
        parsed = urlparse(absolute)
        clean = parsed._replace(fragment="").geturl()
        if clean not in links:
            links.append(clean)
        if len(links) >= MAX_PAGES_PER_SITE - 1:
            break
    return links


def fetch_html(session, url: str, *, timeout: int = DEFAULT_TIMEOUT) -> tuple[str | None, str | None, int | None]:
    try:
        response = session.get(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": "WebactueelLeadContactDiscovery/1.0 (+https://andrewbaeten.nl)"},
            stream=True,
        )
    except requests.RequestException:
        return None, None, None

    try:
        status = int(response.status_code)
        final_url = str(response.url or "").strip()
        content_type = str(response.headers.get("content-type") or "").lower()
        if not (200 <= status < 400) or "text/html" not in content_type:
            return None, final_url or None, status
        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536, decode_unicode=False):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_BYTES_PER_PAGE:
                break
            chunks.append(chunk)
        body = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
        return body, final_url or url, status
    finally:
        response.close()


def purpose_hint(url: str, html: str) -> str:
    text = f"{url} {_visible_text(html)[:120000]}".casefold()
    strong = (
        "sales enquiries",
        "sales inquiry",
        "business enquiries",
        "business inquiry",
        "partnership",
        "partnerships",
        "zakelijke aanvragen",
        "zakelijke aanvraag",
        "offerte aanvragen",
        "offerteaanvraag",
    )
    return "possible_purpose_specific" if any(item in text for item in strong) else "generic_contact_only"


def inspect_candidate(candidate: dict, *, session_factory=requests.Session) -> dict:
    website = str(candidate.get("website_hint") or "").strip()
    domain = normalize_domain(website)
    language_default = default_language_for_domain(domain)
    result = {
        **candidate,
        "official_domain_hint": domain,
        "public_business_emails": [],
        "email_source_urls": [],
        "email_source_types": [],
        "email_source_refs": [],
        "language": language_default,
        "language_source": "market_fallback",
        "excluded_competitor": False,
        "exclusion_reason": None,
        "contact_basis_status": "unverified",
        "contact_basis_hint": "not_evaluated",
        "contact_discovery_status": "no_website",
    }

    hint_reason = competitor_reason(candidate)
    if hint_reason:
        result["excluded_competitor"] = True
        result["exclusion_reason"] = hint_reason
        result["contact_discovery_status"] = "excluded_competitor"
        return result

    if not website or not domain:
        return result

    session = session_factory()
    pages: list[tuple[str, str]] = []
    html, final_url, status = fetch_html(session, website)
    if not html or not final_url or normalize_domain(final_url) != domain:
        result["contact_discovery_status"] = "unreachable_or_cross_domain"
        result["website_http_status"] = status
        return result

    language, language_source = detect_language(html, default=language_default)
    result["language"] = language
    result["language_source"] = language_source

    site_reason = competitor_reason(candidate, html)
    if site_reason:
        result["excluded_competitor"] = True
        result["exclusion_reason"] = site_reason
        result["contact_discovery_status"] = "excluded_competitor"
        return result

    pages.append((final_url, html))
    for link in discover_contact_links(html, final_url, domain):
        if len(pages) >= MAX_PAGES_PER_SITE:
            break
        if any(existing_url == link for existing_url, _ in pages):
            continue
        linked_html, linked_final, _ = fetch_html(session, link)
        if linked_html and linked_final and normalize_domain(linked_final) == domain:
            pages.append((linked_final, linked_html))

    emails: list[str] = []
    sources: list[str] = []
    source_types: list[str] = []
    source_refs: list[str] = []
    hints: list[str] = []
    for page_url, page_html in pages:
        page_emails = extract_emails(page_html)
        if page_emails:
            hints.append(purpose_hint(page_url, page_html))
        for email in page_emails:
            if not email_fits_business_context(email, domain, "official_site"):
                continue
            if email not in emails:
                emails.append(email)
                sources.append(page_url)
                source_types.append("official_site")
                source_refs.append(page_url)
            if len(emails) >= 3:
                break
        if len(emails) >= 3:
            break

    if not emails:
        for item in candidate.get("discovery_email_candidates") or []:
            if not isinstance(item, dict):
                continue
            email = str(item.get("email") or "").strip().lower().strip(".,;:()[]<>")
            source = str(item.get("source") or "discovery").strip() or "discovery"
            if not email_fits_business_context(email, domain, source) or email in emails:
                continue
            emails.append(email)
            source_types.append(source)
            source_refs.append(
                str(candidate.get("maps_link_hint") if source == "google_maps" else candidate.get("overture_id") or source)
            )
            if len(emails) >= 3:
                break

    result["public_business_emails"] = emails
    result["email_source_urls"] = sources
    result["email_source_types"] = source_types
    result["email_source_refs"] = source_refs
    if emails:
        result["contact_discovery_status"] = (
            "found_official_site" if source_types and source_types[0] == "official_site"
            else "found_discovery_fallback"
        )
        result["contact_basis_status"] = "review_required"
    else:
        result["contact_discovery_status"] = "no_public_email_found"
        result["contact_basis_status"] = "unverified"
    result["contact_basis_hint"] = (
        "possible_purpose_specific" if "possible_purpose_specific" in hints
        else ("public_email_review_required" if emails else "no_email")
    )
    return result


def discover_contacts(payload: dict, *, max_workers: int = MAX_WORKERS) -> dict:
    candidates = payload.get("candidates") or []
    if not isinstance(candidates, list):
        raise ValueError("candidates must be a list")
    if len(candidates) > MAX_CANDIDATES_PER_RUN:
        raise ValueError(
            f"public contact discovery is bounded to {MAX_CANDIDATES_PER_RUN} candidates per reviewed run"
        )
    if not 1 <= max_workers <= MAX_WORKERS:
        raise ValueError(f"max_workers must be 1-{MAX_WORKERS}")

    workers = min(max_workers, max(len(candidates), 1))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(inspect_candidate, candidates))

    found = sum(1 for item in results if item.get("public_business_emails"))
    excluded = sum(1 for item in results if item.get("excluded_competitor"))
    return {
        "schema_version": "webactueel-public-contact-discovery/2.1",
        "candidate_count": len(results),
        "contact_found_count": found,
        "excluded_competitor_count": excluded,
        "candidates": results,
        "safety": {
            "official_site_preferred": True,
            "discovery_email_fallback_allowed": True,
            "max_pages_per_site": MAX_PAGES_PER_SITE,
            "email_addresses_guessed": False,
            "placeholder_emails_rejected": True,
            "fallback_domain_context_checked": True,
            "contact_basis_auto_pass": False,
            "draftqueue_write": False,
            "email_send": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = discover_contacts(payload, max_workers=args.max_workers)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "PUBLIC_CONTACT_DISCOVERY=green "
        f"candidates={result['candidate_count']} contacts={result['contact_found_count']} "
        f"excluded_competitors={result['excluded_competitor_count']} "
        "contact_basis_auto_pass=false email_send=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
