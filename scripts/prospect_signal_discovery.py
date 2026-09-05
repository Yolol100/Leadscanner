#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urljoin, urlparse, urlunparse

HIRING_TERMS = (
    "vacature", "vacatures", "werken bij", "werken-bij", "werkenbij",
    "jobs", "job", "careers", "career", "join us", "join-us", "solliciteer", "apply",
)
ACTIVE_HIRING_TERMS = (
    "vacature", "vacatures", "solliciteer", "apply", "functie", "openstaande", "job opening", "open position",
)
WORDPRESS_MARKERS = ("/wp-content/", "/wp-includes/", "wp-json")
WOOCOMMERCE_MARKERS = ("woocommerce", "wc-ajax", "/plugins/woocommerce/")


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def canonical_host(value: object) -> str:
    raw = _text(value)
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def normalize_url(value: object) -> str:
    raw = _text(value)
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password:
        return ""
    host = parsed.hostname.lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        return ""
    netloc = host
    if port and not ((parsed.scheme.lower() == "https" and port == 443) or (parsed.scheme.lower() == "http" and port == 80)):
        netloc = f"{host}:{port}"
    return urlunparse((parsed.scheme.lower(), netloc, parsed.path or "/", "", parsed.query, ""))


def stable_signal_id(candidate_id: object, signal_type: object, evidence_url: object) -> str:
    raw = "|".join((_text(candidate_id).casefold(), _text(signal_type).casefold(), normalize_url(evidence_url).casefold()))
    return "signal-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


class LinkParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.current_href = ""
        self.current_text: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        values = {key.lower(): value or "" for key, value in attrs}
        self.current_href = values.get("href", "").strip()
        self.current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self.current_href:
            self.links.append((urljoin(self.base_url, self.current_href), " ".join(self.current_text).strip()))
            self.current_href = ""
            self.current_text = []

    def handle_data(self, data: str) -> None:
        text = _text(data)
        if text and self.current_href:
            self.current_text.append(text)


@dataclass(frozen=True)
class SignalEvidence:
    signal_type: str
    evidence_url: str
    strength: int
    confidence: str
    note: str


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    text = value.casefold()
    return any(term in text for term in terms)


def _internal_hiring_links(website: str, html: str, *, max_links: int = 2) -> list[str]:
    parser = LinkParser(website)
    parser.feed(html)
    host = canonical_host(website)
    output: list[str] = []
    for target, label in parser.links:
        url = normalize_url(target)
        if not url or canonical_host(url) != host:
            continue
        haystack = f"{urlparse(url).path} {label}".casefold().replace("_", "-")
        if not _contains_any(haystack, HIRING_TERMS):
            continue
        if url not in output:
            output.append(url)
        if len(output) >= max(1, min(max_links, 2)):
            break
    return output


def discover_official_signals(
    website: str,
    homepage_html: str,
    *,
    fetch_text: Callable[[str], str] | None = None,
) -> list[SignalEvidence]:
    website = normalize_url(website)
    if not website:
        return []
    raw = homepage_html.casefold()
    output: list[SignalEvidence] = []

    if any(marker in raw for marker in WORDPRESS_MARKERS):
        output.append(SignalEvidence(
            "technology_wordpress", website, 1, "high",
            "Official homepage contains deterministic WordPress runtime markers.",
        ))
    if any(marker in raw for marker in WOOCOMMERCE_MARKERS):
        output.append(SignalEvidence(
            "technology_woocommerce", website, 1, "high",
            "Official homepage contains deterministic WooCommerce runtime markers.",
        ))

    hiring_links = _internal_hiring_links(website, homepage_html)
    if hiring_links:
        evidence_url = hiring_links[0]
        strength = 1
        note = "Official homepage links to an internal careers/jobs/vacancy page."
        if fetch_text is not None:
            try:
                hiring_html = fetch_text(evidence_url)
            except Exception:
                hiring_html = ""
            if hiring_html and _contains_any(_text(hiring_html), ACTIVE_HIRING_TERMS):
                strength = 2
                note = "Official hiring page contains active vacancy/application language."
        output.append(SignalEvidence("hiring", evidence_url, strength, "high", note))

    unique: dict[tuple[str, str], SignalEvidence] = {}
    for item in output:
        unique[(item.signal_type, normalize_url(item.evidence_url))] = item
    return list(unique.values())
