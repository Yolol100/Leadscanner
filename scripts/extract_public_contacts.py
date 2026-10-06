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

from url_safety import is_public_http_url

MAX_WORKERS = 12
MAX_CANDIDATES_PER_RUN = 100
MAX_PAGES_PER_SITE = 3
MAX_BYTES_PER_PAGE = 1_000_000
DEFAULT_TIMEOUT = 12
MAX_REDIRECTS = 5

EMAIL_RE = re.compile(r"(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63})(?![A-Z0-9._%+-])", re.I)
CONTACT_HINT_RE = re.compile(
    r"(contact|contacten|contact-us|contact_us|over-ons|over_ons|about|business|sales|partnership|partners|offerte|aanvraag)",
    re.I,
)
HTML_LANG_RE = re.compile(r"<html[^>]*\blang\s*=\s*['\"]?([a-zA-Z-]{2,12})", re.I)
BLOCKED_LOCAL_PARTS = {"noreply", "no-reply", "donotreply", "do-not-reply", "example", "test"}
PLACEHOLDER_LOCAL_PARTS = {"naam", "name", "yourname", "your.name", "email", "e-mail", "mail", "voorbeeld"}
PLACEHOLDER_DOMAINS = {"voorbeeld.nl", "voorbeeld.com", "example.com", "example.org", "example.net", "jouwdomein.nl", "yourdomain.com", "mysite.com"}
BLOCKED_TECHNICAL_EMAIL_DOMAIN_SUFFIXES = ("sentry.wixpress.com", "sentry-next.wixpress.com", "sentry.io")
BLOCKED_ASSET_EMAIL_TLDS = {"png", "jpg", "jpeg", "gif", "webp", "svg", "avif", "ico", "css", "js"}
UNSUITABLE_OUTREACH_LOCAL_PARTS = {
    "press", "pressemea", "pers", "media", "hr", "work", "job", "jobs", "career", "careers",
    "vacature", "vacatures", "recruit", "recruitment", "sollicitatie", "solliciteren", "privacy", "legal", "dpo",
    "security", "abuse", "webmaster", "investorrelations",
}
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


def _clean_observation_candidate(raw: str) -> str | None:
    text = re.sub(r"(?s)<[^>]+>", " ", raw or "")
    text = re.sub(r"\s+", " ", unescape(text)).strip(" \t\r\n-|")
    lowered = text.casefold()
    if not text:
        return None
    if any(
        term in lowered
        for term in (
            "cookie",
            "privacy policy",
            "privacybeleid",
            "algemene voorwaarden",
            "terms and conditions",
        )
    ):
        return None
    if re.search(
        r"\b(function\s*\(|window\.|document\.|listeners\b|"
        r"newsletter|nieuwsbrief|schrijf je in|subscribe|"
        r"klik hier|meer lezen na deze video|"
        r"vacatures?|solliciteer|werken bij|teamleider|"
        r"bouwvak|tijdelijk gesloten|closed from|"
        r"product toegevoegd|offertepagina|winkelmand|checkout)\b",
        lowered,
    ):
        return None
    if "©" in text or "all rights reserved" in lowered:
        return None
    if re.search(
        r"\b(ik|persoonlijk|mijn)\b",
        lowered,
    ) and re.search(
        r"\b(goed|beste|vriendelijk|geholpen|eten|restaurant|"
        r"behandeling|dikke 10|terug kom)\b",
        lowered,
    ):
        return None
    if re.search(
        r"\b(dank|klantgericht|te klein)\b",
        lowered,
    ) and re.search(
        r"\b(prima|mensen|temp|locatie)\b",
        lowered,
    ):
        return None
    if re.match(
        r"^(informatie over .*(adres|openingstijden)|"
        r"meer lezen na|voor vragen of reserveringen)\b",
        lowered,
    ):
        return None
    words = text.split()
    if not 4 <= len(words) <= 36:
        return None
    if not 18 <= len(text) <= 240:
        return None
    return text


def extract_verified_observation(html: str) -> str | None:
    candidates: list[tuple[int, str]] = []

    for tag in re.findall(r"(?is)<meta\b[^>]*>", html or ""):
        kind = re.search(
            r"""(?is)(?:name|property)\s*=\s*["']([^"']+)["']""",
            tag,
        )
        content = re.search(
            r"""(?is)content\s*=\s*["']([^"']+)["']""",
            tag,
        )
        if not kind or not content:
            continue
        label = kind.group(1).strip().casefold()
        if label not in {"description", "og:description"}:
            continue
        cleaned = _clean_observation_candidate(content.group(1))
        if cleaned:
            candidates.append((40, cleaned))

    for raw in re.findall(
        r"(?is)<p\b[^>]*>(.*?)</p>",
        html or "",
    )[:40]:
        cleaned = _clean_observation_candidate(raw)
        if cleaned:
            candidates.append((30, cleaned))

    for priority, pattern in (
        (20, r"(?is)<h1\b[^>]*>(.*?)</h1>"),
        (10, r"(?is)<title\b[^>]*>(.*?)</title>"),
    ):
        for match in re.finditer(pattern, html or ""):
            cleaned = _clean_observation_candidate(
                match.group(1)
            )
            if cleaned:
                candidates.append(
                    (priority, cleaned)
                )

    if not candidates:
        return None

    def score(item: tuple[int, str]) -> tuple[int, int, int]:
        priority, text = item
        word_count = len(text.split())
        specificity = 0
        lowered = text.casefold()
        if 7 <= word_count <= 28:
            specificity += 8
        if 40 <= len(text) <= 200:
            specificity += 6
        if any(
            marker in lowered
            for marker in (
                " biedt ",
                " verkoopt ",
                " gespecialiseerd ",
                " restaurant ",
                " winkel ",
                " service ",
                " diensten ",
                " sinds ",
                " gevestigd ",
                " locatie ",
                " assortiment ",
                " catering ",
                " webshop ",
                " offers ",
                " serves ",
                " specializes ",
                " located ",
            )
        ):
            specificity += 8
        if lowered.startswith(
            (
                "welkom bij ",
                "welkom op ",
                "welcome to ",
                "home ",
            )
        ):
            specificity -= 10
        return (
            priority + specificity,
            min(len(text), 200),
            word_count,
        )

    return max(candidates, key=score)[1]


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
    normalized_page = _normalize_text(page_text)
    tokenized_page = " " + re.sub(r"[^a-z0-9]+", " ", normalized_page) + " "
    for phrase in HARD_COMPETITOR_PHRASES:
        normalized_phrase = re.sub(r"[^a-z0-9]+", " ", _normalize_text(phrase)).strip()
        if normalized_phrase and f" {normalized_phrase} " in tokenized_page:
            return f"official_site:{phrase}"

    soft_hits = [term for term in SOFT_COMPETITOR_TERMS if _normalize_text(term) in normalized_page]
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
    normalized_local = re.sub(r"[^a-z0-9]+", "", local)
    if normalized_local in UNSUITABLE_OUTREACH_LOCAL_PARTS:
        return False
    if domain in PLACEHOLDER_DOMAINS or domain.endswith((".example", ".test", ".invalid", ".localhost")):
        return False
    if domain.rsplit(".", 1)[-1] in BLOCKED_ASSET_EMAIL_TLDS:
        return False
    if any(
        domain == suffix or domain.endswith("." + suffix)
        for suffix in BLOCKED_TECHNICAL_EMAIL_DOMAIN_SUFFIXES
    ):
        return False
    return True


def email_fits_business_context(
    email: str,
    official_domain: str | None,
    source_type: str,
    company_name: str | None = None,
) -> bool:
    if not valid_email(email):
        return False
    email_domain = email.rsplit("@", 1)[1].casefold().rstrip(".")
    official = str(official_domain or "").casefold().rstrip(".")
    _ = source_type
    if official and (email_domain == official or email_domain.endswith("." + official)):
        return True
    if email_domain in PUBLIC_MAIL_DOMAINS:
        return True
    if company_name and email_business_priority(email, official_domain, company_name) == 0:
        return True
    return False


def email_business_priority(email: str, official_domain: str | None, company_name: str | None) -> int:
    email_domain = email.rsplit("@", 1)[1].casefold().rstrip(".")
    official = str(official_domain or "").casefold().rstrip(".")
    if official and (email_domain == official or email_domain.endswith("." + official)):
        return 0

    normalized_email_domain = re.sub(r"[^a-z0-9]+", "", email_domain)
    normalized_official_domain = re.sub(r"[^a-z0-9]+", "", official)
    company_tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", _normalize_text(company_name))
        if len(token) >= 4
    ]
    if any(
        token in normalized_email_domain and token in normalized_official_domain
        for token in company_tokens
    ):
        return 0
    if email_domain in PUBLIC_MAIL_DOMAINS:
        return 1
    return 2


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


def _decode_cloudflare_email(token: str) -> str | None:
    value = str(token or "").strip()
    if (
        len(value) < 4
        or len(value) % 2
        or not re.fullmatch(r"[0-9a-fA-F]+", value)
    ):
        return None
    try:
        data = bytes.fromhex(value)
    except ValueError:
        return None
    if len(data) < 2:
        return None
    key = data[0]
    try:
        decoded = bytes(
            byte ^ key
            for byte in data[1:]
        ).decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return None
    return decoded.strip() or None


def extract_emails(html: str) -> list[str]:
    cleaned = unescape(html or "")
    found: list[str] = []

    cloudflare_tokens = re.findall(
        r"""(?is)data-cfemail\s*=\s*["']([0-9a-f]+)["']""",
        cleaned,
    )
    cloudflare_tokens.extend(
        re.findall(
            r"""(?is)/cdn-cgi/l/email-protection#([0-9a-f]+)""",
            cleaned,
        )
    )
    for token in cloudflare_tokens:
        candidate = _decode_cloudflare_email(
            token
        )
        if (
            candidate
            and valid_email(candidate)
            and candidate.casefold() not in found
        ):
            found.append(
                candidate.casefold()
            )

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
    if not is_public_http_url(url):
        return None, None, None

    current_url = url
    original_domain = normalize_domain(url)
    last_status: int | None = None
    for _ in range(MAX_REDIRECTS + 1):
        if not is_public_http_url(current_url):
            return None, current_url or None, last_status
        try:
            response = session.get(
                current_url,
                timeout=timeout,
                allow_redirects=False,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/154.0.0.0 Safari/537.36"
                    ),
                    "Accept": (
                        "text/html,application/xhtml+xml,"
                        "application/xml;q=0.9,*/*;q=0.8"
                    ),
                    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
                },
                stream=True,
            )
        except requests.RequestException:
            return None, current_url or None, last_status

        try:
            status = int(response.status_code)
            last_status = status
            response_url = str(response.url or current_url).strip()
            if not is_public_http_url(response_url):
                return None, response_url or current_url, status

            if status in {301, 302, 303, 307, 308}:
                location = str((response.headers or {}).get("location") or "").strip()
                if not location:
                    return None, response_url or current_url, status
                next_url = urljoin(response_url or current_url, location)
                if not is_public_http_url(next_url):
                    return None, next_url, status
                if original_domain and normalize_domain(next_url) != original_domain:
                    return None, next_url, status
                current_url = next_url
                continue

            content_type = str((response.headers or {}).get("content-type") or "").lower()
            if not (200 <= status < 400) or "text/html" not in content_type:
                return None, response_url or current_url, status
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
            return body, response_url or current_url, status
        finally:
            response.close()

    return None, current_url or None, last_status


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
        "verified_observation": None,
        "verified_observation_source_url": None,
        "verified_observation_source_type": None,
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

    observation = extract_verified_observation(html)
    if observation:
        result["verified_observation"] = observation
        result["verified_observation_source_url"] = final_url
        result["verified_observation_source_type"] = "official_site"

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
            if not email_fits_business_context(
                email,
                domain,
                "official_site",
                str(candidate.get("name_hint") or ""),
            ):
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

    if emails:
        ranked = sorted(
            zip(emails, sources, source_types, source_refs),
            key=lambda item: email_business_priority(
                item[0],
                domain,
                str(candidate.get("name_hint") or ""),
            ),
        )
        emails = [item[0] for item in ranked]
        sources = [item[1] for item in ranked]
        source_types = [item[2] for item in ranked]
        source_refs = [item[3] for item in ranked]

    if not emails:
        for item in candidate.get("discovery_email_candidates") or []:
            if not isinstance(item, dict):
                continue
            email = str(item.get("email") or "").strip().lower().strip(".,;:()[]<>")
            source = str(item.get("source") or "discovery").strip() or "discovery"
            if not email_fits_business_context(
                email,
                domain,
                source,
                str(candidate.get("name_hint") or ""),
            ) or email in emails:
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
