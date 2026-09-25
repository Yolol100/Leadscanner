from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_lead_id(email: str, website: str) -> str:
    seed = f"{str(email or '').strip().casefold()}|{str(website or '').strip().casefold()}"
    return "growth-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def subject_for_language(language: str) -> str:
    return (
        "Quick question about online growth"
        if language == "en"
        else "Korte vraag over online groei"
    )


def build_template(
    company: str,
    language: str,
    *,
    price_min: int,
    price_max: int,
) -> str:
    if language == "en":
        return (
            f"Hi {company},\n\n"
            f"I help businesses with one Growth Subscription for €{price_min}-€{price_max} per month, "
            "depending on the scope. It covers website/webshop improvements, better search visibility, "
            "social content, automation of suitable repetitive work up to about 30% where feasible, "
            "hosting management, and one fixed contact for changes and support.\n\n"
            "Would you like me to briefly show how this could work for you?\n\n"
            "Regards,\nAndrew Baeten\nandrewbaeten.nl\n\n"
            "Not interested? Let me know and I won't email again."
        )

    return (
        f"Hoi {company},\n\n"
        f"Ik help bedrijven met één Groeiabonnement van €{price_min}-€{price_max} per maand, "
        "afhankelijk van de scope. Daarin verbeter ik website/webshop en vindbaarheid, verzorg ik "
        "social content, automatiseer ik geschikte terugkerende werkzaamheden tot circa 30% waar "
        "haalbaar, kan ik hosting overnemen en blijf ik jullie vaste contactpersoon voor aanpassingen "
        "en ondersteuning.\n\n"
        "Zal ik kort laten zien hoe dit voor jullie kan werken?\n\n"
        "Groet,\nAndrew Baeten\nandrewbaeten.nl\n\n"
        "Geen interesse? Laat het gerust weten, dan mail ik niet meer."
    )


def prepare_batch(contacts_payload: dict, config: dict) -> dict:
    price = config["monthly_price_eur"]
    price_min = int(price["min"])
    price_max = int(price["max"])
    rows = []

    for candidate in contacts_payload.get("candidates") or []:
        language = str(candidate.get("language") or "nl").casefold()
        if language not in {"nl", "en"}:
            language = "nl"

        company = str(candidate.get("name_hint") or "").strip() or (
            "there" if language == "en" else "daar"
        )
        emails = candidate.get("public_business_emails") or []
        excluded = bool(candidate.get("excluded_competitor"))
        preview = build_template(
            company,
            language,
            price_min=price_min,
            price_max=price_max,
        )
        subject_preview = subject_for_language(language)

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
            "contact_basis_status": candidate.get("contact_basis_status", "unverified"),
            "contact_basis_hint": candidate.get("contact_basis_hint"),
            "email_source_urls": candidate.get("email_source_urls") or [],
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
            base["status"] = (
                "draft_ready"
                if base["contact_basis_status"] == "pass"
                else "needs_contact_basis"
            )
            if base["contact_basis_status"] == "pass":
                base["subject"] = subject_preview
                base["body"] = preview
        rows.append(base)

    return {
        "schema_version": "webactueel-growth-batch/2.0",
        "product": config,
        "row_count": len(rows),
        "excluded_competitor_count": sum(1 for row in rows if row["status"] == "excluded_competitor"),
        "email_found_count": sum(1 for row in rows if row["email"]),
        "draft_ready_count": sum(1 for row in rows if row["status"] == "draft_ready"),
        "needs_contact_basis_count": sum(1 for row in rows if row["status"] == "needs_contact_basis"),
        "rows": rows,
        "safety": {
            "one_product": True,
            "six_benefits": True,
            "language_matched_copy": True,
            "contact_basis_required_before_addressed_copy": True,
            "automatic_send": False,
        },
    }


def write_csv(payload: dict, path: Path) -> None:
    fields = [
        "lead_id",
        "company",
        "website",
        "email",
        "language",
        "status",
        "excluded_competitor",
        "exclusion_reason",
        "contact_basis_status",
        "contact_basis_hint",
        "product_id",
        "monthly_price_min_eur",
        "monthly_price_max_eur",
        "subject_preview",
        "concept_preview",
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
    args = parser.parse_args()

    contacts_payload = load_json(Path(args.contacts))
    config = load_json(Path(args.config))
    result = prepare_batch(contacts_payload, config)

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_csv(result, Path(args.output_csv))
    print(
        "GROWTH_BATCH=green "
        f"rows={result['row_count']} emails={result['email_found_count']} "
        f"excluded_competitors={result['excluded_competitor_count']} "
        f"needs_contact_basis={result['needs_contact_basis_count']} "
        "email_send=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
