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
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests

from dedupe_preflight import domains_match
from url_safety import is_public_http_url

MAX_DISCOVERY = 5000
MAX_VERIFY = 100
MAX_RESEARCH = 100
MAX_VERIFY_WORKERS = 10
MAX_RESEARCH_WORKERS = 6
MAX_BYTES = 750_000
MAX_REDIRECTS = 4
DEFAULT_TIMEOUT = 10
HOMEPAGE_CACHE_CHARS = 12_000
MAX_CONTACT_PAGES = 2
MAX_RESEARCH_LINKS = 4
MAX_RESEARCH_PAGES = 2
MAX_EVIDENCE_PER_CANDIDATE = 8

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
    "diensten", "services", "producten", "products", "assortiment", "aanbod", "solutions",
    "oplossingen", "werkwijze", "how-we-work", "afspraak", "reserver", "booking", "offerte",
    "menu", "behandelingen", "treatments", "cases", "projecten",
)
RESEARCH_EXCLUDES = (
    "privacy", "cookie", "voorwaarden", "terms", "vacature", "jobs", "career", "login",
    "account", "cart", "checkout", "nieuws", "news", "blog", "contact",
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


def normalize_domain(value: object) -> str:
    raw = _text(value).casefold()
    if not raw:
        return ""
    candidate = raw if "://" in raw else f"//{raw}"
    try:
        host = (urlparse(candidate).hostname or "").rstrip(".")
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


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
        self.text_parts: list[str] = []
        self.title_parts: list[str] = []
        self._active_href: str | None = None
        self._active_text: list[str] = []
        self._ignore = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs):
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignore += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._active_href = str(href)
                self._active_text = []

    def handle_endtag(self, tag: str):
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"} and self._ignore:
            self._ignore -= 1
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._active_href is not None:
            text = " ".join(self._active_text).strip()
            href = self._active_href
            self.links.append((href, text))
            if href.casefold().startswith("mailto:"):
                self.mailtos.append(unquote(href.split(":", 1)[1].split("?", 1)[0]).strip())
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


def verify_candidate(candidate: dict, *, session_factory=requests.Session) -> dict:
    result = dict(candidate)
    result.update({
        "official_domain": None,
        "official_url": None,
        "identity_status": "hold",
        "identity_evidence": [],
        "public_business_email": None,
        "email_source_url": None,
        "contact_status": "not_checked",
        "excluded_competitor": False,
        "exclusion_reason": None,
        "ready_for_research": False,
        "verification_pages": [],
        "research_links": [],
        "homepage_text_excerpt": None,
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

    session = session_factory()
    html, final_url, status = safe_fetch_html(session, website, domain)
    result["website_http_status"] = status
    if not html or not final_url:
        result["contact_status"] = "hold_unreachable_official_site"
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
    result["research_links"] = internal_links(
        parsed, final_url, domain, RESEARCH_HINTS, exclude=RESEARCH_EXCLUDES, limit=MAX_RESEARCH_LINKS
    )

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

    email_sources: dict[str, str] = {}
    for email in extract_emails(parsed):
        if email_fits_official_context(email, domain):
            email_sources.setdefault(email, final_url)

    if not email_sources:
        contact_links = internal_links(
            parsed, final_url, domain, CONTACT_HINTS, limit=MAX_CONTACT_PAGES
        )
        for link in contact_links:
            linked_html, linked_url, _ = safe_fetch_html(session, link, domain)
            if not linked_html or not linked_url:
                continue
            result["verification_pages"].append(linked_url)
            linked = parse_html(linked_html)
            for email in extract_emails(linked):
                if email_fits_official_context(email, domain):
                    email_sources.setdefault(email, linked_url)
            if email_sources:
                break

    if not email_sources:
        result["contact_status"] = "hold_no_public_business_email"
        return result

    ranked = sorted(email_sources, key=lambda email: email_priority(email, domain))
    email = ranked[0]
    result["public_business_email"] = email
    result["email_source_url"] = email_sources[email]
    result["contact_status"] = "verified_official_site"
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
            "required": ["identity_status=verified", "contact_status=verified_official_site", "ready_for_research=true"],
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
    result = {k: v for k, v in candidate.items() if k != "homepage_text_excerpt"}
    result["research_status"] = "hold_not_ready"
    result["researched_urls"] = []
    result["evidence_candidates"] = []
    if not candidate.get("ready_for_research"):
        return result

    official_url = _text(candidate.get("official_url"))
    domain = _text(candidate.get("official_domain"))
    homepage_text = _text(candidate.get("homepage_text_excerpt"))
    if not official_url or not domain or not homepage_text:
        result["research_status"] = "hold_missing_verification_handoff"
        return result

    evidence = evidence_sentences(homepage_text, official_url, "home")
    researched_urls = [official_url]
    session = session_factory()
    for link in list(candidate.get("research_links") or [])[:MAX_RESEARCH_PAGES]:
        html, final_url, _ = safe_fetch_html(session, link, domain)
        if not html or not final_url:
            continue
        parsed = parse_html(html)
        researched_urls.append(final_url)
        evidence.extend(evidence_sentences(parsed.get("text") or "", final_url, page_type_for_url(final_url)))
        if len(evidence) >= MAX_EVIDENCE_PER_CANDIDATE:
            break

    deduped: list[dict] = []
    seen: set[str] = set()
    for item in evidence:
        key = re.sub(r"[^a-z0-9]+", "", normalize_text(item["text"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= MAX_EVIDENCE_PER_CANDIDATE:
            break

    result["researched_urls"] = researched_urls[: 1 + MAX_RESEARCH_PAGES]
    result["evidence_candidates"] = deduped
    result["research_status"] = "ready" if deduped else "hold_no_first_party_evidence"
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
        "candidates": results,
        "handoff": {
            "next": "outreach_opportunity_selection_not_yet_implemented",
            "fields": ["official_domain", "public_business_email", "evidence_candidates", "researched_urls"],
            "no_inference_added": True,
        },
    }


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

    args = parser.parse_args()
    if args.command == "filter":
        result = filter_discovery(_read(args.input))
        _write(args.output, result)
        print(f"COLD_DISCOVERY_FILTER=green input={result['source_candidate_count']} kept={result['candidate_count']} excluded={result['excluded_count']}")
    elif args.command == "verify":
        result = verify_candidates(_read(args.input), limit=args.limit, max_workers=args.max_workers)
        _write(args.output, result)
        print(f"COLD_VERIFY=green checked={result['candidate_count']} ready={result['ready_for_research_count']}")
    else:
        result = research_candidates(_read(args.input), limit=args.limit, max_workers=args.max_workers)
        _write(args.output, result)
        print(f"COLD_RESEARCH=green checked={result['candidate_count']} ready={result['research_ready_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
