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
    "vehicle repair": (4, "garages"), "towing service": (4, "sleepdiensten"),
    "veterinarian": (5, "dierenartsen"), "veterinary clinic": (5, "dierenartsen"),
    "physical therapy": (5, "fysiotherapiepraktijken"),
    "physiotherapist": (5, "fysiotherapiepraktijken"),
    "pet sitter": (5, "dierenoppassers"), "funeral home": (5, "uitvaartondernemers"),
    "bicycle repair": (6, "reparatiebedrijven"), "appliance repair service": (6, "reparatiebedrijven"),
    "electronics repair shop": (6, "reparatiebedrijven"),
    "laundromat": (6, "wasserijen"), "dry cleaner": (6, "stomerijen"),
}
GENERAL = ("info", "contact")
MAIL_RE = re.compile(r"^[a-z0-9._%+\-]{1,64}@[a-z0-9.-]+\.[a-z]{2,63}$", re.I)
NAME_TERMS = {"bedrijf", "bedrijven", "bv", "b.v.", "vof", "van", "de", "het", "en", "the", "groep"}


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
        self._ignore = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style"}:
            self._ignore += 1
        if tag == "a":
            href = (attrs.get("href") or "").strip()
            if href.startswith("mailto:"):
                self.mailto.append(unquote(href[7:].split("?")[0]).strip().lower())
            elif href:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self._ignore:
            self._ignore -= 1

    def handle_data(self, data):
        if not self._ignore:
            self.texts.append(data)


def _safe_same_site(url, host):
    if not is_public_http_url(url):
        return False
    target = urlsplit(url)
    return target.hostname == host and target.port in (None, 80, 443)


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


def _robots_ok(base_url, paths, session):
    # The robots file is read once per site. Deny if unavailable or malformed.
    host = urlsplit(base_url).hostname
    url = urlsplit(base_url)
    robots_url = f"{url.scheme}://{host}/robots.txt"
    if not _safe_same_site(robots_url, host):
        return False
    try:
        response = session.get(robots_url, timeout=TIMEOUT,
                               headers={"User-Agent": AGENT}, allow_redirects=False)
        if response.status_code == 404:
            return True
        if response.status_code != 200 or len(response.content) > 100_000:
            return False
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        return all(parser.can_fetch(AGENT, path) for path in paths)
    except requests.RequestException:
        return False


def verify_official_site(row, *, session=requests):
    """Return a conservatively verified company+published email or None."""
    from new_leads import safe_hint
    from target_scope import is_blocked_place
    name = str(row.get("name_hint") or "").strip()
    url = safe_hint(row.get("website_hint"))
    mapping = category(row)
    if not name or not url or not mapping:
        return None
    host = urlsplit(url).hostname
    if not _safe_same_site(url, host):
        return None
    if not _robots_ok(url, [url], session):
        return None
    html = _get(url, host, session)
    if html is None:
        return None
    page = PublicHTML()
    page.feed(html)
    content = norm(" ".join(page.texts))
    name_words = [x for x in norm(name).split() if len(x) >= 4 and x not in NAME_TERMS]
    # Require a distinctive official business name on the site, not just a working URL.
    if not name_words or not any(word in content.split() for word in name_words):
        return None
    if is_blocked_place(norm(name), norm(row.get("category_hint"))):
        return None
    candidates = list(page.mailto)
    contact_source = url
    # Only a linked, same-domain contact/about page, never a generic site crawl.
    links = []
    for href in page.links:
        dest = urljoin(url, href)
        slug = urlsplit(dest).path.casefold()
        if (any(term in slug for term in ("contact", "over-ons", "about"))
                and _safe_same_site(dest, host) and dest not in links):
            links.append(dest)
    for dest in links[:1]:
        if not _robots_ok(url, [dest], session):
            return None
        inner = _get(dest, host, session)
        if inner is not None:
            sub = PublicHTML()
            sub.feed(inner)
            candidates.extend(sub.mailto)
            contact_source = dest
    published = sorted({x for x in candidates if MAIL_RE.fullmatch(x)})
    general = [x for x in published if x.split("@")[0] in GENERAL]
    # Named addresses require pairing to a verified person; deliberately
    # reject inferred name/address combinations rather than fabricate a greeting.
    if not general:
        return None
    chosen = next((x for x in general if x.startswith("info@")), general[0])
    return {
        "company": name, "website": url, "email": chosen,
        "source_url": contact_source, "cluster": mapping[0],
        "branche_meervoud": mapping[1],
        "greeting": "Hoi," if mapping[0] >= 5 else "Goedendag,",
        "status": "verified_website_and_email",
    }
