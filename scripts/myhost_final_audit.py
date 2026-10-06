from __future__ import annotations

import argparse
import imaplib
import json
import re
from collections import Counter
from pathlib import Path

from myhost_draft import (
    build_message,
    connect_imap,
    exact_message_matches,
    fetch_message,
    find_drafts_folder,
    find_message_ids,
    normalize_text,
    plain_body,
    select_folder,
)
from prepare_growth_batch import prepare_batch, short_company_name, subject_for_company, subject_label_for_company, validate_short_first_touch


def norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def audit_rows(
    batch_payloads: list[dict],
    reports: list[dict],
    config: dict,
    excluded_lead_ids: set[str] | None = None,
) -> tuple[list[dict], list[str], dict]:
    rows: list[dict] = []
    failures: list[str] = []
    excluded = {str(value).strip() for value in (excluded_lead_ids or set()) if str(value).strip()}
    excluded_seen: set[str] = set()

    if len(batch_payloads) != len(reports):
        failures.append(
            f"artifact_count_mismatch: batches={len(batch_payloads)} reports={len(reports)}"
        )

    expected_counts: list[int] = []
    for index, batch in enumerate(batch_payloads, start=1):
        all_phase_rows = [row for row in batch.get("rows") or [] if row.get("status") == "review_draft"]
        report = reports[index - 1] if index - 1 < len(reports) else {}
        original_expected = int(report.get("eligible_count") or 0)
        if original_expected <= 0:
            failures.append(f"batch{index}: eligible_count must be positive")
        if len(all_phase_rows) != original_expected:
            failures.append(
                f"batch{index}: artifact/report count mismatch {len(all_phase_rows)}/{original_expected}"
            )
        excluded_here = {
            str(row.get("lead_id") or "")
            for row in all_phase_rows
            if str(row.get("lead_id") or "") in excluded
        }
        excluded_seen.update(excluded_here)
        phase_rows = [
            row for row in all_phase_rows
            if str(row.get("lead_id") or "") not in excluded
        ]
        expected = max(0, original_expected - len(excluded_here))
        expected_counts.append(expected)
        if len(phase_rows) != expected:
            failures.append(
                f"batch{index}: expected {expected} canonical review_draft rows, found {len(phase_rows)}"
            )
        if (batch.get("safety") or {}).get("automatic_send") is not False:
            failures.append(f"batch{index}: automatic_send is not false")
        rows.extend(phase_rows)

    missing_exclusions = sorted(excluded - excluded_seen)
    if missing_exclusions:
        failures.append(f"excluded_lead_ids_missing_from_artifacts: {missing_exclusions[:10]}")

    requested_total = sum(expected_counts)
    if len(rows) != requested_total:
        failures.append(
            f"final_set: expected {requested_total} rows, found {len(rows)}"
        )

    for label, key in (
        ("lead_id", "lead_id"),
        ("email", "email"),
        ("domain", "official_domain_hint"),
    ):
        values = [norm(row.get(key)) for row in rows]
        duplicates = [value for value, count in Counter(values).items() if value and count > 1]
        if duplicates:
            failures.append(f"duplicate_{label}: {duplicates[:10]}")

    company_counts = Counter(norm(row.get("company")) for row in rows)
    company_name_collisions = {
        value: count
        for value, count in company_counts.items()
        if value and count > 1
    }

    language_split = Counter()
    email_source_types = Counter()

    for row in rows:
        lead_id = str(row.get("lead_id") or "")
        language = str(row.get("language") or "")
        language_split[language] += 1

        if row.get("excluded_competitor") is not False:
            failures.append(f"{lead_id}: competitor flag is not false")
        if row.get("contact_basis_status") != "review_required":
            failures.append(f"{lead_id}: contact_basis_status is not review_required")
        if language not in {"nl", "en"}:
            failures.append(f"{lead_id}: invalid language {language!r}")
        if row.get("monthly_price_min_eur") != 250 or row.get("monthly_price_max_eur") != 500:
            failures.append(f"{lead_id}: price boundary mismatch")
        if row.get("verified_observation_source_type") != "official_site":
            failures.append(f"{lead_id}: observation source is not official_site")
        observation = str(row.get("verified_observation") or "").strip()
        observation_url = str(row.get("verified_observation_source_url") or "").strip()
        if not observation:
            failures.append(f"{lead_id}: missing verified observation")
        if not observation_url.startswith(("http://", "https://")):
            failures.append(f"{lead_id}: missing observation provenance URL")

        source_types = row.get("email_source_types") or []
        source_urls = row.get("email_source_urls") or []
        source_refs = row.get("email_source_refs") or []
        if not source_types:
            failures.append(f"{lead_id}: missing email source type")
        else:
            email_source_types[str(source_types[0])] += 1
        if not any(str(value or "").strip() for value in list(source_urls) + list(source_refs)):
            failures.append(f"{lead_id}: missing exact email provenance")

        body = str(row.get("body") or "")
        subject = str(row.get("subject") or "")
        proof_text = str(row.get("verified_social_proof") or "").strip() or None
        proof_source_url = str(row.get("verified_social_proof_source_url") or "").strip() or None
        try:
            validate_short_first_touch(
                subject,
                body,
                proof_text=proof_text,
                proof_source_url=proof_source_url,
            )
        except ValueError as exc:
            failures.append(f"{lead_id}: short first-touch validation failed: {exc}")

        company_label = str(
            row.get("copy_company_label")
            or short_company_name(str(row.get("company") or ""))
        ).strip()
        subject_label = str(
            row.get("copy_subject_label")
            or subject_label_for_company(str(row.get("company") or ""), language)
        ).strip()
        if not subject_label or subject_label.casefold() not in subject.casefold():
            failures.append(f"{lead_id}: personalized company label missing from subject")
        expected_subject = subject_for_company(str(row.get("company") or ""), language)
        if subject != expected_subject:
            failures.append(f"{lead_id}: subject mismatch")

        if language == "nl":
            if not body.startswith("Hallo,\n\n") and not re.match(r"^Hallo [^\n]+,\n\n", body):
                failures.append(f"{lead_id}: NL greeting mismatch")
            if "Wat me opviel:" not in body:
                failures.append(f"{lead_id}: NL verified observation line missing")
            if body.count(
                "Zal ik vrijblijvend een voorbeeld laten zien hoe dit er voor jullie uit kan zien?"
            ) != 1:
                failures.append(f"{lead_id}: NL CTA count mismatch")
            if "Geen interesse? Laat het gerust weten." not in body:
                failures.append(f"{lead_id}: NL easy-no missing")
            if not body.endswith("Groet,\nAndrew"):
                failures.append(f"{lead_id}: NL signature mismatch")
        elif language == "en":
            if not body.startswith("Hello,\n\n") and not re.match(r"^Hello [^\n]+,\n\n", body):
                failures.append(f"{lead_id}: EN greeting mismatch")
            if "What stood out:" not in body:
                failures.append(f"{lead_id}: EN verified observation line missing")
            if body.count(
                "Would you like me to show you a no-obligation example of what this could look like for you?"
            ) != 1:
                failures.append(f"{lead_id}: EN CTA count mismatch")
            if "Not interested? Just let me know." not in body:
                failures.append(f"{lead_id}: EN easy-no missing")
            if not body.endswith("Regards,\nAndrew"):
                failures.append(f"{lead_id}: EN signature mismatch")

        contact = {
            "name_hint": row.get("company"),
            "website_hint": row.get("website"),
            "official_domain_hint": row.get("official_domain_hint"),
            "public_business_emails": [row.get("email")],
            "email_source_urls": row.get("email_source_urls") or [],
            "email_source_types": row.get("email_source_types") or [],
            "email_source_refs": row.get("email_source_refs") or [],
            "verified_observation": row.get("verified_observation"),
            "verified_observation_source_url": row.get("verified_observation_source_url"),
            "verified_observation_source_type": row.get("verified_observation_source_type"),
            "language": row.get("language"),
            "language_source": row.get("language_source"),
            "category_hint": row.get("category_hint"),
            "excluded_competitor": False,
            "contact_basis_status": "review_required",
            "contact_basis_hint": row.get("contact_basis_hint"),
        }
        regenerated = prepare_batch({"candidates": [contact]}, config, draft_limit=1)["rows"][0]
        if regenerated.get("lead_id") != lead_id:
            failures.append(f"{lead_id}: regenerated lead ID mismatch")
        if regenerated.get("subject") != subject:
            failures.append(f"{lead_id}: regenerated subject mismatch")
        if regenerated.get("body") != body:
            failures.append(f"{lead_id}: regenerated body mismatch")

    readback_by_id: dict[str, dict] = {}
    allowed_outcomes_by_id: dict[str, str] = {}
    for index, report in enumerate(reports, start=1):
        original_expected = int(report.get("eligible_count") or 0)
        if original_expected <= 0:
            failures.append(f"report{index}: eligible_count mismatch")
        created = int(report.get("created_count") or 0)
        existing = int(report.get("existing_count") or 0)
        replaced = int(report.get("replaced_count") or 0)
        if created != 0:
            failures.append(f"report{index}: final audit rewrite report must not create drafts")
        if existing + replaced != original_expected:
            failures.append(
                f"report{index}: expected existing+replaced={original_expected}, "
                f"got existing={existing} replaced={replaced}"
            )
        if report.get("review_required_count") != original_expected:
            failures.append(f"report{index}: review_required_count mismatch")
        if report.get("smtp_send") != "not_available":
            failures.append(f"report{index}: smtp_send must be not_available")
        for item in report.get("items") or []:
            lead_id = str(item.get("lead_id") or "")
            if lead_id in excluded:
                continue
            if lead_id in readback_by_id:
                failures.append(f"{lead_id}: duplicate artifact readback")
            readback_by_id[lead_id] = item
            outcome = str(item.get("outcome") or "")
            if outcome not in {"existing", "replaced"}:
                failures.append(f"{lead_id}: unsupported rewrite outcome {outcome!r}")
            allowed_outcomes_by_id[lead_id] = outcome

    for row in rows:
        lead_id = row["lead_id"]
        item = readback_by_id.get(lead_id)
        if not item:
            failures.append(f"{lead_id}: missing artifact readback")
            continue
        if item.get("to") != row.get("email"):
            failures.append(f"{lead_id}: artifact To mismatch")
        if item.get("subject") != row.get("subject"):
            failures.append(f"{lead_id}: artifact subject mismatch")
        if item.get("body") != row.get("body"):
            failures.append(f"{lead_id}: artifact body mismatch")
        if item.get("review_status") != "contact-basis":
            failures.append(f"{lead_id}: artifact review status mismatch")
        expected_outcome = allowed_outcomes_by_id.get(lead_id)
        if item.get("outcome") != expected_outcome:
            failures.append(
                f"{lead_id}: artifact outcome mismatch, expected {expected_outcome!r}, got {item.get('outcome')!r}"
            )

    metrics = {
        "requested_total": requested_total,
        "artifact_rows": len(rows),
        "artifact_readbacks": len(readback_by_id),
        "unique_lead_ids": len({norm(row.get("lead_id")) for row in rows}),
        "unique_emails": len({norm(row.get("email")) for row in rows}),
        "unique_domains": len({norm(row.get("official_domain_hint")) for row in rows}),
        "unique_companies": len({norm(row.get("company")) for row in rows}),
        "company_name_collision_groups": len(company_name_collisions),
        "company_name_collision_rows": sum(company_name_collisions.values()),
        "language_split": dict(language_split),
        "email_source_types": dict(email_source_types),
        "excluded_lead_ids": sorted(excluded),
        "excluded_artifact_count": len(excluded_seen),
    }
    return rows, failures, metrics


def _reconnect_selected(client, folder: str):
    try:
        client.logout()
    except Exception:
        pass
    client = connect_imap()
    select_folder(client, folder, readonly=True)
    return client


def _read_expected_message(client, folder: str, lead_id: str):
    for attempt in range(2):
        try:
            ids = find_message_ids(client, folder, lead_id, ensure_selected=False)
            if len(ids) != 1:
                return client, ids, None
            return client, ids, fetch_message(client, ids[0])
        except imaplib.IMAP4.abort:
            if attempt:
                raise
            client = _reconnect_selected(client, folder)
    raise RuntimeError("unreachable")


def _find_ids_with_retry(client, folder: str, lead_id: str):
    for attempt in range(2):
        try:
            return client, find_message_ids(client, folder, lead_id, ensure_selected=False)
        except imaplib.IMAP4.abort:
            if attempt:
                raise
            client = _reconnect_selected(client, folder)
    raise RuntimeError("unreachable")


def audit_mailbox(
    rows: list[dict],
    excluded_lead_ids: set[str] | None = None,
) -> tuple[list[str], dict]:
    failures: list[str] = []
    expected = {row["lead_id"]: row for row in rows}
    excluded = {str(value).strip() for value in (excluded_lead_ids or set()) if str(value).strip()}
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        select_folder(client, folder, readonly=True)

        matched = 0
        for lead_id, row in expected.items():
            client, ids, actual = _read_expected_message(client, folder, lead_id)
            if len(ids) != 1:
                failures.append(f"{lead_id}: current mailbox count={len(ids)}, expected 1")
                continue
            _, expected_message = build_message(row)
            if actual is None or not exact_message_matches(actual, expected_message):
                failures.append(f"{lead_id}: current mailbox exact content mismatch")
                continue
            matched += 1

        excluded_absent = 0
        for lead_id in sorted(excluded):
            client, ids = _find_ids_with_retry(client, folder, lead_id)
            if ids:
                failures.append(f"{lead_id}: excluded draft still present count={len(ids)}")
            else:
                excluded_absent += 1

        metrics = {
            "draft_folder": folder,
            "mailbox_scan_mode": "targeted_expected_lead_ids",
            "final_set_current_exact_matches": matched,
            "final_set_current_expected": len(expected),
            "excluded_mailbox_absent": excluded_absent,
            "excluded_mailbox_expected_absent": len(excluded),
            "read_only": True,
        }
        return failures, metrics
    finally:
        try:
            client.logout()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", action="append", required=True)
    parser.add_argument("--report", action="append", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--exclude-lead-id", action="append", default=[])
    args = parser.parse_args()

    if not 1 <= len(args.batch) <= 10 or len(args.batch) != len(args.report):
        raise SystemExit("Final audit requires 1-10 paired draft artifacts")

    batch_payloads = [load(path) for path in args.batch]
    reports = [load(path) for path in args.report]
    config = load(args.config)

    excluded_lead_ids = {str(value).strip() for value in args.exclude_lead_id if str(value).strip()}
    rows, artifact_failures, metrics = audit_rows(
        batch_payloads, reports, config, excluded_lead_ids
    )
    mailbox_failures, mailbox_metrics = audit_mailbox(rows, excluded_lead_ids)
    failures = artifact_failures + mailbox_failures

    sample = None
    if rows:
        row = rows[0]
        sample = {
            "lead_id": row.get("lead_id"),
            "company": row.get("company"),
            "verified_observation": row.get("verified_observation"),
            "subject": row.get("subject"),
            "body": row.get("body"),
        }

    result = {
        "schema_version": "webactueel-final-leads-audit/1.0",
        **metrics,
        **mailbox_metrics,
        "competitor_failures": sum(1 for failure in failures if "competitor" in failure),
        "failure_count": len(failures),
        "failures": failures,
        "automatic_send": False,
        "smtp_send": "not_available",
        "sample_real_created_draft": sample,
    }
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if failures:
        print(
            "FINAL_LEADS_AUDIT=red "
            f"failures={len(failures)} "
            f"exact_mailbox={mailbox_metrics['final_set_current_exact_matches']}/{metrics['requested_total']} "
            "automatic_send=false"
        )
        return 2

    print(
        "FINAL_LEADS_AUDIT=green "
        f"total={metrics['requested_total']} "
        f"unique_lead_ids={metrics['unique_lead_ids']} "
        f"unique_emails={metrics['unique_emails']} "
        f"unique_domains={metrics['unique_domains']} "
        f"unique_companies={metrics['unique_companies']} "
        f"nl={metrics['language_split'].get('nl', 0)} en={metrics['language_split'].get('en', 0)} "
        f"exact_mailbox={mailbox_metrics['final_set_current_exact_matches']}/{metrics['requested_total']} "
        "automatic_send=false smtp_send=not_available"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
