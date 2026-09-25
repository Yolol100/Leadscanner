from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

VALID_ANGLES = {
    "website_webshop",
    "search_visibility",
    "social_content",
    "automation",
    "hosting",
    "fixed_contact",
}

ANGLE_FOCUS = {
    "website_webshop": "website/webshop",
    "search_visibility": "vindbaarheid",
    "social_content": "social content",
    "automation": "automatisering",
    "hosting": "hosting en technisch beheer",
    "fixed_contact": "doorlopende ondersteuning en aanpassingen",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_template(company: str, angle: str, *, show_price: bool, price_text: str) -> str:
    intro = "Ik bied één Groeiabonnement."
    if show_price:
        intro = f"{intro} {price_text}"

    return (
        f"Hoi {company},\n\n"
        f"{intro} Daarmee verbeter ik website/webshop en vindbaarheid, verzorg ik social content, "
        "automatiseer ik geschikte repetitieve werkzaamheden tot circa 30% waar dat haalbaar is, "
        "kan ik hosting overnemen en blijf ik jullie vaste contactpersoon voor aanpassingen. "
        f"De eerste focus kan liggen op {ANGLE_FOCUS[angle]}.\n\n"
        "Zal ik kort laten zien hoe dit voor jullie kan werken?\n\n"
        "Groet,\nAndrew Baeten\nandrewbaeten.nl\n\n"
        "Geen interesse? Laat het gerust weten, dan mail ik niet meer."
    )


def prepare_batch(contacts_payload: dict, config: dict, *, angle: str, show_price: bool) -> dict:
    if angle not in VALID_ANGLES:
        raise ValueError(f"primary_angle must be one of: {', '.join(sorted(VALID_ANGLES))}")

    price = config["monthly_price_eur"]
    price_text = config["first_touch"]["price_text"]
    rows = []

    for candidate in contacts_payload.get("candidates") or []:
        emails = candidate.get("public_business_emails") or []
        company = str(candidate.get("name_hint") or "").strip() or "daar"
        base = {
            "company": candidate.get("name_hint"),
            "website": candidate.get("website_hint"),
            "official_domain_hint": candidate.get("official_domain_hint"),
            "product_id": "growth_subscription",
            "primary_angle": angle,
            "monthly_price_min_eur": price["min"],
            "monthly_price_max_eur": price["max"],
            "contact_basis_status": candidate.get("contact_basis_status", "unverified"),
            "contact_basis_hint": candidate.get("contact_basis_hint"),
            "email_source_urls": candidate.get("email_source_urls") or [],
            "status": "no_public_email",
            "email": None,
            "subject": None,
            "body": None,
            "template_preview": build_template(company, angle, show_price=show_price, price_text=price_text),
        }
        if emails:
            base["email"] = emails[0]
            base["status"] = (
                "draft_ready"
                if base["contact_basis_status"] == "pass"
                else "needs_contact_basis"
            )
            if base["contact_basis_status"] == "pass":
                base["subject"] = f"Groeiabonnement voor {company}"
                base["body"] = base["template_preview"]
        rows.append(base)

    return {
        "schema_version": "webactueel-growth-batch/1.0",
        "product": config,
        "primary_angle": angle,
        "show_price": show_price,
        "row_count": len(rows),
        "draft_ready_count": sum(1 for row in rows if row["status"] == "draft_ready"),
        "needs_contact_basis_count": sum(1 for row in rows if row["status"] == "needs_contact_basis"),
        "rows": rows,
        "safety": {
            "one_product": True,
            "one_primary_angle": True,
            "contact_basis_required_before_addressed_copy": True,
            "automatic_send": False,
        },
    }


def write_csv(payload: dict, path: Path) -> None:
    fields = [
        "company",
        "website",
        "email",
        "status",
        "contact_basis_status",
        "contact_basis_hint",
        "product_id",
        "primary_angle",
        "monthly_price_min_eur",
        "monthly_price_max_eur",
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
    parser.add_argument("--angle", required=True)
    parser.add_argument("--show-price", action="store_true")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-csv", required=True)
    args = parser.parse_args()

    contacts_payload = load_json(Path(args.contacts))
    config = load_json(Path(args.config))
    result = prepare_batch(
        contacts_payload,
        config,
        angle=args.angle,
        show_price=args.show_price,
    )

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_csv(result, Path(args.output_csv))
    print(
        "GROWTH_BATCH=green "
        f"rows={result['row_count']} draft_ready={result['draft_ready_count']} "
        f"needs_contact_basis={result['needs_contact_basis_count']} email_send=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
