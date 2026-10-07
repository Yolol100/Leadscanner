#!/usr/bin/env python3
"""Phases 10-11: prepare review drafts and audit exact IMAP readback.

This module never sends email. It turns phase-9 review copy into the strict
input contract for myhost_draft.py and, after IMAP write/readback, emits the
exact dedupe-registry rows that phase 12 may append.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

MAX_DRAFTS = 100


def _text(value: object) -> str:
    return str(value or "").strip()


def normalize_domain(value: object) -> str:
    raw = _text(value).casefold()
    if not raw:
        return ""
    candidate = raw if "://" in raw else f"//{raw}"
    host = (urlparse(candidate).hostname or "").rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def stable_lead_id(domain: str, email: str) -> str:
    domain = normalize_domain(domain)
    email = _text(email).casefold()
    if not domain or not email or email.count("@") != 1:
        raise ValueError("lead_identity_requires_domain_and_email")
    digest = hashlib.sha256(f"{domain}\0{email}".encode("utf-8")).hexdigest()[:20]
    return f"growth-{digest}"


def prepare_review_batch(payload: dict) -> dict:
    candidates = payload.get("candidates") or []
    if not isinstance(candidates, list):
        raise ValueError("candidates_must_be_list")

    rows: list[dict] = []
    seen_domains: set[str] = set()
    seen_emails: set[str] = set()
    seen_ids: set[str] = set()

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("mail_status") != "ready_for_human_review":
            continue
        if candidate.get("copy_validation_status") != "green":
            raise ValueError("ready_mail_without_green_validation")
        if candidate.get("automatic_send") is not False:
            raise ValueError("automatic_send_must_be_false")

        domain = normalize_domain(candidate.get("official_domain"))
        email = _text(candidate.get("public_business_email")).casefold()
        website = _text(candidate.get("official_url"))
        company = _text(candidate.get("name_hint") or candidate.get("company"))
        subject = _text(candidate.get("subject"))
        body = _text(candidate.get("body"))
        if not all((domain, email, website, company, subject, body)):
            raise ValueError("review_mail_missing_required_field")
        if email.count("@") != 1:
            raise ValueError("review_mail_invalid_email")
        if normalize_domain(email.rsplit("@", 1)[1]) == "":
            raise ValueError("review_mail_invalid_email_domain")

        lead_id = stable_lead_id(domain, email)
        if domain in seen_domains or email in seen_emails or lead_id in seen_ids:
            raise ValueError("duplicate_review_draft_identity")
        seen_domains.add(domain)
        seen_emails.add(email)
        seen_ids.add(lead_id)

        rows.append({
            "lead_id": lead_id,
            "company": company,
            "website": website,
            "official_domain": domain,
            "email": email,
            "subject": subject,
            "body": body,
            "status": "review_draft",
            "contact_basis_status": "review_required",
            "automatic_send": False,
            "verified_observation": _text(candidate.get("verified_observation")),
            "verified_observation_source_url": _text(candidate.get("verified_observation_source_url")),
            "verified_observation_source_type": _text(candidate.get("verified_observation_source_type")),
            "signal_type": _text(candidate.get("signal_type")),
            "value_first_action": _text(candidate.get("value_first_action")),
        })

    if len(rows) > MAX_DRAFTS:
        raise ValueError("draft_limit_exceeded")

    return {
        "schema_version": "leadscanner-review-draft-batch/1.0",
        "draft_candidate_count": len(rows),
        "review_draft_count": len(rows),
        "rows": rows,
        "safety": {
            "automatic_send": False,
            "smtp_available": False,
            "human_review_required": True,
            "changed_existing_draft_policy": "reject",
        },
    }


def audit_exact_readback(batch: dict, report: dict) -> dict:
    rows = batch.get("rows") or []
    items = report.get("items") or []
    if not isinstance(rows, list) or not isinstance(items, list):
        raise ValueError("invalid_batch_or_report")
    if len(rows) > MAX_DRAFTS:
        raise ValueError("draft_limit_exceeded")

    expected = {_text(row.get("lead_id")): row for row in rows}
    if len(expected) != len(rows):
        raise ValueError("duplicate_lead_id_in_batch")

    if report.get("eligible_count") != len(rows):
        raise ValueError("eligible_count_mismatch")
    if report.get("replaced_count") not in {0, None}:
        raise ValueError("replacement_not_allowed")
    if report.get("smtp_send") != "not_available":
        raise ValueError("smtp_surface_must_be_unavailable")
    if report.get("review_required_count") != len(rows):
        raise ValueError("review_required_count_mismatch")
    if len(items) != len(rows):
        raise ValueError("readback_count_mismatch")

    seen: set[str] = set()
    registry_rows: list[list[str]] = []
    actual_created = 0
    actual_existing = 0
    for item in items:
        lead_id = _text(item.get("lead_id"))
        if lead_id in seen or lead_id not in expected:
            raise ValueError("unknown_or_duplicate_readback_lead_id")
        seen.add(lead_id)
        row = expected[lead_id]

        outcome = item.get("outcome")
        if outcome not in {"created", "existing"}:
            raise ValueError("draft_outcome_not_idempotent")
        if outcome == "created":
            actual_created += 1
        else:
            actual_existing += 1
        if _text(item.get("review_status")) != "contact-basis":
            raise ValueError("review_status_mismatch")
        if _text(item.get("to")).casefold() != _text(row.get("email")).casefold():
            raise ValueError("readback_to_mismatch")
        if _text(item.get("subject")) != _text(row.get("subject")):
            raise ValueError("readback_subject_mismatch")
        if _text(item.get("body")) != _text(row.get("body")):
            raise ValueError("readback_body_mismatch")

        registry_rows.append([
            _text(row.get("company")),
            _text(row.get("website")),
            normalize_domain(row.get("official_domain")),
            _text(row.get("email")).casefold(),
            "concept",
            "concept",
            lead_id,
            "",
            "cold_pipeline_review_draft",
            "TRUE",
        ])

    if seen != set(expected):
        raise ValueError("readback_lead_set_mismatch")
    if (
        report.get("created_count") != actual_created
        or report.get("existing_count") != actual_existing
    ):
        raise ValueError("draft_outcome_count_mismatch")

    return {
        "schema_version": "leadscanner-review-readback/1.0",
        "status": "green",
        "draft_count": len(rows),
        "created_count": int(report.get("created_count") or 0),
        "existing_count": int(report.get("existing_count") or 0),
        "replaced_count": 0,
        "automatic_send": False,
        "smtp_send": "not_available",
        "registry_headers": [
            "company", "website", "domain", "emails", "status", "history",
            "lead_ids", "last_event_at", "sources", "exclude_from_new_leads",
        ],
        "registry_rows": registry_rows,
    }


def _read(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("input_must_be_object")
    return data


def _write(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--input", required=True)
    prepare.add_argument("--output", required=True)

    readback = sub.add_parser("readback")
    readback.add_argument("--batch", required=True)
    readback.add_argument("--report", required=True)
    readback.add_argument("--output", required=True)

    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_review_batch(_read(args.input))
        _write(args.output, result)
        print(
            "REVIEW_DRAFT_PREP=green "
            f"count={result['draft_candidate_count']} automatic_send=false"
        )
    else:
        result = audit_exact_readback(_read(args.batch), _read(args.report))
        _write(args.output, result)
        print(
            "REVIEW_DRAFT_READBACK=green "
            f"count={result['draft_count']} replaced=0 smtp_send=not_available"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
