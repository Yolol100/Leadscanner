#!/usr/bin/env python3
"""First-party contact discovery AFTER website research.

Prefer a published email belonging to a verifiably named owner/founder,
then a named team member, then a personal mailbox, then an info/contact inbox.
Never guess an email from a person's name. The absence of an email is a valid
research outcome, not a reason to skip website research.
"""
from __future__ import annotations

import json
import re
import unicodedata
from urllib.parse import unquote, urljoin, urlparse

from dedupe_preflight import normalize_domain

EMAIL_RE = re.compile(r"(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63})(?![A-Z0-9._%+-])", re.I)
PERSON_RE = re.compile(
    r"(?<![A-Za-zÀ-ÿ])([A-ZÀ-Ý][a-zà-ÿ]{1,}(?:[-'][A-ZÀ-Ý]?[a-zà-ÿ]+)?"
    r"(?:\s+(?:van|de|den|der|ten|ter|von))?\s+"
    r"[A-ZÀ-Ý][a-zà-ÿ]{1,}(?:[-'][A-ZÀ-Ý]?[a-zà-ÿ]+)?)(?![A-Za-zÀ-ÿ])"
)
OWNER_ROLE_RE = re.compile(
    r"\b(?:eigenaar|eigenaresse|mede-eigenaar|oprichter|medeoprichter|"
    r"zaakvoerder|directeur|bedrijfsleider|founder|co-founder|owner|"
    r"managing director|proprietor|ceo)\b", re.I
)
GENERIC_LOCAL_PARTS = {
    "info", "contact", "hello", "hallo", "office", "sales", "service",
    "support", "klantenservice", "algemeen", "administratie", "admin",
    "receptie", "reception", "team", "bestellingen", "orders", "winkel",
    "shop", "email", "mail", "vragen", "customerservice", "booking",
    "reservations", "reserveringen", "planning",
}
UNUSABLE_LOCAL_PARTS = {
    "noreply", "no-reply", "donotreply", "do-not-reply", "example",
    "test", "privacy", "dpo", "security", "abuse",
}
PLACEHOLDER_DOMAINS = {
    "example.com", "example.org", "example.net", "voorbeeld.nl",
    "yourdomain.com",
}
PUBLIC_MAIL_DOMAINS = {
    "gmail.com", "hotmail.com", "outlook.com", "live.nl", "live.com",
    "icloud.com", "yahoo.com", "proton.me", "protonmail.com",
}
# These are specifically public contact- and company-person pages, not a list
# of categories allowed for the general business/UX website research.
PERSON_PAGE_HINTS = (
    "team", "medewerker", "onze-mensen", "over-ons", "about", "wie-zijn",
    "eigenaar", "oprichter", "founder", "directeur", "directie", "management",
    "people", "staff", "contact", "contact-us", "contacteer", "bedrijf",
)
FORBIDDEN_PATH_PARTS = (
    "login", "account", "checkout", "cart", "privacy", "terms",
    "voorwaarden", "jobs", "vacature", "cookie",
)
SUPPLIER_MARKERS = (
    "website door", "website by", "site by", "webdesign door",
    "webdesign by", "powered by", "website gemaakt door", "site partner",
    "website ontwikkeld door", "developed by",
)
NONPERSON_PREFIXES = {
    "ons", "onze", "contact", "neem", "bekijk", "meer", "alle", "het",
    "de", "e-mail", "mail", "stuur", "welkom", "over", "voor", "vragen",
    "wij", "open", "lees", "webdesign", "website", "alleen", "dit",
    "team", "maak", "onze", "directeur", "eigenaar",
}


def _normalize(value: object) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "").strip())
    return "".join(x for x in raw if not unicodedata.combining(x)).casefold()


def _email(value: object) -> str:
    value = str(value or "").strip().casefold().strip(' <>"\'.,;:()[]')
    if not EMAIL_RE.fullmatch(value):
        return ""
    local, domain = value.rsplit("@", 1)
    if local in UNUSABLE_LOCAL_PARTS or local.replace(".", "").replace("-", "") in UNUSABLE_LOCAL_PARTS:
        return ""
    if domain in PLACEHOLDER_DOMAINS or domain.endswith((".invalid", ".test", ".localhost", ".example")):
        return ""
    return value


def _names(text: str) -> list[str]:
    # Remove explicitly stated roles before matching capitalized personal
    # names. Otherwise "Eigenaar Jan Jansen" can be misread as "Eigenaar Jan".
    cleaned = OWNER_ROLE_RE.sub(" ", text)
    cleaned = re.sub(
        r"\b(?:monteur|medewerker|adviseur|contactpersoon|accountmanager|"
        r"manager|receptionist|receptioniste|behandelaar)\b",
        " ", cleaned, flags=re.I,
    )
    names = []
    for match in PERSON_RE.finditer(cleaned):
        name = match.group(1)
        words = _normalize(name).split()
        if (
            len(words) < 2
            or words[0] in NONPERSON_PREFIXES
            or any(word in {"contact", "website", "diensten", "team", "eigenaar", "company", "information"} for word in words)
            or len(name) > 70
        ):
            continue
        if name not in names:
            names.append(name)
    return names


def owner_names(parsed_pages: list[dict]) -> list[str]:
    confirmed: list[str] = []
    for page in parsed_pages:
        lines = str((page.get("parsed") or {}).get("text") or "").splitlines()
        for index, line in enumerate(lines):
            if not OWNER_ROLE_RE.search(line):
                continue
            # A name must be on the same role line or immediately adjacent.
            snippets = [line]
            if index:
                snippets.append(lines[index - 1])
            if index + 1 < len(lines):
                snippets.append(lines[index + 1])
            for snippet in snippets:
                for name in _names(snippet):
                    if name not in confirmed:
                        confirmed.append(name)
    return confirmed[:12]


def _matches_local_part(name: str, email: str) -> bool:
    parts = [re.sub(r"[^a-z0-9]", "", item) for item in _normalize(name).split()]
    parts = [item for item in parts if item and item not in {"van", "de", "den", "der", "ten", "ter", "von"}]
    if len(parts) < 2:
        return False
    first, last = parts[0], parts[-1]
    local = re.sub(r"[^a-z0-9]", "", email.split("@", 1)[0])
    possibilities = {first, first + last, first[:1] + last, last + first, last}
    return local in possibilities


def preferred_contact_links(parsed: dict, base_url: str, domain: str, *, limit: int = 8) -> list[str]:
    """Official-site About/Team/Owner/Contact pages first, with no external hops."""
    found = {}
    for href, label in parsed.get("links") or []:
        if not href or str(href).casefold().startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        absolute = urljoin(base_url, str(href))
        url = urlparse(absolute)
        if url.scheme not in {"http", "https"} or url.username is not None or url.password is not None or normalize_domain(absolute) != domain:
            continue
        if any(term in url.path.casefold() for term in FORBIDDEN_PATH_PARTS):
            continue
        if re.search(r"\.(?:pdf|zip|jpg|jpeg|png|gif|webp|svg|json|js|css|xml)$", url.path, re.I):
            continue
        haystack = _normalize(url.path + " " + str(label))
        hits = [x for x in PERSON_PAGE_HINTS if x in haystack]
        if not hits:
            continue
        clean = url._replace(fragment="", query="").geturl()
        if clean == base_url:
            continue
        # Owner/team/about gets attention before generic Contact. Deep pages
        # discovered from About/Team are also allowed in the research budget.
        owner = any(x in haystack for x in ("eigenaar", "oprichter", "founder", "directie", "team", "medewerker", "over-ons", "about"))
        score = (0 if owner else 1, -len(hits), len(url.path), clean)
        if clean not in found or score < found[clean]:
            found[clean] = score
    return [url for url, _ in sorted(found.items(), key=lambda item: item[1])[:limit]]


def _contexts(parsed: dict, email: str) -> list[str]:
    """Find printed or mailto-linked email in its immediate page context."""
    text = str(parsed.get("text") or "")
    snippets = []
    for match in EMAIL_RE.finditer(text):
        if _email(match.group(1)) == email:
            snippets.append(text[max(0, match.start() - 160):match.end() + 90])
    for item in parsed.get("mailto_contexts") or []:
        if _email(item.get("email")) == email:
            snippets.append(str(item.get("context") or "")[-260:])
    if not snippets:
        for href, label in parsed.get("links") or []:
            if str(href).casefold().startswith("mailto:") and _email(unquote(str(href).split(":", 1)[1].split("?", 1)[0])) == email:
                snippets.append(str(label))
    return snippets or [""]


def _emails(parsed: dict) -> list[str]:
    values = []
    for raw in list(parsed.get("mailtos") or []) + EMAIL_RE.findall(str(parsed.get("text") or "")):
        e = _email(raw)
        if e and e not in values:
            values.append(e)
    return values


def _verified_structured_emails(parsed: dict, domain: str, company_name: str) -> list[str]:
    """Use only on-page schema.org business mailboxes matching this business.

    Ignore Person, SiteNavigationElement, vendor and nested third-party nodes.
    Parsing is bounded; JSON-LD never authorizes network requests.
    """
    identities = {
        re.sub(r"[^a-z0-9]", "", _normalize(domain.split(".", 1)[0])),
    }
    if company_name:
        words = [
            part for part in re.findall(r"[a-z0-9]+", _normalize(company_name))
            if part not in {"bv", "b", "v", "nv", "vof", "inc", "ltd", "llc", "the", "de", "het"}
        ]
        identities.add("".join(words))
    identities = {value for value in identities if len(value) >= 5}
    if not identities:
        return []

    emails: list[str] = []
    for raw in (parsed.get("structured_data") or [])[:8]:
        if not isinstance(raw, str) or len(raw) > 64_000:
            continue
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError, RecursionError):
            continue
        nodes = payload if isinstance(payload, list) else [payload]
        # Only explicit @graph nodes, never arbitrary nested documents.
        flattened = []
        for node in nodes[:24]:
            if not isinstance(node, dict):
                continue
            flattened.append(node)
            graph = node.get("@graph")
            if isinstance(graph, list):
                flattened.extend(item for item in graph[:24] if isinstance(item, dict))
        for node in flattened[:48]:
            kinds = node.get("@type")
            kinds = [kinds] if isinstance(kinds, str) else kinds if isinstance(kinds, list) else []
            kind_names = {
                str(kind).rsplit("/", 1)[-1].casefold()
                for kind in kinds if isinstance(kind, str)
            }
            if not any(
                kind in {"organization", "corporation", "localbusiness", "store", "florist",
                         "restaurant", "bakery", "hairsalon", "professionalservice",
                         "automotivebusiness", "medicalbusiness"}
                or kind.endswith(("store", "business"))
                for kind in kind_names
            ):
                continue
            name = re.sub(r"[^a-z0-9]", "", _normalize(node.get("name")))
            if not name or not any(identity == name or identity in name for identity in identities):
                continue
            contact_points = node.get("contactPoint")
            points = contact_points if isinstance(contact_points, list) else [contact_points]
            published = [node.get("email")]
            published.extend(point.get("email") for point in points[:16] if isinstance(point, dict))
            for value in published:
                addresses = value[:8] if isinstance(value, list) else [value]
                for item in addresses:
                    if not isinstance(item, str):
                        continue
                    email = _email(item.removeprefix("mailto:"))
                    if email and email not in emails:
                        emails.append(email)
    return emails[:16]


def select_site_contact(parsed_pages: list[dict], domain: str, *, company_name: str = "") -> dict:
    """Choose a sourced business contact. A missing email never vetoes research."""
    owner_sources = {}
    for page in parsed_pages:
        for name in owner_names([page]):
            owner_sources.setdefault(name, str(page.get("source_url") or ""))
    owners = list(owner_sources)
    candidates = []
    contact_form_source_url = None
    phone_contact_source_url = None
    contact_page_source_url = None
    for page_index, page in enumerate(parsed_pages):
        url = str(page.get("source_url") or "")
        parsed = page.get("parsed") or {}
        source = urlparse(url)
        if source.scheme not in {"http", "https"} or source.username is not None or source.password is not None or normalize_domain(url) != domain:
            continue
        # A fetched first-party Contact page provides a useful manual follow-up
        # route, but does not prove a working form or published email.
        if (
            contact_page_source_url is None
            and re.search(r"(?:^|[/_-])(?:contact|contacteer|contact-us|contactformulier)(?:$|[/_-])",
                          _normalize(source.path))
        ):
            contact_page_source_url = url
        # An actual published HTML contact form or tel: link is an alternative
        # contact channel, not an email address. Never submit forms or guess
        # recipient addresses. Preserve the verified first-party source page.
        if parsed.get("contact_form_present") and contact_form_source_url is None:
            contact_form_source_url = url
        if parsed.get("phone_link_present") and phone_contact_source_url is None:
            phone_contact_source_url = url
        structured_emails = _verified_structured_emails(parsed, domain, company_name)
        for email in dict.fromkeys(_emails(parsed) + structured_emails):
            local, mail_domain = email.split("@", 1)
            same_domain = mail_domain == domain or mail_domain.endswith("." + domain)
            provider = mail_domain in PUBLIC_MAIL_DOMAINS
            contexts = _contexts(parsed, email)
            owner = next((name for name in owners if _matches_local_part(name, email)), None)
            named = None
            for context in contexts:
                for name in _names(context):
                    if _matches_local_part(name, email):
                        named = name
                        break
                if named:
                    break
            context = _normalize(" ".join(contexts))
            if any(marker in context for marker in SUPPLIER_MARKERS) and not owner:
                continue
            # A clearly published employee/owner mailbox on the official site
            # may use another business domain. Do not grab an unrelated agency
            # or widget address merely because it appears in the footer.
            page_path = _normalize(urlparse(url).path)
            business_contact_page = any(x in page_path for x in (
                "contact", "over-ons", "about", "team", "medewerker", "directie", "eigenaar",
            ))
            explicit_contact = any(x in context for x in (
                "email", "e-mail", "mail", "contact", "stuur", "vragen",
            ))
            # The public official Contact/Team page may legitimately list an
            # ISP, custom-mail or external mailbox provider. Its domain is not
            # grounds to reject a visibly published business contact.
            if not (
                same_domain or provider or owner or named or email in structured_emails
                or (business_contact_page and explicit_contact)
            ):
                continue
            generic = local in GENERIC_LOCAL_PARTS
            tier = 0 if owner else 1 if named else 2 if not generic else 3
            page_path = _normalize(urlparse(url).path)
            page_tier = 0 if any(x in page_path for x in PERSON_PAGE_HINTS) else 1
            candidates.append((
                tier, page_tier, 0 if same_domain else 1, page_index, email,
                {
                    "public_business_email": email,
                    "email_source_url": url,
                    "contact_person_name": owner or named,
                    "contact_name_source_url": owner_sources.get(owner) if owner else url if named else None,
                    "contact_role_source_url": owner_sources.get(owner) if owner else None,
                    "contact_role": (
                        "named_owner" if owner else "named_person" if named
                        else "personal_mailbox" if not generic else "general_inbox"
                    ),
                },
            ))
    if not candidates:
        return {
            "public_business_email": None,
            "email_source_url": None,
            "contact_person_name": None,
            "contact_name_source_url": None,
            "contact_role_source_url": None,
            "contact_role": None,
            "contact_status": (
                "contact_form_only" if contact_form_source_url else
                "phone_link_only" if phone_contact_source_url else
                "contact_page_only" if contact_page_source_url else
                "no_public_contact_found"
            ),
            "contact_form_source_url": contact_form_source_url,
            "phone_contact_source_url": phone_contact_source_url,
            "contact_page_source_url": contact_page_source_url,
            "contact_search_pages_checked": len(parsed_pages),
            "named_owner_found_on_site": bool(owners),
        }
    best = min(candidates, key=lambda item: item[:5])[-1]
    return {
        **best,
        "contact_status": "verified_official_site",
        "contact_form_source_url": contact_form_source_url,
        "phone_contact_source_url": phone_contact_source_url,
        "contact_page_source_url": contact_page_source_url,
        "contact_search_pages_checked": len(parsed_pages),
        "named_owner_found_on_site": bool(owners),
    }
