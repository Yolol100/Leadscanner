from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_lead_id(email: str, website: str) -> str:
    seed = f"{str(email or '').strip().casefold()}|{str(website or '').strip().casefold()}"
    return "growth-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def clean_company(value: object, language: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text or ("your company" if language == "en" else "jullie bedrijf")


def subject_for_company(company: str, language: str) -> str:
    candidate = f"An idea for {company}" if language == "en" else f"Idee voor {company}"
    if len(candidate) <= 50 and 2 <= len(candidate.split()) <= 6:
        return candidate
    return "Idea for your online setup" if language == "en" else "Idee voor jullie online aanpak"


def build_template(company: str, language: str, *, price_min: int, price_max: int) -> str:
    if language == "en":
        return (
            "Hello,\n\n"
            f"I came across {company} online. I help businesses improve their online setup with one compact Growth Subscription.\n\n"
            "• Improve or rebuild the website/webshop where needed\n"
            "• Improve search visibility\n"
            "• Create social content\n"
            "• Partly automate suitable recurring processes where feasible\n"
            "• Take over/manage hosting\n"
            "• Me as your fixed contact\n\n"
            f"€{price_min}–€{price_max} per month, depending on what you need.\n\n"
            f"Would you like me to make a no-obligation example design for {company}, so you can first see whether the direction is relevant?\n\n"
            "Not relevant? Let me know and I’ll leave it there.\n\n"
            "Regards,\nAndrew"
        )
    return (
        "Goedendag,\n\n"
        f"Ik kwam {company} online tegen. Met één compact Groeiabonnement help ik bedrijven hun online aanpak doorlopend verbeteren.\n\n"
        "• Website/webshop verbeteren of nieuw maken waar nodig\n"
        "• Zoekbaarheid verbeteren\n"
        "• Social content verzorgen\n"
        "• Geschikte terugkerende processen waar haalbaar deels automatiseren\n"
        "• Hosting overnemen/beheren\n"
        "• Ik als vast contactpersoon\n\n"
        f"€{price_min}–€{price_max} per maand, afhankelijk van wat jullie nodig hebben.\n\n"
        f"Zal ik vrijblijvend een voorbeeld design maken voor {company}? Dan kunnen jullie eerst bekijken of de richting interessant is.\n\n"
        "Geen interesse? Laat het gerust weten, dan houd ik het hierbij.\n\n"
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
        preview = build_template(company, language, price_min=price_min, price_max=price_max)
        subject_preview = subject_for_company(company, language)
        basis = str(candidate.get("contact_basis_status") or "unverified")
        base = {
            "lead_id": None,
            "company": candidate.get("name_hint"),
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
            if selected < draft_limit:
                selected += 1
                base["status"] = "draft_ready" if basis == "pass" else "review_draft"
                base["subject"] = subject_preview
                base["body"] = preview
            else:
                base["status"] = "email_found_not_selected"
        rows.append(base)

    return {
        "schema_version": "webactueel-growth-batch/4.0",
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
