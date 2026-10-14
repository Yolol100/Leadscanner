"""Webactueel local-business target profile.

The profile intentionally favors local physical trades and appointment/service
businesses. It excludes digital agencies, consultancy and other poor-fit sectors.
No prospect data lives here.
"""
import re
import unicodedata

PROFILE_KEYWORDS = {
    "vakbedrijven",
    "lokale vakbedrijven",
    "lokale bedrijven",
    "normale lokale bedrijven",
    "local trades",
}

# User-facing Dutch search terms that fit the Webactueel ICP. Keep this broad but
# practical: a local customer can normally book, visit, request a quote or call
# the business for a concrete physical/local service.
ALLOWED_REQUEST_KEYWORDS = {
    # Bouw, installatie en woning
    "aannemer","bouwbedrijf","verbouwbedrijf","renovatiebedrijf","timmerbedrijf","timmerman",
    "metselaar","stukadoor","schilder","glaszetter","dakdekker","rietdekker","tegelzetter",
    "vloerenlegger","vloerbedrijf","parketteur","loodgieter","installatiebedrijf","elektricien",
    "zonnepaneleninstallateur","zonnepanelen","warmtepompinstallateur","warmtepomp","cv-installateur",
    "verwarming","airco-installateur","airco","klimaatinstallatie","isolatiebedrijf","isolatie",
    "sanitairinstallateur","badkamerinstallateur","keukeninstallateur","kozijnenbedrijf","kozijnen",
    "ramen en deuren","zonwering","rolluiken","garagedeuren","slotenmaker","beveiligingsinstallateur",
    "brandbeveiliging","schoorsteenveger","voeger","gevelrenovatie","gevelreiniging",
    "vochtbestrijding","kelderdichting","fundering","betonreparatie","sloopbedrijf","grondwerker",
    "graafbedrijf","stratenmaker","bestrating","riolering","ontstoppingsbedrijf","drainage",
    "bronbemaling","steigerbouw","staalbouw","hekwerk","schutting","serrebouw","verandabouw",
    # Tuin en buiten
    "hovenier","tuinman","tuinonderhoud","tuinaanleg","boomverzorging","boomverzorger","arborist",
    "boomkap","gazononderhoud","vijverbouw","zwembadbouwer","zwembadonderhoud","beregening",
    # Reiniging en gebouwservice
    "schoonmaakbedrijf","schoonmaker","glazenwasser","tapijtreiniging","meubelreiniging",
    "dakgootreiniging","industriële reiniging","ongediertebestrijding","ongediertebestrijder",
    # Auto, motor en fiets
    "garage","autogarage","autoservice","automonteur","apk","bandenservice","bandenbedrijf",
    "autoschade","schadeherstel","carrosserie","autospuiterij","deukherstel","autoruit",
    "sleepdienst","pechhulp","autodetailing","detailing","carwash","autowasstraat",
    "motorreparatie","motorfietsreparatie","scooterreparatie","fietsenmaker","fietsreparatie",
    "fietsenwinkel","camperreparatie","caravanreparatie",
    # Reparatie en ambacht
    "witgoedreparatie","apparatenreparatie","elektronicareparatie","meubelreparatie",
    "meubelstoffeerder","stoffeerder","schoenmaker","horlogemaker","juwelier","kleermaker",
    "naaiatelier","wasserij","stomerij",
    # Persoonlijke verzorging
    "kapsalon","kapper","barbier","barber","schoonheidssalon","beautysalon","nagelsalon",
    "pedicure","massage","massagesalon","tattooshop","tattoo","piercing","wellness","sauna",
    # Horeca en verblijf
    "restaurant","eetcafé","café","lunchroom","snackbar","cafetaria","ijssalon","catering",
    "cateraar","foodtruck","bakkerij","bakker","slagerij","slager","delicatessen","hotel",
    "pension","bed and breakfast","b&b","vakantieverblijf","camping",
    # Lokale winkels/showrooms
    "bloemist","tuincentrum","opticien","audicien","keukenwinkel","badkamerwinkel","tegelwinkel",
    "vloerwinkel","meubelwinkel","fietswinkel","autodealer","motorzaak",
    # Lokale diensten, sport en opleiding
    "verhuisbedrijf","verhuizer","koerier","rijschool","autorijschool","motorrijschool",
    "sportschool","fitness","fitnesscentrum","yoga","pilates","vechtsportschool","dansschool",
    "zwemschool","personal trainer","fotograaf","dierenarts","hondentrimsalon","trimsalon",
    "dierenpension","hondenpension","kinderopvang","makelaar","tandarts","fysiotherapie",
    "fysiotherapeut","chiropractor","osteopaat","podotherapeut",
}

# Overture taxonomy/name terms used when the macro "vakbedrijven" is requested.
# These are intentionally service/location oriented, not generic business sectors.
PROFILE_CATEGORY_TERMS = tuple(sorted({
    "general contractor","construction company","builder","carpenter","masonry contractor",
    "plumber","electrician","solar energy contractor","solar installer","hvac contractor",
    "heating contractor","air conditioning contractor","insulation contractor","plasterer",
    "tile contractor","flooring contractor","painter","glass service","glazier","roofing contractor",
    "demolition contractor","excavation contractor","paving contractor","drainage service",
    "sewer service","scaffolding service","fence contractor","locksmith","security system installer",
    "fire protection service","chimney sweep","garage door service","window installation service",
    "kitchen remodeler","bathroom remodeler","waterproofing service","foundation repair service",
    "landscaper","gardener","lawn care service","tree service","arborist","irrigation service",
    "swimming pool contractor","pool cleaning service","house cleaning service","cleaning service",
    "window cleaning service","carpet cleaning service","pest control service",
    "auto repair","car repair","vehicle repair","auto mechanic","mechanic","tire shop",
    "auto body shop","body shop","auto glass shop","towing service","car detailing service",
    "car wash","motorcycle repair","scooter repair","bicycle repair","bike repair","bicycle store",
    "appliance repair service","electronics repair shop","furniture repair shop","upholstery shop",
    "shoe repair shop","watch repair service","jewelry repair service","tailor","laundromat",
    "dry cleaner","hair salon","hairdresser","barber shop","beauty salon","beautician","nail salon",
    "pedicure","massage therapist","massage spa","tattoo shop","piercing shop","spa","sauna",
    "restaurant","eatery","cafe","coffee shop","lunch restaurant","fast food restaurant",
    "ice cream shop","caterer","food truck","bakery","butcher","deli","hotel","bed and breakfast",
    "guest house","campground","florist","flower shop","garden center","optician","optometrist",
    "hearing aid store","kitchen supply store","bathroom supply store","tile store","flooring store",
    "furniture store","car dealer","motorcycle dealer","moving company","courier service",
    "driving school","gym","fitness center","fitness centre","yoga studio","pilates studio",
    "martial arts school","dance school","swimming school","personal trainer","photographer",
    "veterinarian","veterinary clinic","animal hospital","pet groomer","kennel","pet boarding service",
    "childcare","daycare","nursery","real estate agent","real estate agency","dentist",
    "dental clinic","dental practice","physical therapy","physical therapist","physiotherapy",
    "physiotherapist","chiropractor","osteopath","podiatrist",
}))

REQUEST_CATEGORY_ALIASES = {
    "aannemer": ("general contractor","builder"), "bouwbedrijf": ("construction company","general contractor"),
    "verbouwbedrijf": ("general contractor","home improvement"), "renovatiebedrijf": ("general contractor","home improvement"),
    "timmerbedrijf": ("carpenter",), "timmerman": ("carpenter",), "metselaar": ("masonry contractor",),
    "stukadoor": ("plasterer",), "schilder": ("painter",), "glaszetter": ("glass service","glazier"),
    "dakdekker": ("roofing contractor",), "tegelzetter": ("tile contractor",),
    "vloerenlegger": ("flooring contractor",), "vloerbedrijf": ("flooring contractor",), "parketteur": ("flooring contractor",),
    "loodgieter": ("plumber",), "installatiebedrijf": ("plumber","electrician","hvac contractor"),
    "elektricien": ("electrician",), "zonnepaneleninstallateur": ("solar installer","solar energy contractor"),
    "zonnepanelen": ("solar installer","solar energy contractor"), "warmtepompinstallateur": ("hvac contractor","heating contractor"),
    "warmtepomp": ("hvac contractor","heating contractor"), "cv-installateur": ("heating contractor","hvac contractor"),
    "verwarming": ("heating contractor",), "airco-installateur": ("air conditioning contractor","hvac contractor"),
    "airco": ("air conditioning contractor","hvac contractor"), "klimaatinstallatie": ("hvac contractor",),
    "isolatiebedrijf": ("insulation contractor",), "isolatie": ("insulation contractor",),
    "slotenmaker": ("locksmith",), "beveiligingsinstallateur": ("security system installer",),
    "brandbeveiliging": ("fire protection service",), "schoorsteenveger": ("chimney sweep",),
    "sloopbedrijf": ("demolition contractor",), "grondwerker": ("excavation contractor",),
    "graafbedrijf": ("excavation contractor",), "stratenmaker": ("paving contractor",),
    "bestrating": ("paving contractor",), "riolering": ("sewer service","drainage service"),
    "ontstoppingsbedrijf": ("sewer service","drainage service"), "drainage": ("drainage service",),
    "hekwerk": ("fence contractor",), "schutting": ("fence contractor",),
    "hovenier": ("landscaper","gardener"), "tuinman": ("gardener",), "tuinonderhoud": ("landscaper","lawn care service"),
    "tuinaanleg": ("landscaper",), "boomverzorging": ("tree service","arborist"), "boomverzorger": ("tree service","arborist"),
    "arborist": ("arborist","tree service"), "zwembadbouwer": ("swimming pool contractor",),
    "zwembadonderhoud": ("pool cleaning service",), "schoonmaakbedrijf": ("cleaning service","house cleaning service"),
    "schoonmaker": ("cleaning service","house cleaning service"), "glazenwasser": ("window cleaning service",),
    "tapijtreiniging": ("carpet cleaning service",), "ongediertebestrijding": ("pest control service",),
    "ongediertebestrijder": ("pest control service",), "garage": ("auto repair","car repair","vehicle repair"),
    "autogarage": ("auto repair","car repair"), "autoservice": ("auto repair","car repair"), "automonteur": ("auto mechanic","mechanic"),
    "apk": ("auto repair",), "bandenservice": ("tire shop",), "bandenbedrijf": ("tire shop",),
    "autoschade": ("auto body shop","body shop"), "schadeherstel": ("auto body shop","body shop"),
    "carrosserie": ("auto body shop","body shop"), "autoruit": ("auto glass shop",), "sleepdienst": ("towing service",),
    "pechhulp": ("towing service",), "autodetailing": ("car detailing service",), "detailing": ("car detailing service",),
    "carwash": ("car wash",), "autowasstraat": ("car wash",), "motorreparatie": ("motorcycle repair",),
    "motorfietsreparatie": ("motorcycle repair",), "scooterreparatie": ("scooter repair","motorcycle repair"),
    "fietsenmaker": ("bicycle repair","bike repair"), "fietsreparatie": ("bicycle repair","bike repair"),
    "fietsenwinkel": ("bicycle store","bicycle repair"), "witgoedreparatie": ("appliance repair service",),
    "apparatenreparatie": ("appliance repair service",), "elektronicareparatie": ("electronics repair shop",),
    "meubelreparatie": ("furniture repair shop",), "meubelstoffeerder": ("upholstery shop",), "stoffeerder": ("upholstery shop",),
    "schoenmaker": ("shoe repair shop",), "horlogemaker": ("watch repair service",), "kleermaker": ("tailor",),
    "naaiatelier": ("tailor",), "wasserij": ("laundromat",), "stomerij": ("dry cleaner",),
    "kapsalon": ("hair salon","hairdresser"), "kapper": ("hair salon","hairdresser"), "barbier": ("barber shop",),
    "barber": ("barber shop",), "schoonheidssalon": ("beauty salon","beautician"), "beautysalon": ("beauty salon","beautician"),
    "nagelsalon": ("nail salon",), "pedicure": ("pedicure",), "massage": ("massage therapist","massage spa"),
    "massagesalon": ("massage spa","massage therapist"), "tattooshop": ("tattoo shop",), "tattoo": ("tattoo shop",),
    "piercing": ("piercing shop",), "wellness": ("spa",), "sauna": ("sauna","spa"),
    "restaurant": ("restaurant","eatery"), "eetcafé": ("restaurant","cafe"), "café": ("cafe","coffee shop"),
    "lunchroom": ("cafe","lunch restaurant"), "snackbar": ("fast food restaurant",), "cafetaria": ("fast food restaurant",),
    "ijssalon": ("ice cream shop",), "catering": ("caterer",), "cateraar": ("caterer",), "foodtruck": ("food truck",),
    "bakkerij": ("bakery",), "bakker": ("bakery",), "slagerij": ("butcher",), "slager": ("butcher",),
    "hotel": ("hotel",), "pension": ("guest house","hotel"), "bed and breakfast": ("bed and breakfast",),
    "b&b": ("bed and breakfast",), "camping": ("campground",), "bloemist": ("florist","flower shop"),
    "tuincentrum": ("garden center",), "opticien": ("optician","optometrist"), "audicien": ("hearing aid store",),
    "keukenwinkel": ("kitchen supply store",), "badkamerwinkel": ("bathroom supply store",), "tegelwinkel": ("tile store",),
    "vloerwinkel": ("flooring store",), "meubelwinkel": ("furniture store",), "autodealer": ("car dealer",),
    "motorzaak": ("motorcycle dealer",), "verhuisbedrijf": ("moving company",), "verhuizer": ("moving company",),
    "koerier": ("courier service",), "rijschool": ("driving school",), "autorijschool": ("driving school",),
    "motorrijschool": ("driving school",), "sportschool": ("gym","fitness center"), "fitness": ("fitness center","gym"),
    "fitnesscentrum": ("fitness center","gym"), "yoga": ("yoga studio",), "pilates": ("pilates studio",),
    "vechtsportschool": ("martial arts school",), "dansschool": ("dance school",), "zwemschool": ("swimming school",),
    "personal trainer": ("personal trainer",), "fotograaf": ("photographer",), "dierenarts": ("veterinarian","veterinary clinic"),
    "hondentrimsalon": ("pet groomer",), "trimsalon": ("pet groomer",), "dierenpension": ("pet boarding service","kennel"),
    "hondenpension": ("pet boarding service","kennel"), "kinderopvang": ("childcare","daycare","nursery"),
    "makelaar": ("real estate agent","real estate agency"), "tandarts": ("dentist","dental clinic"),
    "fysiotherapie": ("physical therapy","physiotherapy"), "fysiotherapeut": ("physical therapist","physiotherapist"),
    "chiropractor": ("chiropractor",), "osteopaat": ("osteopath",), "podotherapeut": ("podiatrist",),
}


def requested_category_terms(keyword: str) -> tuple[str, ...]:
    return tuple(normalize(x) for x in REQUEST_CATEGORY_ALIASES.get(normalize(keyword), ()))


# Explicit poor-fit sectors. These are blocked even if a name contains a positive
# trade word. Phrases are deliberately specific to avoid blocking normal words.
BLOCKED_PHRASES = tuple(sorted({
    # Marketing/digital/media
    "marketing agency","marketingbureau","online marketing","digital marketing","growth agency",
    "seo agency","seo bureau","sea bureau","web agency","webbureau","web design","webdesign",
    "web development","website builder","websitebouwer","advertising agency","reclamebureau",
    "branding agency","creative agency","digital agency","social media agency","content agency",
    "pr agency","public relations","communicatiebureau","communication agency","lead generation",
    "telemarketing","market research","marktonderzoek",
    # IT/software/automation
    "software company","softwarebedrijf","software development","app developer","app development",
    "it consultancy","it consultant","ict bedrijf","ict consultancy","managed service provider",
    "web hosting","hosting provider","saas","cloud consultancy","cybersecurity","data consultancy",
    "automation agency","automatiseringsbureau","ai agency","ai bureau",
    # Advies/professionele zakelijke diensten
    "business consultant","management consultant","management consultancy","organisatieadvies",
    "strategy consultant","sales consultant","marketing consultant","coach","coaching",
    "accountant","accountancy","boekhouder","boekhoudkantoor","belastingadviseur","tax advisor",
    "law firm","advocatenkantoor","advocaat","notaris","legal consultancy","juridisch advies",
    "recruitment agency","recruiter","uitzendbureau","staffing agency","hr consultancy",
    "insurance broker","verzekeringsadviseur","financial advisor","financieel adviseur",
    "investment company","vermogensbeheer","call center","callcenter",
    # Niet-lokaal/online/intermediair
    "wholesale","groothandel","import export","dropshipping","dropship","marketplace",
    "online store","online-only","e-commerce agency","ecommerce agency","business broker",
    "bemiddelingsbureau",
    # Institutioneel / overheid / gevoelige sectoren
    "government office","municipality","gemeentehuis","university","universiteit","hospital",
    "ziekenhuis","nursing home","verpleeghuis","political organization","religious organization",
    "charity organization","casino","gambling","adult entertainment","vape shop","cannabis store",
    "gun store",
}))


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9&+]+", " ", text.casefold()).strip()


def _contains_phrase(haystack: str, phrase: str) -> bool:
    return f" {normalize(phrase)} " in f" {haystack} "


def is_profile_keyword(keyword: str) -> bool:
    return normalize(keyword) in {normalize(x) for x in PROFILE_KEYWORDS}


def is_allowed_requested_keyword(keyword: str) -> bool:
    n = normalize(keyword)
    if n in {normalize(x) for x in PROFILE_KEYWORDS}:
        return True
    return n in {normalize(x) for x in ALLOWED_REQUEST_KEYWORDS}


def validate_requested_keywords(keywords: list[str]) -> list[str]:
    if not keywords:
        raise ValueError("target_keywords_required")
    for keyword in keywords:
        n = normalize(keyword)
        if any(_contains_phrase(n, item) for item in BLOCKED_PHRASES):
            raise ValueError("blocked_target_keyword")
        if not is_allowed_requested_keyword(keyword):
            raise ValueError("unsupported_target_keyword")
    return keywords


def profile_category_terms() -> tuple[str, ...]:
    return tuple(normalize(x) for x in PROFILE_CATEGORY_TERMS)


def is_blocked_place(*values: object) -> bool:
    haystack = normalize(" ".join(str(v or "") for v in values))
    return any(_contains_phrase(haystack, item) for item in BLOCKED_PHRASES)
