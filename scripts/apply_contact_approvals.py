from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def normalize_email(value: object) -> str:
    return str(value or "").strip().casefold()


def parse_approved_emails(raw: str) -> set[str]:
    return {
        normalize_email(item)
        for item in re.split(r"[,;\n\r]+", raw or "")
        if normalize_email(item)
    }


def apply_approvals(payload: dict, approved_emails: set[str]) -> dict:
    candidates = payload.get("candidates") or []
    approved_count = 0

    for candidate in candidates:
        if candidate.get("excluded_competitor"):
            candidate["contact_basis_status"] = "blocked"
            candidate["contact_basis_hint"] = "excluded_competitor"
            continue

        emails = [normalize_email(x) for x in candidate.get("public_business_emails") or []]
        matched = next((email for email in emails if email in approved_emails), None)
        if matched:
            candidate["contact_basis_status"] = "pass"
            candidate["contact_basis_hint"] = "explicit_exact_email_approval"
            candidate["contact_basis_approved_email"] = matched
            approved_count += 1
        else:
            candidate["contact_basis_status"] = "unverified"
            candidate.pop("contact_basis_approved_email", None)

    return {
        **payload,
        "approval_mode": "explicit_exact_email_only",
        "approved_contact_count": approved_count,
        "candidates": candidates,
        "safety": {
            **(payload.get("safety") or {}),
            "contact_basis_inferred_from_public_email": False,
            "approval_required_for_addressed_draft": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--approved-emails", default="")
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    approved = parse_approved_emails(args.approved_emails)
    result = apply_approvals(payload, approved)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "CONTACT_APPROVALS=green "
        f"approved={result['approved_contact_count']} "
        "mode=explicit_exact_email_only"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
