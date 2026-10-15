"""Evidence-limited editorial rewrites for the exact 450 *existing* private drafts.

No SMTP, IMAP, sending, deletion, new leads, social-network scraping,
third-party email enrichment, website scans, or guessed business complaints.

Only the homepage and one linked official contact/about page are opened
through the repo's established robots-aware bounded website verifier.
A phrase is used only when the actual official page text contains it.
All recipient identities, evidence and message text stay in private Sheets.
Scores below 10 are editorial estimates, never expected reply rates.
"""
from __future__ import annotations

import copy
import re
from urllib.parse import urlsplit, urlunsplit
import review450 as base

# Priority matters. Distinctive, source-verifiable features before generic words.
# Each label denotes only the service the site explicitly names; no performance claims.
TOPICS = {
    "restaurants": [
        ("rijsttafel", "rijsttafels"), ("groepsarrangement", "groepsarrangementen"),
        ("groepsmenu", "groepsmenu's"), ("private dining", "private dining"),
        ("buffet", "buffetten"), ("high tea", "high tea"),
        ("kinderfeest", "kinderfeestjes"), ("kindermenu", "kindermenu"),
        ("pannenkoek", "pannenkoeken"), ("proeverij", "proeverijen"),
        ("oester", "oesters"), ("schaaldier", "schaal- en schelpdieren"),
        ("sushi", "sushi"), ("tapas", "tapas"),
        ("vegan", "vegan opties"), ("vegetarisch", "vegetarische gerechten"),
        ("glutenvrij", "glutenvrije gerechten"), ("afhalen", "afhalen"),
        ("bezorg", "bezorging"), ("catering", "catering"),
        ("brunch", "brunch"), ("trouwen", "trouwfeesten"),
        ("bruiloft", "bruiloften"), ("feest", "feesten"),
        ("arrangement", "arrangementen"), ("vergader", "vergaderingen"),
        ("terras", "terras"), ("ontbijt", "ontbijt"),
        ("lunch", "lunch"), ("diner", "diner"), ("menukaart", "menukaart"),
    ],
    "horecazaken": [
        ("high tea", "high tea"), ("brunch", "brunch"),
        ("borrelplank", "borrelplanken"), ("borrel", "borrels"),
        ("bierproeverij", "bierproeverijen"), ("cocktail", "cocktails"),
        ("kinderfeest", "kinderfeestjes"), ("terras", "terras"),
        ("ontbijt", "ontbijt"), ("lunch", "lunch"), ("diner", "diner"),
        ("afhalen", "afhalen"), ("vergader", "vergaderingen"),
        ("feest", "feesten"), ("arrangement", "arrangementen"),
    ],
    "logiesbedrijven": [
        ("familiekamer", "familiekamers"), ("suite", "suites"),
        ("wellness", "wellness"), ("sauna", "sauna"),
        ("spa", "spa"), ("trouwen", "trouwen"), ("bruiloft", "bruiloften"),
        ("vergader", "vergaderarrangementen"), ("ontbijt", "ontbijt"),
        ("restaurant", "restaurant"), ("arrangement", "arrangementen"),
        ("groepsverblijf", "groepsverblijven"), ("vakantiehuis", "vakantiehuizen"),
        ("b&b", "B&B"), ("bed and breakfast", "bed & breakfast"),
        ("kamer", "kamers"), ("overnacht", "overnachtingen"),
    ],
    "sportscholen": [
        ("crossfit", "CrossFit"), ("kickbok", "kickboksen"), ("boksen", "boksen"),
        ("pilates", "pilates"), ("yoga", "yoga"), ("hyrox", "HYROX"),
        ("personal training", "personal training"), ("personal trainer", "personal training"),
        ("groepsles", "groepslessen"), ("bootcamp", "bootcamp"),
        ("proefles", "proeflessen"), ("small group", "small-grouptraining"),
        ("fitness", "fitness"), ("sportschool", "sportaanbod"),
    ],
    "kappers": [
        ("balayage", "balayage"), ("highlights", "highlights"),
        ("haarextension", "haarextensions"), ("bruidskapsel", "bruidskapsels"),
        ("barbier", "barbierbehandelingen"), ("baard", "baardverzorging"),
        ("gezichtsbehandeling", "gezichtsbehandelingen"),
        ("kleuren", "haarkleuring"), ("knippen", "knippen"), ("kapper", "kappersdiensten"),
    ],
    "schilders": [
        ("houtrot", "houtrotherstel"), ("monument", "monumentenwerk"),
        ("restauratie", "restauratie"), ("behangen", "behangen"),
        ("kleuradvies", "kleuradvies"), ("buitenschilderwerk", "buitenschilderwerk"),
        ("binnenschilderwerk", "binnenschilderwerk"), ("schilder", "schilderwerk"),
    ],
    "hoveniers": [
        ("boomverzorg", "boomverzorging"), ("vijver", "vijvers"),
        ("sierbestrating", "sierbestrating"), ("veranda", "veranda's"),
        ("pergola", "pergola's"), ("vlonder", "vlonders"),
        ("tuinontwerp", "tuinontwerp"), ("tuinaanleg", "tuinaanleg"),
        ("tuinonderhoud", "tuinonderhoud"), ("hovenier", "hovenierswerk"),
    ],
    "fietsenwinkels": [
        ("tweedehands", "tweedehands fietsen"), ("proefrit", "proefritten"),
        ("e-bike", "e-bikes"), ("elektrische fiets", "elektrische fietsen"),
        ("fietsenwinkel", "fietsen"), ("fietsreparatie", "fietsreparaties"),
    ],
    "reparatiebedrijven": [
        ("step", "steps"), ("telefoon", "telefoons"), ("smartphone", "smartphones"),
        ("tablet", "tablets"), ("witgoed", "witgoed"),
        ("fiets", "fietsen"), ("reparatie", "reparaties"),
    ],
    "schoonheidssalons": [
        ("pedicure", "pedicure"), ("manicure", "manicure"),
        ("nagel", "nagelbehandelingen"), ("gezichtsbehandeling", "gezichtsbehandelingen"),
        ("massage", "massage"), ("schoonheid", "schoonheidsbehandelingen"),
    ],
    "bloemisten": [
        ("rouwwerk", "rouwwerk"), ("rouw", "rouwboeketten"),
        ("bruids", "bruidsbloemen"), ("bruiloft", "bruiloftsbloemen"),
        ("boeket", "boeketten"), ("bloemen", "bloemen"),
    ],
    "fysiotherapiepraktijken": [
        ("handtherapie", "handtherapie"), ("sportfysiotherapie", "sportfysiotherapie"),
        ("bekkenfysiotherapie", "bekkenfysiotherapie"),
        ("manuele therapie", "manuele therapie"), ("fysiotherapie", "fysiotherapie"),
    ],
    "stukadoors": [
        ("cinewall", "cinewalls"), ("spuitwerk", "spuitwerk"),
        ("buitenstuc", "buitenstucwerk"), ("stucwerk", "stucwerk"),
        ("stukadoor", "stukadoorswerk"),
    ],
    "loodgieters": [
        ("cv", "cv-onderhoud"), ("lekkage", "lekkages"),
        ("riolering", "riolering"), ("loodgieter", "loodgieterswerk"),
    ],
    "glazenwassers": [
        ("gevelreiniging", "gevelreiniging"),
        ("glasbewassing", "glasbewassing"), ("glazenwass", "glazenwassen"),
    ],
    "garages": [
        ("apk", "APK"), ("banden", "banden"),
        ("airco", "airco-onderhoud"), ("camper", "campers"),
        ("autoreparatie", "autoreparaties"), ("garage", "garagediensten"),
    ],
}
BROAD = frozenset({
    "menukaart", "lunch", "diner", "ontbijt", "kamers", "overnachtingen",
    "sportaanbod", "fitness", "kappersdiensten", "schilderwerk",
    "hovenierswerk", "bloemen", "fietsen", "reparaties", "schoonheidsbehandelingen",
    "fysiotherapie", "stukadoorswerk", "loodgieterswerk", "glazenwassen",
    "garagediensten", "restaurant", "arrangementen", "terras",
})
HOMEPAGE_MAX = 2
FORBIDDEN = base.FORBIDDEN


def topic_pattern(needle):
    from verify_official_lead import norm
    token = norm(needle)
    # A distinct word/phrase boundary: "vis" must not match "advies".
    return re.compile(r"(?<![a-z0-9])" + re.escape(token).replace(r"\ ", r"\s+") + r"[a-z]*\b")


def topics_from_verified_pages(row, pages):
    """Return only exact labeled service terms actually seen on official pages."""
    from verify_official_lead import norm
    text = norm(" ".join(content for _, content in pages))
    found = []
    for needle, label in TOPICS.get(row["branch"], []):
        if topic_pattern(needle).search(text) and label not in found:
            found.append(label)
    # A company's name by itself is insufficient evidence of a unique service.
    identity_words = set(norm(row["company"]).split())
    feature = [v for v in found if v not in BROAD and not set(norm(v).split()).issubset(identity_words)]
    distinctive = feature[:2]
    if distinctive:
        return distinctive, len(distinctive)
    return found[:2], 0


def rewrite(row, qa_row, topics, distinctiveness):
    """One low-pressure permission CTA, no invented site problems or results."""
    base.validate(row)
    if not topics:
        return "", "", "GEEN_SPECIFIEK_BEWIJS", 6.5, "Geen bruikbaar, onafhankelijk bedrijfskenmerk op de bezochte officiële pagina."
    greeting = row["body"].split("\n", 1)[0]
    left = topics[0]
    right = topics[1] if len(topics) > 1 else None
    # Explicitly observed services are facts; relative importance/defects are not.
    hook = "Jullie website noemt " + left + (" en " + right if right else "") + "."
    cluster = row["cluster"]
    if cluster == "1":
        offer = "Ik kan een compacte mobiele voorbeeldopzet schetsen die dit werk toont en bezoekers helpt hun aanvraag gericht te formuleren."
    elif cluster == "2":
        offer = "Ik kan een helder mobiel overzicht schetsen waarmee bezoekers het aanbod begrijpen en via jullie contact- of afspraakroute verdergaan."
    elif cluster == "3":
        offer = "Ik kan een kleine mobiele voorbeeldopzet schetsen die dit aanbod makkelijker laat kiezen en aansluit op jullie bestaande contact- of reserveringsroute."
    elif cluster == "4":
        offer = "Ik kan een helder mobiel dienstenoverzicht schetsen, zodat bezoekers weten waarvoor ze bellen of contact opnemen."
    elif cluster == "5":
        offer = "Ik kan een rustig mobiel overzicht schetsen van deze informatie, met een logische stap naar persoonlijk contact."
    else:
        offer = "Ik kan een mobiel overzicht schetsen van de diensten en hoe klanten hun vraag bij jullie neerleggen."
    # A conditional proposal, not an assertion that the website is deficient.
    idea = ("beide onderdelen" if right else left)
    question = "Zal ik een kort voorbeeld voor " + idea + " uitwerken?"
    subject = (left[:1].upper() + left[1:] + (" en " + right if right else "") +
               " bij " + row["company"])
    # Do not include the user's expressly excluded introductory sentence.
    content = "\n\n".join([greeting, hook, offer, question, base.OPT, "Groet,\nAndrew"])
    updated = copy.deepcopy(row)
    updated.update(subject=subject, body=content)
    base.validate(updated)
    # These are editorial estimates, not objective or validated conversion scores.
    score = 8.9 if distinctiveness == 2 else (8.2 if distinctiveness == 1 else 7.3)
    status = "VOORSTEL_BRONVERMELD" if distinctiveness else "VOORSTEL_NOG_TE_GENERIEK"
    comments = ("Twee bronvermelde onderscheidende aanknopingspunten, menselijke inhoudscheck volgt." if distinctiveness == 2
                else "Bronvermelde dienst, maar beperkte unieke personalisatie; menselijke verbetercontrole volgt.")
    return subject, content, status, score, comments


def candidate_urls(row):
    """Try safe same-host HTTPS of the original website, never a third-party."""
    parsed = urlsplit(row["website"])
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
            parsed.username or parsed.password or parsed.port):
        return []
    original_host = parsed.hostname.casefold()
    host = original_host
    alternatives = [row["website"]]
    upgraded = urlunsplit(("https", host, parsed.path, parsed.query, ""))
    root = urlunsplit(("https", host, "/", "", ""))
    for link in (upgraded, root):
        if link not in alternatives:
            alternatives.append(link)
    return alternatives[:3]


def capture_official(row):
    """Verifier repeats name, published address, activity and Dutch postcode checks.
    A transient failure stays blocked; this does not invent another address.
    """
    from verify_official_lead import CATEGORIES, verify_official_site
    from review450_strict import local_proof, term_match
    reverse = {}
    for category, (_, branch) in CATEGORIES.items():
        reverse.setdefault(branch, category)
    cat = reverse.get(row["branch"])
    if not cat:
        return [], "", "ONBEKENDE_BRANCHE"
    for site in candidate_urls(row):
        hint = {"name_hint":row["company"], "website_hint":site,
                "category_hint":cat,"country_hint":"NL"}
        cap = base.Capture()
        try:
            verified = verify_official_site(hint, session=cap)
            if not verified or not local_proof(cap.pages, hint):
                continue
            if (verified["email"].casefold() != row["email"].casefold() or
                    verified["branche_meervoud"] != row["branch"]):
                continue
            return cap.pages, site, "BRON_EN_ADRES_BEVESTIGD"
        except Exception:
            continue
        finally:
            cap.close()
    return [], "", "BRON_OF_ADRES_NIET_BEVESTIGD"


def evaluate(n, row, qa_row):
    """Returns only values destined for the private user's spreadsheet."""
    if str(n) != str(qa_row[0]) or row["draft_id"] != qa_row[1]:
        raise RuntimeError("qa_identity_mismatch")
    pages, source, status = capture_official(row)
    checked = base.now()
    if status != "BRON_EN_ADRES_BEVESTIGD":
        return [str(n),row["draft_id"],row["company"],row["email"],row["source_url"],
                row["website"],row["branch"],row["subject"],"","",
                "","",status,"0.0","Bestaand concept niet gewijzigd. Officiële website en zakelijk adres moeten opnieuw worden vastgesteld.",checked]
    if row["origin"] == "review50_reverified_v3" and qa_row[13] == "INHOUDELIJK_BIJNA_GOED_DETAILCHECK_NODIG":
        # Do not replace bespoke human-reviewed originals with templated copy.
        return [str(n),row["draft_id"],row["company"],row["email"],row["source_url"],
                row["website"],row["branch"],row["subject"],row["subject"],row["body"],
                "bestaande bedrijfsspecifieke tekst behouden",source,
                "BESTAANDE_STERKE_TEKST_BEHOUDEN",qa_row[4],
                "Persoonlijke claims uit bestaande mail vereisen nog detailcontrole door de eigenaar.",checked]
    features, level = topics_from_verified_pages(row, pages)
    subject, body, state, score, comment = rewrite(row, qa_row, features, level)
    return [str(n),row["draft_id"],row["company"],row["email"],row["source_url"],
            row["website"],row["branch"],row["subject"],subject,body,
            " + ".join(features),source,"BRON_EN_ADRES_BEVESTIGD;"+state,
            "%.1f" % score,comment,checked]
