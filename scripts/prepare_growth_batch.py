from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path


FOCUS_PATTERNS = (
    ("fysiotherapie", "physical therapy", r"fysio|fysiotherapie|revalidatie|dry needling"),
    ("fietsen en fietsservice", "bicycles and bike service", r"fiets|bike|tweewiel|giant store|rental & repair"),
    ("bloemen en planten", "flowers and plants", r"bloem|flower|florist|boeket"),
    ("auto-onderhoud en reparatie", "car maintenance and repair", r"garage|auto|automotive|apk|carservice|car center|car service|autoservice|werkplaats"),
    ("tandzorg en mondzorg", "dental care", r"tand|dental|mondzorg|tandheel"),
    ("optiek en oogzorg", "eyewear and eye care", r"optiek|opticien|bril|oog|eyewear|contactlen|optometr"),
    ("sieraden en juwelierswerk", "jewellery and jewellery services", r"juwel|sieraad|goud|diamant|edelsteen|goldsmith|goudsmid|jewelry|jeweler"),
    ("kinderopvang", "childcare", r"kinderopvang|kinderdag|bso|day care|kinderfort|kindergarden|kinder"),
    ("restaurant en gastvrijheid", "restaurant and hospitality", r"restaurant|à la carte|horeca"),
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_lead_id(email: str, website: str) -> str:
    seed = f"{str(email or '').strip().casefold()}|{str(website or '').strip().casefold()}"
    return "growth-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def clean_company(value: object, language: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text or ("your company" if language == "en" else "jullie bedrijf")


def short_company_name(company: str) -> str:
    text = re.sub(r"\s+", " ", str(company or "")).strip()
    for separator in (" – ", " - ", " | ", " / "):
        if separator in text:
            text = text.split(separator, 1)[0].strip()
            break
    words = text.split()
    if len(words) > 4:
        text = " ".join(words[:4])
    return text


def subject_label_for_company(company: str, language: str) -> str:
    words = short_company_name(company).split()
    prefix = "An idea for " if language == "en" else "Idee voor "
    while len(words) > 1 and (len(prefix + " ".join(words)) > 56 or len((prefix + " ".join(words)).split()) > 7):
        words.pop()
    return " ".join(words) or ("your company" if language == "en" else "jullie bedrijf")


def subject_for_company(company: str, language: str) -> str:
    label = subject_label_for_company(company, language)
    return f"An idea for {label}" if language == "en" else f"Idee voor {label}"


def infer_focus_from_observation(observation: str, language: str) -> str | None:
    haystack = str(observation or "").casefold()
    for nl, en, pattern in FOCUS_PATTERNS:
        if re.search(pattern, haystack, flags=re.IGNORECASE):
            return en if language == "en" else nl
    return None


def _word_set(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def observation_is_low_signal(company: str, observation: str) -> bool:
    text = re.sub(r"\s+", " ", str(observation or "")).strip()
    low = text.casefold()
    if not text:
        return True
    if re.match(r"^(home|homepage|welkom|welcome)\b", low):
        return True
    if low in {"gelieve te wachten", "mysite", "wij zijn verhuisd..", "wij zijn verhuisd"}:
        return True
    company_words = _word_set(company)
    observation_words = _word_set(text)
    if company_words and observation_words:
        extra = observation_words - company_words
        if len(extra) <= 1 and len(observation_words) <= len(company_words) + 1:
            return True
    return False


def build_opening(company: str, language: str, observation: str) -> str:
    company_label = short_company_name(company)
    focus = infer_focus_from_observation(observation, language)
    low_signal = observation_is_low_signal(company, observation)
    if language == "en":
        if focus:
            return (
                f"I saw that {company_label} focuses on {focus}. "
                "I have an idea to make your online presence clearer and stronger."
            )
        if not low_signal:
            return (
                f"I looked through {company_label}'s website and noticed “{observation}”. "
                "I have an idea to make your online presence clearer and stronger."
            )
        return (
            f"I looked through {company_label}'s website. "
            "I have an idea to make your online presence clearer and stronger."
        )
    if focus:
        return (
            f"Ik zag dat {company_label} zich richt op {focus}. "
            "Ik heb een idee om jullie online aanpak sterker en duidelijker te maken."
        )
    if not low_signal:
        return (
            f"Ik heb de website van {company_label} bekeken en zag “{observation}”. "
            "Ik heb een idee om jullie online aanpak sterker en duidelijker te maken."
        )
    return (
        f"Ik heb de website van {company_label} bekeken. "
        "Ik heb een idee om jullie online aanpak sterker en duidelijker te maken."
    )


def build_template(company: str, language: str, observation: str, *, price_min: int, price_max: int) -> str:
    opening = build_opening(company, language, observation)
    if language == "en":
        return (
            "Hello,\n\n"
            f"{opening}\n\n"
            f"With my Growth Subscription (€{price_min}–€{price_max}/month), I help with:\n\n"
            "• Website/webshop — improve or renew\n"
            "• Search visibility — become more visible in Google\n"
            "• Social content — create relevant content\n"
            "• Automation — streamline recurring work\n"
            "• Hosting — management and maintenance\n"
            "• Fixed contact — direct contact with me\n\n"
            "Would you like me to make a no-obligation example for your homepage? "
            "Then you can first see whether the direction fits.\n\n"
            "Not interested? Just let me know.\n\n"
            "Regards,\nAndrew"
        )
    return (
        "Goedendag,\n\n"
        f"{opening}\n\n"
        f"Met mijn Groeiabonnement (€{price_min}–€{price_max} p/m) help ik met:\n\n"
        "• Website/webshop — verbeteren of vernieuwen\n"
        "• Vindbaarheid — beter zichtbaar in Google\n"
        "• Social content — passende content verzorgen\n"
        "• Automatisering — terugkerend werk slimmer inrichten\n"
        "• Hosting — beheer en onderhoud\n"
        "• Vast contact — rechtstreeks contact met mij\n\n"
        "Zal ik vrijblijvend een voorbeeld voor jullie homepage maken? "
        "Dan kunnen jullie eerst zien of de richting past.\n\n"
        "Geen interesse? Laat het gerust weten.\n\n"
        "Groet,\nAndrew"
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
        has_verified_observation = bool(
            observation
            and observation_source_url
            and observation_source_type == "official_site"
        )
        preview = (
            build_template(company, language, observation, price_min=price_min, price_max=price_max)
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
