"""Verify only the official homepage and one same-site contact/about page.

Conservative, bounded review of PUBLIC business contact information. No profiles,
directory enrichment, guessed emails, JS execution, or website audit.
"""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, unquote
from urllib.robotparser import RobotFileParser
import re
import unicodedata

import requests
from url_safety import is_public_http_url

AGENT = "WebactueelLeadscanner/1.0 (+https://andrewbaeten.nl)"
MAX_BYTES = 350_000
TIMEOUT = (4, 7)

# Each category corresponds to exactly one canonical Leads Skill leaf.
# Unknown, adjacent, or multi-category activities are NOT auto-approved.
CATEGORIES = {
    "painter": (1, "schilders"), "painting contractor": (1, "schilders"),
    "landscaper": (1, "hoveniers"), "gardener": (1, "hoveniers"),
    "plumber": (1, "loodgieters"), "electrician": (1, "elektriciens"),
    "carpenter": (1, "timmerbedrijven"), "roofing contractor": (1, "dakdekkers"),
    "plasterer": (1, "stukadoors"), "tile contractor": (1, "tegelzetters"),
    "general contractor": (1, "aannemers"), "window cleaning service": (1, "glazenwassers"),
    "cleaning service": (1, "schoonmaakbedrijven"), "tree service": (1, "boomverzorgers"),
    "hair salon": (2, "kappers"), "hairdresser": (2, "kappers"),
    "barber shop": (2, "kappers"), "beauty salon": (2, "schoonheidssalons"),
    "nail salon": (2, "schoonheidssalons"), "driving school": (2, "rijscholen"),
    "gym": (2, "sportscholen"), "fitness center": (2, "sportscholen"),
    "florist": (3, "bloemisten"), "flower shop": (3, "bloemisten"),
    "restaurant": (3, "restaurants"), "cafe": (3, "horecazaken"),
    "bakery": (3, "bakkerijen"), "butcher": (3, "slagerijen"),
    "hotel": (3, "logiesbedrijven"), "bicycle store": (3, "fietsenwinkels"),
    "auto repair": (4, "garages"), "car repair": (4, "garages"),
    "vehicle repair": (4, "garages"), "towing service": (4, "pechhulpbedrijven"),
    "veterinarian": (5, "dierenartsen"), "veterinary clinic": (5, "dierenartsen"),
    "physical therapy": (5, "fysiotherapiepraktijken"),
    "physiotherapist": (5, "fysiotherapiepraktijken"),
    "pet sitter": (5, "dierenoppassers"), "funeral home": (5, "uitvaartbedrijven"),
    "bicycle repair": (6, "reparatiebedrijven"), "appliance repair service": (6, "reparatiebedrijven"),
    "electronics repair shop": (6, "reparatiebedrijven"),
    "laundromat": (6, "wasserijen"), "dry cleaner": (6, "wasserijen"),
}
GENERAL = ("info", "contact")
# Require proof of the actual service on the official site, not an Overture label alone.
BRANCH_PROOF = {
    "schilders": ("schilder",), "hoveniers": ("hovenier", "tuinaanleg", "tuinonderhoud"),
    "loodgieters": ("loodgieter",), "elektriciens": ("elektricien",),
    "timmerbedrijven": ("timmer",), "dakdekkers": ("dakdek",),
    "stukadoors": ("stukadoor",), "tegelzetters": ("tegelzet",),
    "aannemers": ("aannemer", "bouwbedrijf"), "glazenwassers": ("glazenwass",),
    "schoonmaakbedrijven": ("schoonmaak",), "boomverzorgers": ("boomverzorg",),
    "kappers": ("kapper", "kapsalon", "barber"), "schoonheidssalons": ("schoonheid", "beauty", "nagel", "pedicure"),
    "rijscholen": ("rijschool",), "sportscholen": ("sportschool", "fitness", "gym", "groepsles"),
    "bloemisten": ("bloemist", "bloemen"), "restaurants": ("restaurant",),
    "horecazaken": ("horeca", "cafe", "lunchroom"), "bakkerijen": ("bakker",),
    "slagerijen": ("slager",), "logiesbedrijven": ("hotel", "overnacht", "logies"),
    "fietsenwinkels": ("fietsenwinkel", "fietsverkoop", "tweewieler"),
    "garages": ("autogarage", "garage", "autoreparatie"),
    "pechhulpbedrijven": ("pechhulp", "sleepdienst"),
    "dierenartsen": ("dierenarts", "dierenkliniek", "veterinair"),
    "fysiotherapiepraktijken": ("fysiotherap",),
    "dierenoppassers": ("dierenoppas", "petsitter"),
    "uitvaartbedrijven": ("uitvaart",),
    "reparatiebedrijven": ("reparatie", "fietsherstel", "witgoed", "elektronica"),
    "wasserijen": ("wasserij", "stomerij"),
}
MAIL_RE = re.compile(r"^[a-z0-9._%+\-]{1,64}@[a-z0-9.-]+\.[a-z]{2,63}$", re.I)
NAME_TERMS = {"bedrijf", "bedrijven", "bv", "b.v.", "vof", "van", "de", "het", "en", "the", "groep"}
# An industry word or city in a business hint is not distinctive identity proof.
GENERIC_NAME_WORDS = {
    "schildersbedrijf", "schilderwerken", "schilder", "hoveniersbedrijf", "hovenier",
    "tuinaanleg", "bouwbedrijf", "aannemer", "dakdekker", "loodgieter",
    "installatiebedrijf", "schoonmaakbedrijf", "schoonmaak", "glazenwasser",
    "kapsalon", "kapper", "barber", "beautysalon", "schoonheidssalon",
    "restaurant", "horeca", "bloemist", "bakkerij", "slagerij", "garage",
    "autogarage", "autobedrijf", "fysiotherapie", "fysiotherapiepraktijk",
    "dierenarts", "dierenkliniek", "reparatiebedrijf", "reparatie", "wasserij",
    "stomerij", "rotterdam", "amsterdam", "nederland",
}


def norm(value):
    val = unicodedata.normalize("NFKD", str(value or ""))
    val = "".join(ch for ch in val if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", val.casefold()).strip()


def category(row):
    value = norm(row.get("category_hint"))
    return CATEGORIES.get(value)


class PublicHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.texts = []
        self.links = []
        self.mailto = []
        self.named_links = []
        self._active_mail = None
        self._active_text = []
        self._ignore = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style"}:
            self._ignore += 1
        if tag == "a":
            href = (attrs.get("href") or "").strip()
            if href.startswith("mailto:"):
                address = unquote(href[7:].split("?")[0]).strip().lower()
                self.mailto.append(address)
                self._active_mail = address
                self._active_text = []
            elif href:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag == "a" and self._active_mail:
            self.named_links.append((self._active_mail, " ".join(self._active_text).strip()))
            self._active_mail = None
            self._active_text = []
        if tag in {"script", "style"} and self._ignore:
            self._ignore -= 1

    def handle_data(self, data):
        if not self._ignore:
            self.texts.append(data)
            if self._active_mail:
                self._active_text.append(data)


def _same_site_shape(url, host):
    """Cheap syntactic check for candidate links; NO network or DNS lookup."""
    try:
        target = urlsplit(url)
        return (target.scheme in {"http", "https"}
                and target.username is None and target.password is None
                and (target.hostname or "").removeprefix("www.") ==
                    (host or "").removeprefix("www.")
                and target.port in (None, 80, 443))
    except (ValueError, TypeError):
        return False


def _safe_same_site(url, host):
    # DNS/public-IP safety check remains mandatory before every HTTP request.
    return _same_site_shape(url, host) and is_public_http_url(url)


def _get(url, host, session):
    # Redirects are manual: never follow links to another domain or private hosts.
    for _ in range(3):
        if not _safe_same_site(url, host):
            return None
        try:
            response = session.get(url, timeout=TIMEOUT, headers={"User-Agent": AGENT},
                                   allow_redirects=False, stream=True)
            try:
                if response.status_code in {301, 302, 303, 307, 308}:
                    target = urljoin(url, response.headers.get("Location", ""))
                    if not _safe_same_site(target, host):
                        return None
                    url = target
                    continue
                if response.status_code != 200:
                    return None
                if "text/html" not in response.headers.get("Content-Type", "").lower():
                    return None
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=16384):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        return None
                    chunks.append(chunk)
                return b"".join(chunks).decode("utf-8", errors="replace")
            finally:
                response.close()
        except requests.RequestException:
            return None
    return None


def _robots_policy(base_url, session):
    # Read once per site. Deny if unavailable, malformed or redirected unsafely.
    host = urlsplit(base_url).hostname
    url = urlsplit(base_url)
    robots_url = f"{url.scheme}://{host}/robots.txt"
    # Sites with HTTP hints often redirect robots.txt to the HTTPS equivalent.
    # Follow only same-site HTTPS robots redirects, never bypass the policy.
    for _ in range(3):
        if not _safe_same_site(robots_url, host):
            return None
        try:
            response = session.get(robots_url, timeout=TIMEOUT, stream=True,
                                   headers={"User-Agent": AGENT},
                                   allow_redirects=False)
            try:
                if response.status_code in {301, 302, 303, 307, 308}:
                    target = urljoin(robots_url, response.headers.get("Location", ""))
                    dest = urlsplit(target)
                    if (dest.scheme != "https" or dest.path != "/robots.txt"
                            or dest.query or dest.fragment
                            or not _safe_same_site(target, host)):
                        return None
                    robots_url = target
                    continue
                if response.status_code == 404:
                    return True
                if response.status_code != 200:
                    return None
                raw = bytearray()
                for chunk in response.iter_content(chunk_size=16384):
                    raw.extend(chunk)
                    if len(raw) > 100_000:
                        return None
                parser = RobotFileParser()
                parser.parse(raw.decode("utf-8", errors="replace").splitlines())
                return parser
            finally:
                response.close()
        except requests.RequestException:
            return None
    return None

def _with_captured_pages(payload, pages, enabled):
    """Internal-only data: parsed official HTML used by the same successful check."""
    if enabled:
        payload["_captured_pages"] = pages
    return payload


def verify_official_site(row, *, session=requests, expected_email=None,
                         collect_evidence=False, diagnostic=None):
    """Return a verified official company/address, or None with safe reason.

    diagnostic is an optional callback receiving ONLY a fixed reason code.
    Never pass website, email, page content, exception, or contact identity.
    """
    def reject(reason):
        if diagnostic is not None:
            diagnostic(reason)
        return None

    from new_leads import safe_hint
    from target_scope import is_blocked_place
    name = str(row.get("name_hint") or "").strip()
    url = safe_hint(row.get("website_hint"))
    mapping = category(row)
    if not name or not url or not mapping:
        return reject("input_not_verified")
    host = urlsplit(url).hostname
    if not _safe_same_site(url, host):
        return reject("site_url_not_public")
    policy = _robots_policy(url, session)
    if policy is None:
        return reject("robots_unavailable")
    if policy is not True and not policy.can_fetch(AGENT, url):
        return reject("robots_disallowed")
    html = _get(url, host, session)
    if html is None:
        return reject("homepage_unavailable")
    page = PublicHTML()
    page.feed(html)
    evidence_pages = [(url, " ".join(page.texts))] if collect_evidence else []
    content = norm(" ".join(page.texts))
    name_words = [x for x in norm(name).split()
                  if len(x) >= 3 and x not in NAME_TERMS
                  and x not in GENERIC_NAME_WORDS and not x.endswith("bedrijf")]
    # A category word like "schildersbedrijf" alone cannot prove identity.
    if not name_words or not any(word in content.split() for word in name_words):
        return reject("homepage_identity_unverified")
    if is_blocked_place(norm(name), norm(row.get("category_hint"))):
        return reject("place_blocked")
    if not any(word in content for word in BRANCH_PROOF[mapping[1]]):
        return reject("homepage_activity_unverified")
    candidates = list(page.mailto)
    named_links = list(page.named_links)
    candidates.extend(x.lower() for x in re.findall(
        r"(?<![a-z0-9._%+-])[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,63}", 
        " ".join(page.texts), re.I))
    source_by_email = {email: url for email in candidates}
    # Reverification-only fast path: the exact previously selected email is
    # already visibly published on this official homepage. Reuse the captured
    # homepage instead of needlessly loading the same site's contact page.
    # New discovery calls keep the original named-owner-first search unchanged.
    expected = str(expected_email or "").strip().casefold()
    if expected and not MAIL_RE.fullmatch(expected):
        return reject("selected_address_invalid")
    # Evidence collection may need the official contact page for Dutch
    # locality even if the exact email is already on the homepage.
    # A fully sufficient homepage still takes the two-request fast path.
    has_locality = bool(re.search(r"\b[1-9]\d{3}\s?[A-Z]{2}\b",
                                  " ".join(page.texts)))
    if expected and expected in candidates and (not collect_evidence or has_locality):
        return _with_captured_pages({
            "company": name, "website": url, "email": expected,
            "source_url": url, "cluster": mapping[0],
            "branche_meervoud": mapping[1],
            "greeting": "Hoi," if mapping[0] >= 5 else "Goedendag,",
            "status": "verified_website_and_email",
        }, evidence_pages, collect_evidence)
    # Only a linked, same-domain contact/about page, never a generic site crawl.
    # Prefer an explicitly labeled contact endpoint over an earlier "about"
    # link. Both choices remain bounded to at most ONE additional same-site GET.
    links = []
    for href in page.links:
        dest = urljoin(url, href)
        slug = urlsplit(dest).path.casefold()
        if (any(term in slug for term in ("contact", "over-ons", "about"))
                and _same_site_shape(dest, host) and dest not in links):
            links.append(dest)
    links.sort(key=lambda item: (
        0 if "contact" in urlsplit(item).path.casefold() else 1,
    ))
    for dest in links[:1]:
        if policy is not True and not policy.can_fetch(AGENT, dest):
            continue  # Homepage contact may already be independently published.
        inner = _get(dest, host, session)
        if inner is not None:
            sub = PublicHTML()
            sub.feed(inner)
            if collect_evidence:
                evidence_pages.append((dest, " ".join(sub.texts)))
            discovered = list(sub.mailto)
            discovered.extend(x.lower() for x in re.findall(
                r"(?<![a-z0-9._%+-])[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,63}",
                " ".join(sub.texts), re.I))
            candidates.extend(discovered)
            named_links.extend(sub.named_links)
            source_by_email.update({email: dest for email in discovered})
    published = sorted({x for x in candidates if MAIL_RE.fullmatch(x)})
    general = [x for x in published if x.split("@")[0] in GENERAL]
    # Only a direct mailto link explicitly naming an owner/contact person
    # proves the link between that person and the published address.
    first = None
    chosen = None
    for email, label in named_links:
        if not MAIL_RE.fullmatch(email) or not re.search(
                r"\b(eigenaar|directeur|contactpersoon|owner)\b", label, re.I):
            continue
        person = re.match(r"^([A-ZÀ-ÿ][a-zà-ÿ-]{2,})\s+"
                          r"(?:[a-z]{1,3}\s+)?[A-ZÀ-ÿ][A-Za-zÀ-ÿ'-]{2,}", label)
        if person:
            first, chosen = person.group(1), email
            break
    if expected:
        if expected not in published:
            return reject("selected_address_not_published")
        # Exact-address rechecks must not silently substitute a different
        # address that is also on the official contact page.
        chosen, first = expected, None
    if chosen is None:
        if not general:
            return reject("general_address_not_published")
        chosen = next((x for x in general if x.startswith("info@")), general[0])
    greeting = f"Hoi {first}," if first else ("Hoi," if mapping[0] >= 5 else "Goedendag,")
    return _with_captured_pages({
        "company": name, "website": url, "email": chosen,
        "source_url": source_by_email[chosen], "cluster": mapping[0],
        "branche_meervoud": mapping[1],
        "greeting": greeting,
        "status": "verified_website_and_email",
    }, evidence_pages, collect_evidence)
