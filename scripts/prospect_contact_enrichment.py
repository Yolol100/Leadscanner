from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Callable, Iterable, Mapping, Sequence
from urllib.parse import urlparse

import dns.resolver

from prospect_discovery import BoundedHttpClient, DiscoveryError, host_key, normalize_url, parse_page, root_url
from outreach_sender import append_row, build_sheets_service, ensure_expected_headers, get_values, rows_from_values

PROSPECT_SHEET = "ProspectCandidates"
CONTACT_SHEET = "ContactCandidates"
PROSPECT_HEADERS = [
    "candidate_id", "discovered_at", "company", "website", "source_url",
    "source_id", "source_type", "country", "matched_terms", "status", "reason",
]
CONTACT_HEADERS = [
    "candidate_id", "checked_at", "company", "website", "email", "source_url",
    "email_domain", "domain_alignment", "mx_status", "status", "reason",
]

EMAIL_RE = re.compile(r"(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63})(?![A-Z0-9._%+-])", re.I)
CONTACT_HINTS = (
    "contact", "contacteer", "contacten", "over-ons", "over ons", "about",
    "team", "bedrijf", "organisatie", "klantenservice", "customer-service",
)
ROLE_PRIORITY = {"info": 0, "contact": 1, "hello": 2, "hallo": 3, "sales": 4, "office": 5, "service": 6}
BLOCKED_LOCAL_PARTS = {
    "noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon",
    "postmaster", "abuse", "privacy", "dmarc", "bounce", "bounces",
}
FREE_MAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "yahoo.com", "icloud.com", "me.com", "proton.me", "protonmail.com",
    "aol.com", "gmx.com", "gmx.net",
}
HARD_MAX_PROSPECTS_PER_RUN = 25
DEFAULT_MAX_PROSPECTS_PER_RUN = 10
MAX_CONTACT_PAGES = 3


class ContactDiscoveryError(RuntimeError):
    pass


def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clamp_int(raw: object, default: int, low: int, high: int) -> int:
    try:
        value = int(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        value = default
    return max(low, min(value, high))


def normalize_email(raw: str) -> str:
    address = parseaddr(raw or "")[1].strip().lower().strip("<>.,;:")
    if not EMAIL_RE.fullmatch(address):
        return ""
    return address


def email_domain(address: str) -> str:
    address = normalize_email(address)
    return address.rsplit("@", 1)[1] if "@" in address else ""


def aligned_domain(website: str, address_domain: str) -> bool:
    host = host_key(website)
    address_domain = (address_domain or "").lower().strip(".")
    if not host or not address_domain:
        return False
    return host == address_domain or host.endswith("." + address_domain) or address_domain.endswith("." + host)


def mx_status(domain: str, resolver: Callable[[str, str], Iterable] = dns.resolver.resolve) -> str:
    try:
        answers = list(resolver(domain, "MX"))
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return "missing"
    except Exception:
        return "unknown"
    return "present" if answers else "missing"


def is_allowed_business_address(address: str) -> bool:
    address = normalize_email(address)
    if not address:
        return False
    local, domain = address.rsplit("@", 1)
    local_key = local.replace("_", "-").casefold()
    if local_key in BLOCKED_LOCAL_PARTS or local_key.startswith("no-reply") or local_key.startswith("noreply"):
        return False
    if domain in FREE_MAIL_DOMAINS:
        return False
    return True


@dataclass(frozen=True)
class ContactCandidate:
    email: str
    source_url: str
    source_kind: str
    domain_alignment: str
    mx_status: str
    status: str
    reason: str

    def rank(self) -> tuple[int, int, int, str]:
        local = self.email.split("@", 1)[0].casefold()
        return (0 if self.domain_alignment == "aligned" else 1, ROLE_PRIORITY.get(local, 50), 0 if self.source_kind == "mailto" else 1, self.email)


def extract_addresses(page, source_url: str, website: str) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for target, _ in page.links:
        if not target.lower().startswith("mailto:"):
            continue
        raw = target[7:].split("?", 1)[0]
        for part in raw.split(","):
            address = normalize_email(part)
            if address and address not in seen and is_allowed_business_address(address):
                seen.add(address)
                found.append((address, source_url, "mailto"))
    for match in EMAIL_RE.finditer(page.text or ""):
        address = normalize_email(match.group(1))
        if address and address not in seen and is_allowed_business_address(address):
            seen.add(address)
            found.append((address, source_url, "text"))
    return found


def contact_page_urls(page, website: str) -> list[str]:
    host = host_key(website)
    output: list[str] = []
    for target, label in page.links:
        normalized = normalize_url(target, require_path=True)
        if not normalized or host_key(normalized) != host:
            continue
        parsed = urlparse(normalized)
        context = f"{parsed.path} {label}".casefold()
        if not any(hint in context for hint in CONTACT_HINTS):
            continue
        if normalized not in output:
            output.append(normalized)
        if len(output) >= MAX_CONTACT_PAGES:
            break
    return output


def discover_contact(website: str, *, fetch: Callable[[str], str], resolver: Callable[[str, str], Iterable] = dns.resolver.resolve) -> ContactCandidate | None:
    website = root_url(website)
    if not website:
        raise ContactDiscoveryError("invalid website")
    try:
        homepage = parse_page(fetch(website), website)
    except DiscoveryError as exc:
        raise ContactDiscoveryError(str(exc)) from exc
    raw_candidates = extract_addresses(homepage, website, website)
    for page_url in contact_page_urls(homepage, website):
        try:
            page = parse_page(fetch(page_url), page_url)
        except DiscoveryError:
            continue
        raw_candidates.extend(extract_addresses(page, page_url, website))
    unique: dict[str, tuple[str, str]] = {}
    for address, source_url, source_kind in raw_candidates:
        unique.setdefault(address, (source_url, source_kind))
    candidates: list[ContactCandidate] = []
    for address, (source_url, source_kind) in unique.items():
        domain = email_domain(address)
        alignment = "aligned" if aligned_domain(website, domain) else "external_domain"
        mx = mx_status(domain, resolver)
        if mx == "missing":
            status, reason = "blocked", "public business address found on official site but receiving domain has no MX record"
        elif alignment != "aligned":
            status, reason = "manual_review", "public business address found on official site but email domain differs from website domain"
        elif mx == "unknown":
            status, reason = "manual_review", "public business address found on official site; MX lookup could not be proven"
        else:
            status, reason = "ready", "public business address found on official site with aligned domain and MX present"
        candidates.append(ContactCandidate(address, source_url, source_kind, alignment, mx, status, reason))
    if not candidates:
        return None
    candidates.sort(key=lambda candidate: candidate.rank())
    return candidates[0]


def eligible_prospects(rows: Sequence[Mapping[str, str]], existing_ids: set[str], limit: int) -> list[Mapping[str, str]]:
    output: list[Mapping[str, str]] = []
    for row in rows:
        candidate_id = str(row.get("candidate_id", "")).strip()
        if not candidate_id or candidate_id in existing_ids:
            continue
        if str(row.get("status", "")).strip().casefold() != "qualified":
            continue
        if not str(row.get("website", "")).strip():
            continue
        output.append(row)
        if len(output) >= limit:
            break
    return output


def _load_sheet(service, spreadsheet_id: str, sheet_name: str, expected_headers: list[str]):
    headers, rows = rows_from_values(get_values(service, spreadsheet_id, sheet_name))
    ensure_expected_headers(headers, expected_headers, sheet_name)
    return headers, rows


def run(mode: str | None = None) -> tuple[int, int]:
    mode = (mode or os.getenv("CONTACT_ENRICHMENT_MODE", "validate")).strip().lower()
    if mode not in {"validate", "discover"}:
        raise ContactDiscoveryError("CONTACT_ENRICHMENT_MODE must be validate or discover")
    spreadsheet_id = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        raise ContactDiscoveryError("OUTREACH_SPREADSHEET_ID is required")
    if not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise ContactDiscoveryError("GOOGLE_SERVICE_ACCOUNT_JSON is required")
    service = build_sheets_service()
    _, prospects = _load_sheet(service, spreadsheet_id, PROSPECT_SHEET, PROSPECT_HEADERS)
    _, contacts = _load_sheet(service, spreadsheet_id, CONTACT_SHEET, CONTACT_HEADERS)
    if mode == "validate":
        print("CONTACT_ENRICHMENT=validated sheets=ProspectCandidates,ContactCandidates")
        return 0, 0
    max_rows = clamp_int(os.getenv("CONTACT_ENRICHMENT_MAX_PER_RUN", ""), DEFAULT_MAX_PROSPECTS_PER_RUN, 1, HARD_MAX_PROSPECTS_PER_RUN)
    existing_ids = {str(row.get("candidate_id", "")).strip() for row in contacts if row.get("candidate_id")}
    eligible = eligible_prospects(prospects, existing_ids, max_rows)
    client = BoundedHttpClient(user_agent=os.getenv("CONTACT_ENRICHMENT_USER_AGENT", "WebactueelContactDiscovery/1.0 (+https://andrewbaeten.nl)"), timeout=float(os.getenv("CONTACT_ENRICHMENT_TIMEOUT", "10") or "10"), max_bytes=524_288, min_interval=float(os.getenv("CONTACT_ENRICHMENT_MIN_INTERVAL", "0.5") or "0.5"))
    checked = ready = 0
    for row in eligible:
        checked += 1
        candidate = discover_contact(str(row.get("website", "")), fetch=client.fetch_text)
        if candidate is None:
            output = {"candidate_id": str(row.get("candidate_id", "")), "checked_at": utc_iso(), "company": str(row.get("company", "")), "website": str(row.get("website", "")), "email": "", "source_url": "", "email_domain": "", "domain_alignment": "", "mx_status": "", "status": "not_found", "reason": "no public business email found on the bounded official-site pages"}
        else:
            if candidate.status == "ready": ready += 1
            output = {"candidate_id": str(row.get("candidate_id", "")), "checked_at": utc_iso(), "company": str(row.get("company", "")), "website": str(row.get("website", "")), "email": candidate.email, "source_url": candidate.source_url, "email_domain": email_domain(candidate.email), "domain_alignment": candidate.domain_alignment, "mx_status": candidate.mx_status, "status": candidate.status, "reason": candidate.reason}
        append_row(service, spreadsheet_id, CONTACT_SHEET, CONTACT_HEADERS, output)
    print(f"CONTACT_ENRICHMENT=complete checked={checked} ready={ready}")
    return checked, ready


def main() -> int:
    try:
        run()
    except (ContactDiscoveryError, RuntimeError, ValueError) as exc:
        print(f"CONTACT_ENRICHMENT=blocked detail={exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
