#!/usr/bin/env python3
"""Bounded, source-approved company discovery for the Webactueel Leads workflow.

The module discovers public company websites only. It does not collect contact
addresses, score leads, generate copy, change compliance state, or send mail.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

DEFAULT_USER_AGENT = "WebactueelProspectDiscovery/1.0 (+https://andrewbaeten.nl)"
DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_BYTES = 524_288
DEFAULT_MAX_TOTAL = 50
HARD_MAX_TOTAL = 200
HARD_MAX_BYTES = 2_097_152
HARD_TIMEOUT = 30.0
SOURCE_HEADERS = [
    "source_id", "source_type", "source_url", "country", "include_terms",
    "exclude_terms", "max_candidates", "approved", "enabled",
]
CANDIDATE_HEADERS = [
    "candidate_id", "discovered_at", "company", "website", "source_url",
    "source_id", "source_type", "country", "matched_terms", "status", "reason",
]
LEAD_HEADERS = ["Bedrijf", "Website", "E-mail", "Status"]
ALLOWED_SOURCE_TYPES = {"directory_page", "directory_index", "seed_site"}
SKIP_HOST_SUFFIXES = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "youtu.be", "tiktok.com", "pinterest.com", "google.com",
    "google.nl", "bing.com", "yahoo.com", "duckduckgo.com", "github.com",
    "wikipedia.org",
}


class DiscoveryError(RuntimeError):
    pass


def clamp_int(raw: object, default: int, low: int, high: int) -> int:
    try:
        value = int(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        value = default
    return max(low, min(value, high))


def clamp_float(raw: object, default: float, low: float, high: float) -> float:
    try:
        value = float(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        value = default
    return max(low, min(value, high))


def normalize_url(raw: str, *, require_path: bool = False) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        return ""
    netloc = host
    if port and not ((parsed.scheme.lower() == "https" and port == 443) or (parsed.scheme.lower() == "http" and port == 80)):
        netloc = f"{host}:{port}"
    path = parsed.path or ("/" if require_path else "")
    return urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query if require_path else "", ""))


def host_key(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def root_url(url: str) -> str:
    parsed = urlparse(normalize_url(url))
    return urlunparse((parsed.scheme, parsed.netloc, "/", "", "", "")) if parsed.hostname else ""


def is_skipped_host(host: str) -> bool:
    host = host.lower().strip(".")
    return any(host == item or host.endswith("." + item) for item in SKIP_HOST_SUFFIXES)


def is_public_network_target(host: str, port: int | None = None) -> bool:
    host = (host or "").strip().lower().rstrip(".")
    if not host or host == "localhost" or host.endswith((".localhost", ".local")):
        return False
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return literal.is_global
    try:
        addresses = {row[4][0] for row in socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)}
        return bool(addresses) and all(ipaddress.ip_address(address).is_global for address in addresses)
    except (OSError, ValueError):
        return False


def split_terms(raw: object) -> list[str]:
    if raw is None:
        return []
    values = raw if isinstance(raw, (list, tuple)) else re.split(r"[,;\n]", str(raw))
    output: list[str] = []
    for value in values:
        term = re.sub(r"\s+", " ", str(value)).strip().casefold()
        if term and term not in output:
            output.append(term)
    return output[:50]


def truthy(raw: object) -> bool:
    return str(raw or "").strip().casefold() in {"1", "true", "yes", "ja", "y", "on"}


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    source_type: str
    source_url: str
    country: str = ""
    include_terms: tuple[str, ...] = ()
    exclude_terms: tuple[str, ...] = ()
    max_candidates: int = 20
    approved: bool = False
    enabled: bool = True

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> "SourceSpec":
        source_id = str(row.get("source_id") or "").strip()
        source_type = str(row.get("source_type") or "").strip().casefold()
        source_url = normalize_url(str(row.get("source_url") or ""), require_path=True)
        if not source_id:
            raise DiscoveryError("source_id is required")
        if source_type not in ALLOWED_SOURCE_TYPES:
            raise DiscoveryError(f"unsupported source_type for {source_id}: {source_type}")
        if not source_url:
            raise DiscoveryError(f"invalid source_url for {source_id}")
        return cls(
            source_id=source_id,
            source_type=source_type,
            source_url=source_url,
            country=str(row.get("country") or "").strip(),
            include_terms=tuple(split_terms(row.get("include_terms"))),
            exclude_terms=tuple(split_terms(row.get("exclude_terms"))),
            max_candidates=clamp_int(row.get("max_candidates"), 20, 1, 100),
            approved=truthy(row.get("approved")),
            enabled=truthy(row.get("enabled", True)),
        )


@dataclass
class ParsedPage:
    title: str = ""
    site_name: str = ""
    text: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)


class PageParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_open = False
        self.anchor = ""
        self.anchor_text: list[str] = []
        self.text_parts: list[str] = []
        self.title_parts: list[str] = []
        self.site_name = ""
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {key.lower(): (value or "") for key, value in attrs}
        tag = tag.lower()
        if tag == "title":
            self.title_open = True
        elif tag == "meta":
            prop = (attrs_d.get("property") or attrs_d.get("name") or "").casefold()
            if prop == "og:site_name" and attrs_d.get("content"):
                self.site_name = attrs_d["content"].strip()
        elif tag == "a":
            self.anchor = attrs_d.get("href", "").strip()
            self.anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.title_open = False
        elif tag.lower() == "a" and self.anchor:
            self.links.append((urljoin(self.base_url, self.anchor), " ".join(self.anchor_text).strip()))
            self.anchor = ""
            self.anchor_text = []

    def handle_data(self, data: str) -> None:
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        self.text_parts.append(text)
        if self.title_open:
            self.title_parts.append(text)
        if self.anchor:
            self.anchor_text.append(text)

    def parsed(self) -> ParsedPage:
        return ParsedPage(
            title=" ".join(self.title_parts).strip(),
            site_name=re.sub(r"\s+", " ", self.site_name).strip(),
            text=" ".join(self.text_parts),
            links=self.links,
        )


def parse_page(content: str, base_url: str) -> ParsedPage:
    parser = PageParser(base_url)
    parser.feed(content)
    return parser.parsed()


class SafeRedirectHandler(HTTPRedirectHandler):
    def __init__(self, validator: Callable[[str], None]):
        super().__init__()
        self.validator = validator

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.validator(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class BoundedHttpClient:
    def __init__(self, *, user_agent: str = DEFAULT_USER_AGENT, timeout: float = DEFAULT_TIMEOUT,
                 max_bytes: int = DEFAULT_MAX_BYTES, min_interval: float = 0.25,
                 sleeper: Callable[[float], None] = time.sleep) -> None:
        self.user_agent = user_agent[:200]
        self.timeout = clamp_float(timeout, DEFAULT_TIMEOUT, 1.0, HARD_TIMEOUT)
        self.max_bytes = clamp_int(max_bytes, DEFAULT_MAX_BYTES, 16_384, HARD_MAX_BYTES)
        self.min_interval = clamp_float(min_interval, 0.25, 0.0, 5.0)
        self.sleeper = sleeper
        self.last_request: dict[str, float] = {}
        self.robots: dict[str, RobotFileParser] = {}

    def _assert_public(self, url: str) -> None:
        parsed = urlparse(normalize_url(url, require_path=True))
        if not parsed.hostname or not is_public_network_target(parsed.hostname, parsed.port):
            raise DiscoveryError(f"non-public network target blocked: {url}")

    def _raw_fetch(self, url: str) -> str:
        url = normalize_url(url, require_path=True)
        if not url:
            raise DiscoveryError("invalid URL")
        self._assert_public(url)
        host = host_key(url)
        now = time.monotonic()
        if host in self.last_request:
            wait = self.min_interval - (now - self.last_request[host])
            if wait > 0:
                self.sleeper(wait)
        self.last_request[host] = time.monotonic()
        request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1"})
        try:
            with build_opener(SafeRedirectHandler(self._assert_public)).open(request, timeout=self.timeout) as response:
                content_type = (response.headers.get("Content-Type") or "").casefold()
                if not any(token in content_type for token in ("text/html", "application/xhtml+xml", "text/plain")):
                    raise DiscoveryError(f"unsupported content type: {content_type or 'unknown'}")
                payload = response.read(self.max_bytes + 1)
                if len(payload) > self.max_bytes:
                    raise DiscoveryError("response exceeds byte limit")
                return payload.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        except (HTTPError, URLError, socket.timeout, TimeoutError, OSError) as exc:
            raise DiscoveryError(f"fetch failed for {url}: {exc}") from exc

    def fetch_text(self, url: str) -> str:
        url = normalize_url(url, require_path=True)
        host = host_key(url)
        if host not in self.robots:
            parser = RobotFileParser()
            try:
                parser.parse(self._raw_fetch(urljoin(root_url(url), "robots.txt")).splitlines())
            except DiscoveryError:
                parser.parse([])
            self.robots[host] = parser
        if not self.robots[host].can_fetch(self.user_agent, url):
            raise DiscoveryError(f"robots.txt disallows fetch: {url}")
        return self._raw_fetch(url)


@dataclass
class Candidate:
    company: str
    website: str
    source_url: str
    source_id: str
    source_type: str
    country: str
    matched_terms: tuple[str, ...]
    reason: str

    @property
    def candidate_id(self) -> str:
        raw = f"{host_key(self.website)}|{self.source_id}".encode("utf-8")
        return "prospect-" + hashlib.sha256(raw).hexdigest()[:20]

    def as_row(self, discovered_at: str) -> list[str]:
        return [
            self.candidate_id, discovered_at, self.company, self.website, self.source_url,
            self.source_id, self.source_type, self.country, ", ".join(self.matched_terms),
            "discovered", self.reason,
        ]


def match_terms(text: str, include_terms: Sequence[str], exclude_terms: Sequence[str]) -> tuple[bool, tuple[str, ...]]:
    text = re.sub(r"\s+", " ", text).casefold()
    if any(term in text for term in exclude_terms):
        return False, ()
    matched = tuple(term for term in include_terms if term in text)
    return (not include_terms or bool(matched)), matched


def company_name(page: ParsedPage, website: str) -> str:
    value = page.site_name or (re.split(r"\s+[|–—-]\s+", page.title, maxsplit=1)[0] if page.title else host_key(website).split(".")[0].replace("-", " "))
    return re.sub(r"\s+", " ", value).strip()[:160]


def source_candidate_urls(source: SourceSpec, page: ParsedPage) -> list[tuple[str, str]]:
    if source.source_type == "seed_site":
        return [(root_url(source.source_url), page.text)]
    source_host = host_key(source.source_url)
    output: list[tuple[str, str]] = []
    seen: set[str] = set()
    for target, label in page.links:
        website = root_url(normalize_url(target))
        host = host_key(website)
        if not website or not host or host == source_host or is_skipped_host(host) or host in seen:
            continue
        seen.add(host)
        output.append((website, label))
        if len(output) >= source.max_candidates:
            break
    return output


def discover_candidate(source: SourceSpec, website: str, context: str, fetch: Callable[[str], str]) -> Candidate | None:
    website = root_url(website)
    if not website or is_skipped_host(host_key(website)):
        return None
    try:
        page = parse_page(fetch(website), website)
    except DiscoveryError:
        return None
    accepted, matched = match_terms(f"{context} {page.title} {page.site_name} {page.text}", source.include_terms, source.exclude_terms)
    if not accepted:
        return None
    return Candidate(
        company=company_name(page, website), website=website, source_url=source.source_url,
        source_id=source.source_id, source_type=source.source_type, country=source.country,
        matched_terms=matched,
        reason="official website discovered from approved public source; contact lookup intentionally deferred to Leads",
    )


def discover_source(source: SourceSpec, fetch: Callable[[str], str]) -> list[Candidate]:
    if not source.enabled or not source.approved:
        return []
    source_page = parse_page(fetch(source.source_url), source.source_url)
    candidate_links: list[tuple[str, str]] = []
    if source.source_type == "directory_index":
        source_host = host_key(source.source_url)
        profiles: list[str] = []
        for target, _ in source_page.links:
            profile = normalize_url(target, require_path=True)
            if profile and host_key(profile) == source_host and profile != source.source_url and profile not in profiles:
                profiles.append(profile)
            if len(profiles) >= source.max_candidates:
                break
        seen: set[str] = set()
        for profile in profiles:
            try:
                page = parse_page(fetch(profile), profile)
            except DiscoveryError:
                continue
            proxy = SourceSpec(source.source_id, "directory_page", profile, source.country,
                               source.include_terms, source.exclude_terms, source.max_candidates, True, True)
            for website, label in source_candidate_urls(proxy, page):
                host = host_key(website)
                if host and host not in seen:
                    seen.add(host)
                    candidate_links.append((website, f"{label} {page.text}"))
                if len(candidate_links) >= source.max_candidates:
                    break
            if len(candidate_links) >= source.max_candidates:
                break
    else:
        candidate_links = source_candidate_urls(source, source_page)
    output: list[Candidate] = []
    for website, context in candidate_links:
        candidate = discover_candidate(source, website, context, fetch)
        if candidate:
            output.append(candidate)
        if len(output) >= source.max_candidates:
            break
    return output


def rows_to_dicts(values: Sequence[Sequence[object]], expected_headers: Sequence[str]) -> list[dict[str, object]]:
    if not values:
        raise DiscoveryError("sheet range is empty")
    headers = [str(value).strip() for value in values[0]]
    missing = [header for header in expected_headers if header not in headers]
    if missing:
        raise DiscoveryError("sheet is missing required headers: " + ", ".join(missing))
    output = []
    for row in values[1:]:
        padded = list(row) + [""] * max(0, len(headers) - len(row))
        output.append(dict(zip(headers, padded)))
    return output


def existing_domains(lead_rows: Sequence[Mapping[str, object]], candidate_rows: Sequence[Mapping[str, object]]) -> set[str]:
    output: set[str] = set()
    for row in list(lead_rows) + list(candidate_rows):
        website = normalize_url(str(row.get("Website") or row.get("website") or ""))
        if website:
            output.add(host_key(website))
    return output
