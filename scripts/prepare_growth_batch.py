from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from pathlib import Path


FOCUS_PATTERNS = (
    ("fysiotherapie en revalidatie", "physical therapy and rehabilitation", r"fysio|fysiotherapie|revalidatie|physical therapy|rehabilitation|dry needling|rugcentrum"),
    ("fietsen en fietsservice", "bicycles and bike service", r"fiets|bike|tweewiel|giant store|rental & repair|fietsenwinkel"),
    ("bloemen, planten en cadeaus", "flowers, plants and gifts", r"\bbloemen(?:winkel|zaak)?\b|\bbloemist\b|flower|florist|boeket|tuincentrum"),
    ("auto's en mobiliteit", "cars and mobility", r"garage|auto|automotive|apk|carservice|car center|car service|autoservice|werkplaats|dealer|bmw|mazda|toyota|renault|nissan|mitsubishi"),
    ("tandzorg en mondzorg", "dental care", r"tand|dental|mondzorg|tandheel|orthodont"),
    ("optiek en oogzorg", "eyewear and eye care", r"optiek|opticien|bril|oog(?:zorg|kliniek|heelkund|arts|mode)|eyewear|contactlen|optometr"),
    ("fotografie en fotoapparatuur", "photography and camera retail", r"\bfoto(?:\s+|[-–])?(?:speciaalzaak|winkel|studio|grafie|camera(?:'s)?)\b|\bfotografie\b|\bfotograaf\b|\bcamera shop\b|\bphotograph(?:y|er)?\b"),
    ("sieraden en juwelierswerk", "jewellery and jewellery services", r"juwel|sieraad|diamant|edelsteen|goldsmith|goudsmid|jewelry|jeweler"),
    ("kinderopvang", "childcare", r"kinderopvang|kinderdag|bso|day care|kinderfort|kindergarden"),
    ("restaurant en gastvrijheid", "restaurant and hospitality", r"restaurant|à la carte|horeca|bistro|brasserie|pannenkoek|sushi|pizza|burger|grill(?:restaurant|room|bar)|steak(?:house)?|lunchroom|eetcaf|eetkamer|eethuis"),
    ("koffie, lunch en horeca", "coffee, lunch and hospitality", r"café|cafe|coffee|koffie|barista"),
    ("dagelijkse boodschappen en retail", "everyday groceries and retail", r"supermarkt|supermarket|boodschappen|grocery|groceries"),
    ("brood en banket", "bread and pastry", r"bakker|\bbrood\b|banket|patisserie|bakery"),
    ("slagerij en versproducten", "butchery and fresh food", r"slager|keurslager|butcher"),
    ("haar en beauty", "hair and beauty", r"kapsalon|kapper|coiffure|hair|haarmode|hairstyl|beauty|schoonheid"),
    ("dierenzorg", "animal care", r"dierenarts|dierenkliniek|veterin|kattenkliniek|paardenkliniek"),
    ("dieren en dierbenodigdheden", "pets and pet supplies", r"dierenwinkel|dierenspeciaalzaak|dierenbenodigdheden|pet shop|pet store|reptielen|aquarium"),
    ("hengelsport en visbenodigdheden", "angling and fishing supplies", r"\bhengelsport\b|\bhengel(?:s)?\b|fishing tackle|fishing gear|fishing supplies|vismateriaal|visaas"),
    ("sport en fitness", "sports and fitness", r"fitness|sportschool|sportcentrum|crossfit|gym|hockey|racket|pilates"),
    ("mode en kleding", "fashion and clothing", r"mode|kleding|fashion|boutique|herenmode|schoenen|lingerie|ondermode|lingeriezaak|suit store"),
    ("boeken, muziek en media", "books, music and media", r"boekhandel|bookstore|muziekhuis|music|read shop"),
    ("bedden en slaapcomfort", "beds and sleep comfort", r"boxspring|matras|slaapcomfort|beddenwinkel"),
    ("wonen en interieur", "home and interiors", r"interieur|\bwoon(?:winkel|boulevard|accessoire|decoratie|interieur|kamer|stijl|huis|beton)\w*|meubel|raamdecoratie|zonwering|vloerdecoratie"),
    ("wonen met zorg en ouderenzorg", "residential elder care", r"woonzorg|woonzorglocatie|ouderenzorg|nursing home|care home|elderly care"),
    ("loterijen en kansspelen", "lotteries and games of chance", r"staatsloten|staatsloterij|krasloten|loterij|lotter(?:y|ies)|kansspelen|gambling"),
    ("eten en delicatessen", "food and delicacies", r"delicatessen|wijn|wine|kaas|\bvis\b|\bvisspeciaalzaak\b|\bvishandel\b|\bviswinkel\b|\bvisboer\b|fishmonger|fish market|food|toko"),
    ("makelaardij en vastgoed", "real estate", r"\bmakelaar\b|\bmakelaardij\b|real estate|taxatie"),
    ("camping en recreatie", "camping and recreation", r"camping|kampeer|camper|caravan"),
    ("winkelen en retail", "shopping and retail", r"winkelcentrum|shopping mall"),
    ("tweedehands en hergebruik", "second-hand and reuse", r"kringloop|tweedehands"),
    ("apotheekzorg en gezondheid", "pharmacy and health", r"apotheek|pharmacy"),
)


EXPLICIT_BUSINESS_MARKER = re.compile(
    r"\bfiets(?:en)?\b|fietsenwinkel|fietsenmaker|bike shop|bicycle shop|"
    r"bloemenwinkel|bloemenzaak|bloemist|florist|flower shop|tuincentrum|"
    r"supermarkt|supermarket|grocery|groceries|boodschappen|"
    r"garage|autodealer|autobedrijf|auto service|autoservice|"
    r"tandarts|tandheel|dental|mondzorg|orthodont|"
    r"optiek|opticien|oogzorg|oogkliniek|oogheelkund|oogarts|oogmode|eyewear|contactlen|optometr|"
    r"foto\s+speciaalzaak|fotospeciaalzaak|fotowinkel|fotografie|fotograaf|camera shop|photograph|"
    r"juwelier|jeweler|jewelry|jewellery|goudsmid|goldsmith|"
    r"kinderopvang|kinderdag|day care|kindergarden|"
    r"restaurant|bistro|brasserie|café|cafe|lunchroom|eetcaf|eetkamer|steakhouse|"
    r"bakker|patisserie|banketbakker|slager|keurslager|butcher|"
    r"dierenarts|dierenkliniek|veterin|dierenwinkel|dierenspeciaalzaak|dierenbenodigdheden|pet shop|pet store|"
    r"sportschool|sportcentrum|fitness|gym|crossfit|hengelsport|"
    r"mode|kleding|fashion|lingerie|ondermode|"
    r"boekhandel|bookstore|muziekhuis|music shop|"
    r"visspeciaalzaak|vishandel|viswinkel|visboer|fishmonger|"
    r"woonzorg|ouderenzorg|nursing home|care home|elderly care|"
    r"staatslot|kraslot|loterij|lotter|kansspel|"
    r"makelaar|makelaardij|real estate|taxatie|apotheek|pharmacy",
    flags=re.IGNORECASE,
)


CATEGORY_FOCUS = {
    "restaurant": ("restaurant en gastvrijheid", "restaurant and hospitality"),
    "casual_eatery": ("eten en gastvrijheid", "food and hospitality"),
    "fast_food_restaurant": ("eten en gastvrijheid", "food and hospitality"),
    "cafe": ("koffie, lunch en horeca", "coffee, lunch and hospitality"),
    "coffee_shop": ("koffie, lunch en horeca", "coffee, lunch and hospitality"),
    "non_alcoholic_beverage_venue": ("dranken en horeca", "drinks and hospitality"),
    "hotel": ("overnachten en gastvrijheid", "accommodation and hospitality"),
    "food_and_beverage_store": ("eten, drinken en retail", "food, drinks and retail"),
    "convenience_store": ("dagelijkse boodschappen en retail", "everyday groceries and retail"),
    "supermarket": ("dagelijkse boodschappen en retail", "everyday groceries and retail"),
    "grocery_store": ("dagelijkse boodschappen en retail", "everyday groceries and retail"),
    "grocery_or_supermarket": ("dagelijkse boodschappen en retail", "everyday groceries and retail"),
    "warehouse_club_store": ("retail en boodschappen", "retail and groceries"),
    "fashion_and_apparel_store": ("mode en kleding", "fashion and clothing"),
    "personal_care_and_beauty_store": ("beauty en persoonlijke verzorging", "beauty and personal care"),
    "hardware_home_and_garden_store": ("wonen, klussen en tuin", "home, DIY and garden"),
    "home_service": ("diensten rond wonen en onderhoud", "home and maintenance services"),
    "gym": ("sport en fitness", "sports and fitness"),
    "sporting_goods_store": ("sport en sportartikelen", "sports and sporting goods"),
    "animal_or_pet_service": ("dierenzorg", "animal care"),
    "animal_and_pet_store": ("dieren en dierbenodigdheden", "pets and pet supplies"),
    "personal_or_beauty_service": ("haar en beauty", "hair and beauty"),
    "auto_dealer": ("auto's en mobiliteit", "cars and mobility"),
    "vehicle_dealer": ("voertuigen en mobiliteit", "vehicles and mobility"),
    "automotive_service": ("auto-onderhoud en mobiliteit", "car maintenance and mobility"),
    "vehicle_parts_store": ("auto-onderdelen en mobiliteit", "vehicle parts and mobility"),
    "dental_clinic": ("tandzorg en mondzorg", "dental care"),
    "physical_medicine_and_rehabilitation": ("fysiotherapie en revalidatie", "physical therapy and rehabilitation"),
    "primary_care_or_general_clinic": ("eerstelijnszorg", "primary care"),
    "medical_service": ("zorg en gezondheid", "healthcare"),
    "behavioral_or_mental_health_clinic": ("mentale gezondheid en begeleiding", "mental health and support"),
    "wellness_service": ("wellness en gezondheid", "wellness and health"),
    "pharmacy_and_drug_store": ("apotheekzorg en gezondheid", "pharmacy and health"),
    "flowers_and_gifts_store": ("bloemen, planten en cadeaus", "flowers, plants and gifts"),
    "books_music_and_video_store": ("boeken, muziek en media", "books, music and media"),
    "musical_instrument_and_pro_audio_store": ("muziek en instrumenten", "music and instruments"),
    "vision_or_eye_care_clinic": ("optiek en oogzorg", "eyewear and eye care"),
    "real_estate_service": ("makelaardij en vastgoed", "real estate"),
    "second_hand_store": ("tweedehands en hergebruik", "second-hand and reuse"),
    "shopping_mall": ("winkelen en retail", "shopping and retail"),
    "shopping": ("winkelen en retail", "shopping and retail"),
    "department_store": ("retail en warenhuis", "retail and department store"),
    "electronics_store": ("elektronica en retail", "electronics and retail"),
    "toys_and_games_store": ("speelgoed en spellen", "toys and games"),
    "office_supply_store": ("kantoorartikelen en retail", "office supplies and retail"),
    "arts_crafts_and_hobby_store": ("creatieve hobby en retail", "arts, crafts and retail"),
    "supplier_or_distributor": ("levering en distributie", "supply and distribution"),
    "family_service": ("dienstverlening voor gezinnen", "family services"),
    "legal_service": ("juridische dienstverlening", "legal services"),
    "high_school": ("onderwijs", "education"),
}

def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_lead_id(email: str, website: str) -> str:
    seed = f"{str(email or '').strip().casefold()}|{str(website or '').strip().casefold()}"
    return "growth-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


TRAILING_CONNECTORS = {"&", "and", "en", "van", "der", "den", "de", "het", "ter", "ten", "e", "of"}


def _strip_decorative_symbols(value: object) -> str:
    chars = []
    for ch in str(value or ""):
        category = unicodedata.category(ch)
        if category in {"So", "Cs"} or ch in {"\ufe0f", "\u200d"}:
            continue
        chars.append(ch)
    return re.sub(r"\s+", " ", "".join(chars)).strip()


def clean_company(value: object, language: str) -> str:
    text = _strip_decorative_symbols(value)
    return text or ("your company" if language == "en" else "jullie bedrijf")


def _base_company_name(company: str) -> str:
    text = clean_company(company, "nl")
    for separator in (" – ", " - ", " | ", " / "):
        if separator in text:
            text = text.split(separator, 1)[0].strip()
            break
    return text


def _trim_dangling_connectors(words: list[str]) -> list[str]:
    trimmed = list(words)
    while len(trimmed) > 1 and trimmed[-1].casefold().strip(".,") in TRAILING_CONNECTORS:
        trimmed.pop()
    return trimmed


def short_company_name(company: str) -> str:
    words = _base_company_name(company).split()
    if len(words) > 6:
        words = words[:6]
    words = _trim_dangling_connectors(words)
    return " ".join(words)


def subject_label_for_company(company: str, language: str) -> str:
    words = _base_company_name(company).split()
    prefix = "An idea for " if language == "en" else "Idee voor "
    max_label_words = 6 - len(prefix.split())
    if len(words) > max_label_words:
        words = words[:max_label_words]
    words = _trim_dangling_connectors(words)
    while len(words) > 1 and len(prefix + " ".join(words)) > 64:
        words = _trim_dangling_connectors(words[:-1])
    return " ".join(words) or ("your company" if language == "en" else "jullie bedrijf")


def subject_for_company(company: str, language: str) -> str:
    label = subject_label_for_company(company, language)
    return f"An idea for {label}" if language == "en" else f"Idee voor {label}"


def infer_focus_from_observation(
    observation: str,
    language: str,
    category_hint: str | None = None,
) -> str | None:
    haystack = str(observation or "").casefold()
    for nl, en, pattern in FOCUS_PATTERNS:
        if re.search(pattern, haystack, flags=re.IGNORECASE):
            return en if language == "en" else nl
    category = str(category_hint or "").strip().casefold()
    focus = CATEGORY_FOCUS.get(category)
    if focus:
        return focus[1] if language == "en" else focus[0]
    return None


def _word_set(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def observation_is_low_signal(company: str, observation: str) -> bool:
    text = re.sub(r"\s+", " ", str(observation or "")).strip()
    low = text.casefold()
    if not text:
        return True
    if re.search(r"\b\d+\s*%", text):
        return True
    if re.match(r"^(home|homepage|welkom|welcome)\b", low):
        return True
    if (
        re.match(
            r"^(contact(?:gegevens)?|contact us|openingstijden|opening hours|"
            r"route|adres|address|privacy|privacybeleid|vacatures?|jobs?|"
            r"werken bij|careers?)\b",
            low,
        )
        and len(_word_set(text)) <= 10
    ):
        return True
    if re.match(
        r"^(actie|sale|nu |tijdelijk|deze week|special offer|limited offer)\b",
        low,
    ):
        return True
    if low in {"gelieve te wachten", "mysite", "wij zijn verhuisd..", "wij zijn verhuisd", "wie zijn wij?", "wie zijn wij", "🔒 beveiligde website", "beveiligde website", "staff member carousel"}:
        return True
    if re.search(r"reserved domain|under construction|coming soon|domainorder|geparkeerd|crypto casino|bitcoin casino|tempat main|window \d+|without code", low):
        return True
    company_words = _word_set(company)
    observation_words = _word_set(text)
    if company_words and observation_words:
        extra = observation_words - company_words
        if len(extra) <= 1 and len(observation_words) <= len(company_words) + 1:
            return True
    return False


def build_opening(
    company: str,
    language: str,
    observation: str,
    category_hint: str | None = None,
) -> str:
    company_label = short_company_name(company)
    observed = re.sub(r"\s+", " ", str(observation or "")).strip()
    low_signal = observation_is_low_signal(company, observed)
    low = observed.casefold()
    boilerplate_heading = bool(
        re.match(r"^(home|homepage|welkom|welcome)\b", observed, flags=re.IGNORECASE)
    )
    placeholder_observation = low in {
        "gelieve te wachten",
        "mysite",
        "wij zijn verhuisd..",
        "wij zijn verhuisd",
        "wie zijn wij?",
        "wie zijn wij",
        "🔒 beveiligde website",
        "beveiligde website",
        "staff member carousel",
    } or bool(
        re.search(
            r"reserved domain|under construction|coming soon|domainorder|geparkeerd|"
            r"crypto casino|bitcoin casino|tempat main|window \d+|without code",
            low,
        )
    )
    weak_observation = bool(re.search(r"\b\d+\s*%", observed))

    if (
        observed
        and len(_word_set(observed)) >= 3
        and not boilerplate_heading
        and not placeholder_observation
        and not weak_observation
        and not low_signal
    ):
        punctuation = "" if observed.endswith((".", "!", "?")) else "."
        if language == "en":
            return f"What stood out to me on your website: {observed}{punctuation}"
        return f"Wat me opviel op jullie website: {observed}{punctuation}"

    # Never turn a weak page title, company name or discovery category into
    # a prospect claim. A first touch requires one specific verified fact from
    # the official site; otherwise content research must continue.
    _ = category_hint
    _ = company_label
    _ = low_signal
    raise ValueError(
        "No specific verified site detail for outreach opening"
    )


def naturalize_existing_opening(opening: str, language: str) -> str:
    text = re.sub(r"\s+", " ", str(opening or "")).strip()
    if language == "en":
        match = re.fullmatch(
            r'I noticed this on your website:\s*[“"](.+?)[”"]\.?',
            text,
            flags=re.IGNORECASE,
        )
        if match:
            observed = match.group(1).strip()
            punctuation = "" if observed.endswith((".", "!", "?")) else "."
            return f"What stood out to me on your website: {observed}{punctuation}"
        return text

    match = re.fullmatch(
        r'Op jullie site viel me op:\s*[“"](.+?)[”"]\.?',
        text,
        flags=re.IGNORECASE,
    )
    if match:
        observed = match.group(1).strip()
        punctuation = "" if observed.endswith((".", "!", "?")) else "."
        return f"Wat me opviel op jullie website: {observed}{punctuation}"
    return text


def exact_nl_opening_from_existing(opening: str, company: str | None = None) -> str:
    text = re.sub(r"\s+", " ", str(opening or "")).strip()
    if not text:
        raise ValueError("unsupported existing Dutch verified opening")

    direct = re.fullmatch(
        r"Ik zag op jullie website dat\s+(.+)",
        text,
        flags=re.IGNORECASE,
    )
    if direct:
        fact = direct.group(1).strip()
        fact = re.split(r"\s+(?:Ik heb een idee|Mijn idee voor)\b", fact, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        fact = re.sub(r"[.!?]+$", "", fact).strip()
        if fact:
            return f"Ik zag op jullie website dat {fact}."

    quoted_patterns = (
        r'Op jullie site viel me op:\s*[“"](.+?)[”"]',
        r'Op jullie website zag ik\s*[“"](.+?)[”"]',
        r'Op jullie website staat\s*[“"](.+?)[”"]',
        r'Ik heb de website van .+? bekeken en zag\s*[“"](.+?)[”"]',
        r'Eén detail dat opviel was\s*[“"](.+?)[”"]',
    )
    for pattern in quoted_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            fact = re.sub(r"[.!?]+$", "", match.group(1).strip()).strip()
            if fact:
                return f"Ik zag op jullie website dat {fact}."

    stood_out = re.fullmatch(
        r"Wat me opviel op jullie website:\s*(.+)",
        text,
        flags=re.IGNORECASE,
    )
    if stood_out:
        fact = stood_out.group(1).strip()
        fact = re.split(r"\s+(?:Ik heb een idee|Mijn idee voor)\b", fact, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        fact = re.sub(r"[.!?]+$", "", fact).strip()
        if fact:
            return f"Ik zag op jullie website dat {fact}."

    focus = re.match(
        r"Ik zag dat\s+(.+?)(?:\.\s+(?:Ik heb een idee|Mijn idee voor)\b|[.!?]*$)",
        text,
        flags=re.IGNORECASE,
    )
    if focus:
        fact = re.sub(r"[.!?]+$", "", focus.group(1).strip()).strip()
        if fact:
            return f"Ik zag op jullie website dat {fact}."

    site_focus = re.search(
        r"Jullie site draait duidelijk om\s+(.+?)(?:\.\s+Mijn idee voor|[.!?]*$)",
        text,
        flags=re.IGNORECASE,
    )
    if site_focus and company:
        focus_text = re.sub(r"[.!?]+$", "", site_focus.group(1).strip()).strip()
        company_label = short_company_name(company)
        if focus_text and company_label:
            return f"Ik zag op jullie website dat {company_label} zich richt op {focus_text}."

    raise ValueError("unsupported existing Dutch verified opening")


def _copy_variant_index(key: str, count: int) -> int:
    if count <= 0:
        raise ValueError("count must be positive")
    digest = hashlib.sha256(str(key).encode("utf-8")).digest()
    return digest[0] % count


def build_template_from_opening(
    company: str,
    language: str,
    opening: str,
    *,
    price_min: int,
    price_max: int,
    variant_key: str | None = None,
) -> str:
    company_label = short_company_name(company)
    clean_opening = naturalize_existing_opening(opening, language)
    if not clean_opening:
        raise ValueError("opening is required")
    if language == "nl":
        clean_opening = exact_nl_opening_from_existing(clean_opening, company_label)

    # Keep variant_key for API compatibility; copy is intentionally fixed so
    # every Growth draft follows the same reviewed structure. Only verified
    # site context, language and company label may vary.
    _ = variant_key

    if language == "en":
        return (
            "Hello,\n\n"
            f"{clean_opening}\n\n"
            "My Growth Subscription covers several parts of your online presence:\n\n"
            "• Website/webshop — improve or build new where needed\n"
            "• Search visibility — improve findability\n"
            "• Social content — relevant content\n"
            "• Automation — partially automate suitable processes where feasible\n"
            "• Hosting — manage or take over where appropriate\n"
            "• Me as your fixed point of contact\n\n"
            f"€{price_min}–€{price_max} per month, depending on what you need.\n\n"
            f"Would you like me to make a no-obligation example design for {company_label}, "
            "so you can first see whether the direction is relevant?\n\n"
            "Not interested? Just let me know.\n\n"
            "Regards,\nAndrew"
        )

    return (
        "Hallo,\n\n"
        f"{clean_opening}\n\n"
        "Met mijn Groeiabonnement kan ik meerdere onderdelen van jullie online aanpak oppakken:\n\n"
        "• Website/webshop — verbeteren of nieuw maken waar nodig\n"
        "• Zoekbaarheid — beter vindbaar worden\n"
        "• Social content — passende content\n"
        "• Automatisering — geschikte processen deels automatiseren waar haalbaar\n"
        "• Hosting — beheren of overnemen waar passend\n"
        "• Ik als vast contactpersoon\n\n"
        f"€{price_min}–€{price_max} per maand, afhankelijk van wat jullie nodig hebben.\n\n"
        f"Zal ik vrijblijvend een voorbeeld design maken voor {company_label}? "
        "Dan kunnen jullie eerst bekijken of de richting interessant is.\n\n"
        "Geen interesse? Laat het gerust weten.\n\n"
        "Groet,\nAndrew"
    )

def build_template(
    company: str,
    language: str,
    observation: str,
    *,
    price_min: int,
    price_max: int,
    category_hint: str | None = None,
) -> str:
    opening = build_opening(company, language, observation, category_hint)
    return build_template_from_opening(
        company,
        language,
        opening,
        price_min=price_min,
        price_max=price_max,
    )


def prepare_batch(contacts_payload: dict, config: dict, *, draft_limit: int = 1) -> dict:
    if not 1 <= draft_limit <= 100:
        raise ValueError("draft_limit must be 1-100")
    price = config["monthly_price_eur"]
    price_min, price_max = int(price["min"]), int(price["max"])
    rows = []
    selected = 0

    for candidate in contacts_payload.get("candidates") or []:
        language = str(candidate.get("language") or "nl").casefold()
        if language not in {"nl", "en"}:
            language = "nl"
        company = clean_company(candidate.get("name_hint"), language)
        emails = candidate.get("public_business_emails") or []
        excluded = bool(candidate.get("excluded_competitor"))
        observation = str(candidate.get("verified_observation") or "").strip()
        observation_source_url = str(candidate.get("verified_observation_source_url") or "").strip()
        observation_source_type = str(candidate.get("verified_observation_source_type") or "").strip()
        category_hint = str(candidate.get("category_hint") or "").strip() or None
        has_verified_observation = bool(
            observation
            and observation_source_url
            and observation_source_type == "official_site"
        )
        preview = (
            build_template(
                company,
                language,
                observation,
                price_min=price_min,
                price_max=price_max,
                category_hint=category_hint,
            )
            if has_verified_observation
            else None
        )
        subject_preview = subject_for_company(company, language) if has_verified_observation else None
        basis = str(candidate.get("contact_basis_status") or "unverified")
        base = {
            "lead_id": None,
            "company": candidate.get("name_hint"),
            "copy_company_label": short_company_name(company),
            "copy_subject_label": subject_label_for_company(company, language),
            "website": candidate.get("website_hint"),
            "official_domain_hint": candidate.get("official_domain_hint"),
            "product_id": "growth_subscription",
            "language": language,
            "language_source": candidate.get("language_source"),
            "category_hint": category_hint,
            "monthly_price_min_eur": price_min,
            "monthly_price_max_eur": price_max,
            "excluded_competitor": excluded,
            "exclusion_reason": candidate.get("exclusion_reason"),
            "contact_basis_status": basis,
            "contact_basis_hint": candidate.get("contact_basis_hint"),
            "email_source_urls": candidate.get("email_source_urls") or [],
            "email_source_types": candidate.get("email_source_types") or [],
            "email_source_refs": candidate.get("email_source_refs") or [],
            "verified_observation": observation or None,
            "verified_observation_source_url": observation_source_url or None,
            "verified_observation_source_type": observation_source_type or None,
            "status": "excluded_competitor" if excluded else "no_public_email",
            "email": None,
            "subject": None,
            "body": None,
            "subject_preview": None if excluded else subject_preview,
            "concept_preview": None if excluded else preview,
        }
        if excluded:
            rows.append(base)
            continue
        if emails:
            base["email"] = emails[0]
            base["lead_id"] = stable_lead_id(base["email"], base["website"])
            if not has_verified_observation:
                base["status"] = "blocked_missing_verified_observation"
            elif selected < draft_limit:
                selected += 1
                base["status"] = "draft_ready" if basis == "pass" else "review_draft"
                base["subject"] = subject_preview
                base["body"] = preview
            else:
                base["status"] = "email_found_not_selected"
        rows.append(base)

    return {
        "schema_version": "webactueel-growth-batch/4.2",
        "product": config,
        "row_count": len(rows),
        "excluded_competitor_count": sum(1 for row in rows if row["status"] == "excluded_competitor"),
        "email_found_count": sum(1 for row in rows if row["email"]),
        "draft_candidate_count": sum(1 for row in rows if row["status"] in {"draft_ready", "review_draft"}),
        "review_draft_count": sum(1 for row in rows if row["status"] == "review_draft"),
        "rows": rows,
        "safety": {
            "one_product": True,
            "six_benefits": True,
            "language_matched_copy": True,
            "verified_official_site_observation_required": True,
            "personalized_company_opening": True,
            "contact_basis_review_required_before_send": True,
            "review_draft_storage_allowed": True,
            "automatic_send": False,
        },
    }


def write_csv(payload: dict, path: Path) -> None:
    fields = [
        "lead_id", "company", "website", "email", "language", "status",
        "excluded_competitor", "exclusion_reason", "contact_basis_status",
        "contact_basis_hint", "email_source_types", "product_id",
        "verified_observation", "verified_observation_source_url", "verified_observation_source_type",
        "monthly_price_min_eur", "monthly_price_max_eur",
        "subject_preview", "concept_preview",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in payload["rows"]:
            writer.writerow({field: row.get(field) for field in fields})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contacts", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--draft-limit", type=int, default=1)
    args = parser.parse_args()
    result = prepare_batch(
        load_json(Path(args.contacts)),
        load_json(Path(args.config)),
        draft_limit=args.draft_limit,
    )
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_csv(result, Path(args.output_csv))
    print(
        "GROWTH_BATCH=green "
        f"rows={result['row_count']} emails={result['email_found_count']} "
        f"excluded_competitors={result['excluded_competitor_count']} "
        f"draft_candidates={result['draft_candidate_count']} email_send=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
