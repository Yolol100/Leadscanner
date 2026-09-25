from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

MAX_WORKERS = 12
MAX_PAGES_PER_SITE = 3
MAX_BYTES_PER_PAGE = 1_000_000
DEFAULT_TIMEOUT = 12

EMAIL_RE = re.compile(r"(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63})(?![A-Z0-9._%+-])", re.I)
CONTACT_HINT_RE = re.compile(
    r"(contact|contacten|contact-us|contact_us|over-ons|over_ons|about|business|sales|partnership|partners|offerte|aanvraag)",
    re.I,
)
BLOCKED_LOCAL_PARTS = {"noreply", "no-reply", "donotreply", "do-not-reply", "example", "test"}


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


def valid_email(value: str) -> bool:
    email = str(value or "").strip().lower().strip(".,;:()[]<>")
    if not EMAIL_RE.fullmatch(email):
        return False
    local, domain = email.rsplit("@", 1)
    if local in BLOCKED_LOCAL_PARTS or local.startswith("no-reply") or local.startswith("noreply"):
        return False
    if domain.endswith((".example", ".test", ".invalid", ".localhost")):
        return False
    return True


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
    for match in EMAIL_RE.findall(cleaned):
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
    text = f"{url} {re.sub(r'<[^>]+>', ' ', html or '')[:120000]}".casefold()
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
    result = {
        **candidate,
        "official_domain_hint": domain,
        "public_business_emails": [],
        "email_source_urls": [],
        "contact_basis_status": "unverified",
        "contact_basis_hint": "not_evaluated",
        "contact_discovery_status": "no_website",
    }
    if not website or not domain:
        return result

    session = session_factory()
    pages: list[tuple[str, str]] = []
    html, final_url, status = fetch_html(session, website)
    if not html or not final_url or normalize_domain(final_url) != domain:
        result["contact_discovery_status"] = "unreachable_or_cross_domain"
        result["website_http_status"] = status
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
    hints: list[str] = []
    for page_url, page_html in pages:
        page_emails = extract_emails(page_html)
        if page_emails:
            hints.append(purpose_hint(page_url, page_html))
        for email in page_emails:
            if email not in emails:
                emails.append(email)
                sources.append(page_url)
            if len(emails) >= 3:
                break
        if len(emails) >= 3:
            break

    result["public_business_emails"] = emails
    result["email_source_urls"] = sources
    result["contact_discovery_status"] = "found" if emails else "no_public_email_found"
    result["contact_basis_hint"] = (
        "possible_purpose_specific" if "possible_purpose_specific" in hints else "generic_contact_only"
    )
    result["contact_basis_status"] = "unverified"
    return result


def discover_contacts(payload: dict, *, max_workers: int = MAX_WORKERS) -> dict:
    candidates = payload.get("candidates") or []
    if not isinstance(candidates, list):
        raise ValueError("candidates must be a list")
    if not 1 <= max_workers <= MAX_WORKERS:
        raise ValueError(f"max_workers must be 1-{MAX_WORKERS}")

    workers = min(max_workers, max(len(candidates), 1))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(inspect_candidate, candidates))

    found = sum(1 for item in results if item.get("public_business_emails"))
    return {
        "schema_version": "webactueel-public-contact-discovery/1.0",
        "candidate_count": len(results),
        "contact_found_count": found,
        "candidates": results,
        "safety": {
            "official_site_only": True,
            "max_pages_per_site": MAX_PAGES_PER_SITE,
            "email_addresses_guessed": False,
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
        "contact_basis_auto_pass=false email_send=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
