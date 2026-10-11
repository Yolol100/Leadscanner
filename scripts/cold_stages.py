#!/usr/bin/env python3
"""Clean-slate cold lead stages after raw Overture discovery.

Contracts:
- filter: cheap, no network; keeps only website-bearing non-competitor candidates.
- verify: bounded first-party identity/domain/contact verification.
- research: bounded first-party evidence collection; no copy or inferred pain.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests

from dedupe_preflight import domains_match, normalize_domain, match_candidate, load_registry
from first_party_contacts import preferred_contact_links, select_site_contact
from instantly_site_crawl import PoliteSiteSession
from url_safety import is_public_http_url

MAX_DISCOVERY = 5000
MAX_VERIFY = 100
MAX_RESEARCH = 100
MAX_VERIFY_WORKERS = 10
MAX_RESEARCH_WORKERS = 6
MAX_BYTES = 750_000
MAX_REDIRECTS = 4
DEFAULT_TIMEOUT = 10
HOMEPAGE_CACHE_CHARS = 24_000
MAX_CONTACT_PAGES = 6
MAX_RESEARCH_LINKS = 12
MAX_RESEARCH_PAGES = 12
MAX_EVIDENCE_PER_CANDIDATE = 48

EMAIL_RE = re.compile(r"(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63})(?![A-Z0-9._%+-])", re.I)

CHEAP_COMPETITOR_PHRASES = (
    "marketingbureau", "marketing agency", "online marketing", "reclamebureau",
    "digital agency", "digitaal bureau", "webbureau", "web agency", "webdesign bureau",
    "webdesign agency", "websitebouwer", "webshopbouwer", "seo bureau", "seo agency",
    "social media bureau", "content agency", "ai agency", "ai bureau", "automation agency",
    "no-code agency", "nocode agency", "wordpress bureau", "woocommerce specialist",
    "elementor agency", "hosting provider", "hostingbedrijf", "internetbureau",
)
STRONG_SITE_COMPETITOR_PHRASES = (
    "marketingbureau", "marketing agency", "reclamebureau", "digital agency", "digitaal bureau",
    "webbureau", "web agency", "webdesign bureau", "webdesign agency", "seo bureau", "seo agency",
    "social media bureau", "content agency", "ai agency", "ai bureau", "automation agency",
    "no-code agency", "nocode agency", "wordpress bureau", "elementor agency",
    "hosting provider", "internetbureau", "wij bouwen websites", "we build websites",
    "zoekmachine optimalisatie voor klanten", "marketing voor bedrijven",
)
SOFT_SITE_COMPETITOR_TERMS = (
    "webdesign", "web development", "website bouwen", "seo", "online marketing",
    "social media marketing", "content marketing", "wordpress", "woocommerce",
    "automation", "automatisering", "webhosting",
)

CONTACT_HINTS = (
    "contact", "contact-us", "contact_us", "over-ons", "about", "offerte", "aanvraag",
    "business", "sales", "zakelijk",
)
RESEARCH_HINTS = (
    "home", "over-ons", "about", "about-us", "team", "medewerkers", "directie", "eigenaar", "founder", "wie-zijn", "faq", "help", "contact", "veelgestelde",
    "levering", "bezorg", "shipping", "delivery", "retour", "returns",
    "portfolio", "referenties", "cases", "klantenservice", "support",
    "categorie", "category", "zoeken", "search", "filter", "collectie", "collection",
    "diensten", "services", "producten", "products", "assortiment", "aanbod", "solutions",
    "oplossingen", "werkwijze", "how-we-work", "afspraak", "reserver", "booking", "offerte",
    "menu", "behandelingen", "treatments", "cases", "projecten",
)
RESEARCH_EXCLUDES = (
    "privacy", "cookie", "voorwaarden", "terms", "vacature", "jobs", "career", "login",
    "account", "cart", "checkout", "nieuws", "news", "blog",
)
LEGAL_TOKENS = {
    "bv", "b", "v", "nv", "vof", "vof", "stichting", "foundation", "company", "co",
    "groep", "group", "holding", "nederland", "netherlands", "the", "de", "het", "van",
}
GENERIC_COMPANY_TOKENS = {
    "garage", "restaurant", "praktijk", "kliniek", "clinic", "bakkerij", "bakery", "shop",
    "winkel", "bedrijf", "services", "service", "solutions", "bouw", "bouwbedrijf", "tuinen",
    "installatie", "installatietechniek", "schilders", "schilderwerken", "dakdekkers",
}
BLOCKED_LOCAL_PARTS = {
    "noreply", "no-reply", "donotreply", "do-not-reply", "example", "test", "privacy",
    "legal", "dpo", "security", "abuse", "press", "media", "jobs", "job", "career",
    "careers", "vacatures", "recruitment", "webmaster",
}
PLACEHOLDER_DOMAINS = {"example.com", "example.org", "example.net", "voorbeeld.nl", "yourdomain.com"}
PUBLIC_MAIL_DOMAINS = {"gmail.com", "hotmail.com", "outlook.com", "live.nl", "live.com", "icloud.com", "yahoo.com", "proton.me", "protonmail.com"}
PREFERRED_LOCAL_PARTS = ("info", "contact", "hello", "hallo", "office", "sales", "algemeen", "service")


def _text(value: object) -> str:
    return str(value or "").strip()


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", _text(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().casefold()


def normalize_company(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_text(value))


def _site_session(session_factory, domain: str):
    """Enforce robots and per-host budgets on real network sessions.

    Injected non-requests sessions are deterministic test doubles only.
    """
    session = session_factory()
    return PoliteSiteSession(session, domain) if isinstance(session, requests.Session) else session


def cheap_competitor_reason(candidate: dict) -> str | None:
    haystack = normalize_text(f"{candidate.get('name_hint') or ''} {candidate.get('category_hint') or ''}")
    for phrase in CHEAP_COMPETITOR_PHRASES:
        if normalize_text(phrase) in haystack:
            return f"discovery_hint:{phrase}"
    return None


def filter_discovery(payload: dict) -> dict:
    candidates = payload.get("candidates") or []
    if not isinstance(candidates, list):
        raise ValueError("candidates_must_be_list")
    if len(candidates) > MAX_DISCOVERY:
        raise ValueError("discovery_limit_exceeded")

    kept: list[dict] = []
    excluded: list[dict] = []
    seen_domains: set[str] = set()
    for index, raw in enumerate(candidates):
        if not isinstance(raw, dict):
            continue
        website = _text(raw.get("website_hint"))
        domain = normalize_domain(website)
        name = _text(raw.get("name_hint"))
        if not name or not website or not domain:
            excluded.append({"index": index, "reason": "missing_name_or_website", "candidate": raw})
            continue
        reason = cheap_competitor_reason(raw)
        if reason:
            excluded.append({"index": index, "reason": reason, "candidate": raw})
            continue
        if any(domains_match(domain, seen) for seen in seen_domains):
            excluded.append({"index": index, "reason": "duplicate_domain_in_discovery", "candidate": raw})
            continue
        seen_domains.add(domain)
        kept.append({
            "discovery_id": _text(raw.get("overture_id")) or f"overture-index-{index}",
            "name_hint": name,
            "category_hint": _text(raw.get("category_hint")) or None,
            "website_hint": website,
            "domain_hint": domain,
            "longitude": raw.get("longitude"),
            "latitude": raw.get("latitude"),
            "confidence": raw.get("confidence"),
            "discovery_source": "overture",
            "identity_status": "unverified",
        })

    return {
        "schema_version": "leadscanner-cold-discovery/1.0",
        "source_candidate_count": len(candidates),
        "candidate_count": len(kept),
        "excluded_count": len(excluded),
        "candidates": kept,
        "excluded": excluded,
        "handoff": {
            "next": "dedupe_preflight",
            "fields": ["discovery_id", "name_hint", "category_hint", "website_hint", "domain_hint"],
        },
    }


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.mailtos: list[str] = []
        self.mailto_contexts: list[dict] = []
        self.text_parts: list[str] = []
        self.title_parts: list[str] = []
        self._active_href: str | None = None
        self._active_text: list[str] = []
        self._ignore = 0
        self._in_title = False
        self.contact_form_present = False
        self.phone_link_present = False
        self._active_form: dict[str, bool] | None = None

    def handle_starttag(self, tag: str, attrs):
        tag = tag.casefold()
        fields = dict(attrs)
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignore += 1
        if tag == "title":
            self._in_title = True

        # Detect an actual published message form, not a text claim that a
        # form exists. Never follow the action or submit any form.
        if not self._ignore:
            if tag == "form":
                self._active_form = {"recipient": False, "message": False}
            elif self._active_form is not None and tag in {"input", "textarea"}:
                field_type = str(fields.get("type") or "").casefold()
                description = " ".join(str(fields.get(k) or "") for k in ("name", "id", "placeholder")).casefold()
                if field_type in {"email", "tel"} or re.search(r"e-?mail|telefoon|phone", description):
                    self._active_form["recipient"] = True
                if tag == "textarea" or re.search(r"bericht|message|vraag|question|inquiry|comment", description):
                    self._active_form["message"] = True
        if tag == "a":
            href = fields.get("href")
            if href:
                self._active_href = str(href)
                self._active_text = []
                if re.fullmatch(r"tel:\+?[0-9 ()-]{5,32}", str(href).strip(), flags=re.I):
                    self.phone_link_present = True

    def handle_endtag(self, tag: str):
        tag = tag.casefold()
        if tag == "form" and self._active_form is not None:
            self.contact_form_present |= all(self._active_form.values())
            self._active_form = None
        if tag in {"script", "style", "noscript", "svg"} and self._ignore:
            self._ignore -= 1
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._active_href is not None:
            text = " ".join(self._active_text).strip()
            href = self._active_href
            self.links.append((href, text))
            if href.casefold().startswith("mailto:"):
                email = unquote(href.split(":", 1)[1].split("?", 1)[0]).strip()
                self.mailtos.append(email)
                self.mailto_contexts.append({
                    "email": email,
                    "context": " ".join(self.text_parts[-7:]),
                })
            self._active_href = None
            self._active_text = []

    def handle_data(self, data: str):
        if self._ignore:
            return
        text = unescape(data).strip()
        if not text:
            return
        self.text_parts.append(text)
        if self._in_title:
            self.title_parts.append(text)
        if self._active_href is not None:
            self._active_text.append(text)


def parse_html(html: str) -> dict:
    parser = PageParser()
    try:
        parser.feed(html or "")
    except Exception:
        pass
    return {
        "text": "\n".join(parser.text_parts),
        "title": " ".join(parser.title_parts).strip(),
        "links": parser.links,
        "mailtos": parser.mailtos,
        "mailto_contexts": parser.mailto_contexts,
        "contact_form_present": parser.contact_form_present,
        "phone_link_present": parser.phone_link_present,
    }


def safe_fetch_html(session, url: str, expected_domain: str, *, timeout: int = DEFAULT_TIMEOUT) -> tuple[str | None, str | None, int | None]:
    if not is_public_http_url(url):
        return None, None, None
    current = url
    last_status = None
    for _ in range(MAX_REDIRECTS + 1):
        if not is_public_http_url(current) or normalize_domain(current) != expected_domain:
            return None, current, last_status
        try:
            response = session.get(
                current,
                timeout=timeout,
                allow_redirects=False,
                stream=True,
                headers={
                    "User-Agent": "Leadscanner/2.1 (+https://andrewbaeten.nl)",
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
                },
            )
        except requests.RequestException:
            return None, current, last_status
        try:
            status = int(response.status_code)
            last_status = status
            response_url = _text(response.url) or current
            if not is_public_http_url(response_url) or normalize_domain(response_url) != expected_domain:
                return None, response_url, status
            if status in {301, 302, 303, 307, 308}:
                location = _text((response.headers or {}).get("location"))
                if not location:
                    return None, response_url, status
                nxt = urljoin(response_url, location)
                if not is_public_http_url(nxt) or normalize_domain(nxt) != expected_domain:
                    return None, nxt, status
                current = nxt
                continue
            content_type = _text((response.headers or {}).get("content-type")).casefold()
            if not 200 <= status < 400 or "html" not in content_type:
                return None, response_url, status
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=65536, decode_unicode=False):
                if not chunk:
                    continue
                remaining = MAX_BYTES - total
                if remaining <= 0:
                    break
                chunks.append(chunk[:remaining])
                total += min(len(chunk), remaining)
                if total >= MAX_BYTES:
                    break
            return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace"), response_url, status
        finally:
            response.close()
    return None, current, last_status


def _brand_tokens(name: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", normalize_text(name))
    return [t for t in tokens if len(t) >= 4 and t not in LEGAL_TOKENS and t not in GENERIC_COMPANY_TOKENS]


def verify_identity(name: str, domain: str, title: str, visible_text: str) -> tuple[bool, list[str]]:
    company_compact = normalize_company(name)
    page_compact = normalize_company(f"{title} {visible_text[:30000]}")
    domain_compact = re.sub(r"[^a-z0-9]+", "", domain.split(".", 1)[0])
    reasons: list[str] = []
    if len(company_compact) >= 5 and company_compact in page_compact:
        reasons.append("full_company_name_on_site")
    tokens = _brand_tokens(name)
    domain_hits = [token for token in tokens if token in domain_compact]
    if domain_hits:
        reasons.append("brand_token_in_domain:" + ",".join(domain_hits[:2]))
    page_words = set(re.findall(r"[a-z0-9]+", normalize_text(f"{title} {visible_text[:30000]}")))
    page_hits = [token for token in tokens if token in page_words]
    required_hits = 1 if len(tokens) <= 1 else 2
    if len(page_hits) >= required_hits:
        reasons.append("brand_tokens_on_site:" + ",".join(page_hits[:2]))
    return bool(reasons), reasons


def site_competitor_reason(visible_text: str) -> str | None:
    haystack = normalize_text(visible_text[:50000])
    for phrase in STRONG_SITE_COMPETITOR_PHRASES:
        if normalize_text(phrase) in haystack:
            return f"official_site:{phrase}"
    hits = sorted({term for term in SOFT_SITE_COMPETITOR_TERMS if normalize_text(term) in haystack})
    if len(hits) >= 3:
        return "official_site:multiple_competing_services:" + ",".join(hits[:3])
    return None


def valid_email(email: str) -> bool:
    candidate = _text(email).casefold().strip(" <>\"'.,;:()[]")
    if not EMAIL_RE.fullmatch(candidate):
        return False
    local, domain = candidate.rsplit("@", 1)
    normalized_local = re.sub(r"[^a-z0-9-]+", "", local)
    if local in BLOCKED_LOCAL_PARTS or normalized_local in BLOCKED_LOCAL_PARTS:
        return False
    if domain in PLACEHOLDER_DOMAINS or domain.endswith((".example", ".test", ".invalid", ".localhost")):
        return False
    return True


def extract_emails(parsed: dict) -> list[str]:
    found: list[str] = []
    for raw in list(parsed.get("mailtos") or []) + EMAIL_RE.findall(_text(parsed.get("text"))):
        email = _text(raw).casefold().strip(" <>\"'.,;:()[]")
        if valid_email(email) and email not in found:
            found.append(email)
    return found


def email_fits_official_context(email: str, official_domain: str) -> bool:
    _, domain = email.rsplit("@", 1)
    same_domain = domain == official_domain or domain.endswith("." + official_domain)
    return same_domain or domain in PUBLIC_MAIL_DOMAINS


def email_priority(email: str, official_domain: str) -> tuple[int, int, str]:
    local, domain = email.rsplit("@", 1)
    same_domain = domain == official_domain or domain.endswith("." + official_domain)
    preferred = PREFERRED_LOCAL_PARTS.index(local) if local in PREFERRED_LOCAL_PARTS else len(PREFERRED_LOCAL_PARTS)
    return (0 if same_domain else 1, preferred, email)


def internal_links(parsed: dict, base_url: str, domain: str, hints: tuple[str, ...], *, exclude: tuple[str, ...] = (), limit: int) -> list[str]:
    ranked: list[tuple[int, str]] = []
    seen: set[str] = set()
    for href, anchor in parsed.get("links") or []:
        if not href or href.casefold().startswith(("mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        if normalize_domain(absolute) != domain:
            continue
        parsed_url = urlparse(absolute)
        clean = parsed_url._replace(fragment="", query="").geturl()
        haystack = normalize_text(f"{parsed_url.path} {anchor}")
        if any(item in haystack for item in exclude):
            continue
        matches = [hint for hint in hints if hint in haystack]
        if not matches or clean in seen:
            continue
        seen.add(clean)
        ranked.append((-len(matches), clean))
    ranked.sort()
    return [url for _, url in ranked[:limit]]


def broad_research_links(parsed: dict, base_url: str, domain: str, *, limit: int = MAX_RESEARCH_PAGES) -> list[str]:
    """Select diverse public site pages, without category-based exclusion.

    Prefer useful path labels, but allow any safe same-domain HTML link as
    fallback. Authentication, transaction, legal and news routes stay excluded.
    """
    ranked = []
    seen = {urlparse(base_url)._replace(fragment="", query="").geturl()}
    for href, label in parsed.get("links") or []:
        if not href or href.casefold().startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = urljoin(base_url, href)
        parsed_url = urlparse(url)
        if parsed_url.scheme not in {"https", "http"} or normalize_domain(url) != domain:
            continue
        path = parsed_url.path.casefold()
        if any(term in path for term in RESEARCH_EXCLUDES):
            continue
        if re.search(r"\.(?:pdf|zip|jpg|jpeg|png|webp|gif|svg|xml|json|css|js)$", path):
            continue
        clean = parsed_url._replace(fragment="", query="").geturl()
        if clean in seen:
            continue
        seen.add(clean)
        hint_text = normalize_text(path + " " + str(label))
        relevance = sum(term in hint_text for term in RESEARCH_HINTS)
        ranked.append((-relevance, len(parsed_url.path.split("/")), clean))
    ranked.sort()
    return [url for _, _, url in ranked[:limit]]


def verify_candidate(candidate: dict, *, session_factory=requests.Session) -> dict:
    """Verify the OFFICIAL WEBSITE only; contact research comes afterwards.

    A missing email never prevents bounded first-party website research.
    """
    result = dict(candidate)
    result.update({
        "official_domain": None,
        "official_url": None,
        "identity_status": "hold",
        "identity_evidence": [],
        "public_business_email": None,
        "email_source_url": None,
        "contact_person_name": None,
        "contact_role": None,
        "contact_status": "not_checked",
        "excluded_competitor": False,
        "exclusion_reason": None,
        "ready_for_research": False,
        "verification_pages": [],
        "research_links": [],
        "contact_links": [],
        "homepage_text_excerpt": None,
        "homepage_mailtos": [],
        "homepage_mailto_contexts": [],
        "homepage_contact_form_present": False,
        "homepage_phone_link_present": False,
    })
    reason = cheap_competitor_reason(candidate)
    if reason:
        result["excluded_competitor"] = True
        result["exclusion_reason"] = reason
        result["contact_status"] = "skipped_competitor"
        return result

    website = _text(candidate.get("website_hint"))
    domain = normalize_domain(website)
    if not website or not domain:
        result["contact_status"] = "hold_missing_domain"
        return result
    session = _site_session(session_factory, domain)
    html, final_url, status = safe_fetch_html(session, website, domain)
    result["website_http_status"] = status
    if not html or not final_url:
        result["contact_status"] = (
            "hold_robots_policy" if getattr(session, "policy_hold", False)
            else "hold_unreachable_official_site"
        )
        return result

    parsed = parse_html(html)
    visible = _text(parsed["text"])
    identity_ok, identity_evidence = verify_identity(
        _text(candidate.get("name_hint")), domain, parsed.get("title") or "", visible
    )
    result["official_domain"] = domain
    result["official_url"] = final_url
    result["identity_evidence"] = identity_evidence
    result["verification_pages"].append(final_url)
    result["homepage_text_excerpt"] = visible[:HOMEPAGE_CACHE_CHARS]
    result["homepage_mailtos"] = parsed["mailtos"]
    result["homepage_mailto_contexts"] = parsed["mailto_contexts"]
    result["homepage_contact_form_present"] = parsed["contact_form_present"]
    result["homepage_phone_link_present"] = parsed["phone_link_present"]
    result["contact_links"] = preferred_contact_links(parsed, final_url, domain, limit=MAX_CONTACT_PAGES)
    result["research_links"] = broad_research_links(parsed, final_url, domain)
    if not identity_ok:
        result["contact_status"] = "hold_identity_not_proven"
        return result
    result["identity_status"] = "verified"

    site_reason = site_competitor_reason(visible)
    if site_reason:
        result["excluded_competitor"] = True
        result["exclusion_reason"] = site_reason
        result["contact_status"] = "skipped_competitor"
        return result

    # Research coverage is based on verified site identity, NOT email format,
    # mailbox type, name, or provider. Email selection happens after research.
    result["contact_status"] = "pending_post_research"
    result["ready_for_research"] = True
    return result

def verify_candidates(payload: dict, *, limit: int, max_workers: int = MAX_VERIFY_WORKERS, session_factory=requests.Session) -> dict:
    candidates = payload.get("kept")
    if candidates is None:
        candidates = payload.get("candidates") or []
    if not isinstance(candidates, list):
        raise ValueError("verification_candidates_must_be_list")
    if not 1 <= limit <= MAX_VERIFY:
        raise ValueError("verify_limit_must_be_1_100")
    selected = candidates[:limit]
    if not selected:
        return {
            "schema_version": "leadscanner-cold-verification/1.0",
            "candidate_count": 0,
            "ready_for_research_count": 0,
            "candidates": [],
        }
    if not 1 <= max_workers <= MAX_VERIFY_WORKERS:
        raise ValueError("verify_workers_out_of_bounds")
    workers = min(max_workers, len(selected))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda item: verify_candidate(item, session_factory=session_factory), selected))
    return {
        "schema_version": "leadscanner-cold-verification/1.0",
        "candidate_count": len(results),
        "ready_for_research_count": sum(1 for item in results if item.get("ready_for_research")),
        "candidates": results,
        "handoff": {
            "next": "bounded_research",
            "required": ["identity_status=verified", "ready_for_research=true"],
            "contact_step": "post_research_owner_first_or_general_fallback",
        },
    }


def evidence_sentences(text: str, source_url: str, page_type: str) -> list[dict]:
    candidates: list[dict] = []
    seen: set[str] = set()
    chunks = []
    for line in str(text or "").splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            chunks.extend(re.split(r"(?<=[.!?])\s+", line))
    for raw in chunks:
        sentence = re.sub(r"\s+", " ", raw).strip(" -|•\t\r\n")
        low = normalize_text(sentence)
        words = sentence.split()
        if not 6 <= len(words) <= 40 or not 30 <= len(sentence) <= 280:
            continue
        if any(term in low for term in (
            "cookie", "privacy", "algemene voorwaarden", "terms and conditions", "copyright",
            "all rights reserved", "vacature", "solliciteer", "nieuwsbrief", "subscribe",
        )):
            continue
        if re.search(r"\b(maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", low) and re.search(r"\b\d{1,2}[:.]\d{2}\b", low):
            continue
        key = re.sub(r"[^a-z0-9]+", "", low)
        if not key or key in seen:
            continue
        seen.add(key)
        candidates.append({
            "text": sentence,
            "source_url": source_url,
            "source_type": "official_site",
            "page_type": page_type,
        })
        if len(candidates) >= MAX_EVIDENCE_PER_CANDIDATE:
            break
    return candidates


def page_type_for_url(url: str) -> str:
    path = urlparse(url).path.casefold()
    for label, terms in (
        ("services", ("dienst", "service", "oploss", "solution", "behandeling", "treatment")),
        ("products", ("product", "assortiment", "menu")),
        ("process", ("werkwijze", "how-we-work", "afspraak", "booking", "reserver", "offerte")),
    ):
        if any(term in path for term in terms):
            return label
    return "detail"


def research_candidate(candidate: dict, *, session_factory=requests.Session) -> dict:
    """Research the website FIRST, then choose a published business contact."""
    drop = {
        "homepage_text_excerpt", "homepage_mailtos", "homepage_mailto_contexts",
        "homepage_contact_form_present", "homepage_phone_link_present",
    }
    result = {key: value for key, value in candidate.items() if key not in drop}
    result["research_status"] = "hold_not_ready"
    result["researched_urls"] = []
    result["evidence_candidates"] = []
    result["research_pages_attempted"] = 0
    result["research_pages_fetched"] = 0
    result["research_page_failure_counts"] = {}
    if not candidate.get("ready_for_research"):
        return result

    official_url = _text(candidate.get("official_url"))
    domain = _text(candidate.get("official_domain"))
    homepage_text = _text(candidate.get("homepage_text_excerpt"))
    if not official_url or not domain or candidate.get("homepage_text_excerpt") is None:
        result["research_status"] = "hold_missing_verification_handoff"
        return result

    homepage = {
        "source_url": official_url,
        "parsed": {
            "text": homepage_text,
            "mailtos": candidate.get("homepage_mailtos") or [],
            "mailto_contexts": candidate.get("homepage_mailto_contexts") or [],
            "contact_form_present": bool(candidate.get("homepage_contact_form_present")),
            "phone_link_present": bool(candidate.get("homepage_phone_link_present")),
        },
    }
    pages = [homepage]
    evidence_pages = [evidence_sentences(homepage_text, official_url, "home")]
    researched_urls = [official_url]
    page_failures: Counter[str] = Counter()
    session = _site_session(session_factory, domain)

    # Visit business pages before a contact-heavy navigation consumes the
    # bounded research budget. Contact pages still receive dedicated slots.
    contact_links = list(dict.fromkeys(
        link for link in candidate.get("contact_links") or [] if link != official_url
    ))
    business_links = list(dict.fromkeys(
        link for link in candidate.get("research_links") or []
        if link != official_url and link not in contact_links
    ))
    pending = business_links[:4] + contact_links[:4] + business_links[4:] + contact_links[4:]
    attempted = {official_url}
    while pending and len(attempted) - 1 < MAX_RESEARCH_PAGES:
        link = pending.pop(0)
        if link in attempted:
            continue
        attempted.add(link)
        if hasattr(session, "policy_hold"):
            session.policy_hold = False
        html, final_url, status = safe_fetch_html(session, link, domain)
        if not html or not final_url:
            if getattr(session, "policy_hold", False) and status is None:
                reason = "robots_policy"
            elif status in {401, 403, 429}:
                reason = "http_blocked"
            elif status == 404:
                reason = "http_not_found"
            elif status is not None and status >= 500:
                reason = "http_server_error"
            elif final_url and normalize_domain(final_url) != domain:
                reason = "redirect_disallowed"
            else:
                reason = "request_unavailable"
            page_failures[reason] += 1
            continue
        parsed = parse_html(html)
        researched_urls.append(final_url)
        pages.append({"source_url": final_url, "parsed": parsed})
        evidence_pages.append(evidence_sentences(
            parsed.get("text") or "", final_url, page_type_for_url(final_url)
        ))
        # Follow deeper services, products, help and person pages when linked
        # internally; all reads still share the same twelve-page budget.
        child_contacts = preferred_contact_links(parsed, final_url, domain, limit=3)
        child_research = broad_research_links(parsed, final_url, domain, limit=6)
        new_contacts = [
            url for url in child_contacts if url not in attempted and url not in pending
        ]
        new_research = [
            url for url in child_research
            if url not in attempted and url not in pending and url not in new_contacts
        ]
        pending = new_contacts + pending[:3] + new_research[:4] + pending[3:]
        if len(pending) > 2 * MAX_RESEARCH_PAGES:
            pending = pending[:2 * MAX_RESEARCH_PAGES]

    # Interleave pages so a long homepage or About page cannot consume the
    # entire evidence budget before products, services and support are read.
    deduped: list[dict] = []
    seen: set[str] = set()
    for position in range(max((len(items) for items in evidence_pages), default=0)):
        for items in evidence_pages:
            if position >= len(items):
                continue
            item = items[position]
            key = re.sub(r"[^a-z0-9]+", "", normalize_text(item["text"]))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= MAX_EVIDENCE_PER_CANDIDATE:
                break
        if len(deduped) >= MAX_EVIDENCE_PER_CANDIDATE:
            break

    result["researched_urls"] = researched_urls[: 1 + MAX_RESEARCH_PAGES]
    result["research_pages_attempted"] = len(attempted)
    result["research_pages_fetched"] = len(researched_urls)
    result["research_page_failure_counts"] = dict(sorted(page_failures.items()))
    result["evidence_candidates"] = deduped
    # A reachable, verified website was researched even if its content is too
    # brief for a reliable outreach observation. Never turn a weak finding
    # into a claim merely to improve the coverage metric.
    result["research_status"] = "ready"
    result["research_evidence_status"] = "usable" if deduped else "no_eligible_sentence"
    # No contact requirement above this line. All valid first-party pages
    # contribute evidence even when the business uses only a contact form.
    result.update(select_site_contact(pages, domain))
    return result

def research_candidates(payload: dict, *, limit: int, max_workers: int = MAX_RESEARCH_WORKERS, session_factory=requests.Session) -> dict:
    candidates = payload.get("candidates") or []
    if not isinstance(candidates, list):
        raise ValueError("research_candidates_must_be_list")
    if not 1 <= limit <= MAX_RESEARCH:
        raise ValueError("research_limit_must_be_1_100")
    selected = [item for item in candidates if isinstance(item, dict) and item.get("ready_for_research")][:limit]
    if not selected:
        return {
            "schema_version": "leadscanner-cold-research/1.0",
            "candidate_count": 0,
            "research_ready_count": 0,
            "candidates": [],
        }
    if not 1 <= max_workers <= MAX_RESEARCH_WORKERS:
        raise ValueError("research_workers_out_of_bounds")
    workers = min(max_workers, len(selected))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda item: research_candidate(item, session_factory=session_factory), selected))
    return {
        "schema_version": "leadscanner-cold-research/1.0",
        "candidate_count": len(results),
        "research_ready_count": sum(1 for item in results if item.get("research_status") == "ready"),
        "contacts_found_count": sum(1 for item in results if item.get("contact_status") == "verified_official_site"),
        "named_contacts_found_count": sum(1 for item in results if item.get("contact_role") in {"named_owner", "named_person"}),
        "candidates": results,
        "handoff": {
            "next": "rank_site_findings_then_contact_ready_mail",
            "fields": ["official_domain", "public_business_email", "evidence_candidates", "researched_urls"],
            "no_inference_added": True,
        },
    }


def suppress_previously_used_contact_emails(research: dict, registry_rows: list[dict]) -> dict:
    """Fail closed on emails already suppressed under ANY prior company.

    The company and domain suppression gate runs before website research.
    This second check is necessary for shared personal/free email domains that
    become known only AFTER research. Never discard the website observations.
    """
    result = dict(research)
    candidates = research.get("candidates") or []
    if not isinstance(candidates, list):
        raise ValueError("research_candidates_must_be_list")
    checked = []
    suppressed = 0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("research_candidate_must_be_object")
        row = dict(candidate)
        email = _text(row.get("public_business_email"))
        if email and match_candidate({"email": email}, registry_rows):
            row.update({
                "public_business_email": None,
                "email_source_url": None,
                "contact_person_name": None,
                "contact_role": None,
                "contact_status": "suppressed_existing_email",
            })
            suppressed += 1
        checked.append(row)
    result["candidates"] = checked
    result["contact_dedupe_suppressed_count"] = suppressed
    result["contacts_found_count"] = sum(
        row.get("contact_status") == "verified_official_site" for row in checked
    )
    result["named_contacts_found_count"] = sum(
        row.get("contact_role") in {"named_owner", "named_person"} for row in checked
    )
    return result


def _read(path: str) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("input_must_be_object")
    return payload


def _write(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p_filter = sub.add_parser("filter")
    p_filter.add_argument("--input", required=True)
    p_filter.add_argument("--output", required=True)

    p_verify = sub.add_parser("verify")
    p_verify.add_argument("--input", required=True)
    p_verify.add_argument("--limit", type=int, default=40)
    p_verify.add_argument("--max-workers", type=int, default=MAX_VERIFY_WORKERS)
    p_verify.add_argument("--output", required=True)

    p_research = sub.add_parser("research")
    p_research.add_argument("--input", required=True)
    p_research.add_argument("--limit", type=int, default=40)
    p_research.add_argument("--max-workers", type=int, default=MAX_RESEARCH_WORKERS)
    p_research.add_argument("--output", required=True)

    p_dedupe = sub.add_parser("contact-dedupe")
    p_dedupe.add_argument("--input", required=True)
    p_dedupe.add_argument("--registry-csv", required=True)
    p_dedupe.add_argument("--output", required=True)

    args = parser.parse_args()
    if args.command == "filter":
        result = filter_discovery(_read(args.input))
        _write(args.output, result)
        print(f"COLD_DISCOVERY_FILTER=green input={result['source_candidate_count']} kept={result['candidate_count']} excluded={result['excluded_count']}")
    elif args.command == "verify":
        result = verify_candidates(_read(args.input), limit=args.limit, max_workers=args.max_workers)
        _write(args.output, result)
        print(f"COLD_VERIFY=green checked={result['candidate_count']} ready={result['ready_for_research_count']}")
    elif args.command == "research":
        result = research_candidates(_read(args.input), limit=args.limit, max_workers=args.max_workers)
        _write(args.output, result)
        print(
            f"COLD_RESEARCH=green checked={result['candidate_count']} "
            f"ready={result['research_ready_count']} "
            f"contacts={result.get('contacts_found_count', 0)} "
            "email_required_for_research=false"
        )
    else:
        result = suppress_previously_used_contact_emails(
            _read(args.input), load_registry(Path(args.registry_csv))
        )
        _write(args.output, result)
        print(
            f"COLD_CONTACT_DEDUPE=green suppressed={result['contact_dedupe_suppressed_count']} "
            f"contacts={result['contacts_found_count']} research_preserved=true"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
