from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from myhost_draft import (
    build_message,
    connect_imap,
    exact_message_matches,
    fetch_message,
    find_drafts_folder,
    normalize_text,
    plain_body,
    select_folder,
)
from prepare_growth_batch import prepare_batch, short_company_name


def norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def audit_rows(batch_payloads: list[dict], reports: list[dict], config: dict) -> tuple[list[dict], list[str], dict]:
    rows: list[dict] = []
    failures: list[str] = []

    for index, batch in enumerate(batch_payloads, start=1):
        phase_rows = [row for row in batch.get("rows") or [] if row.get("status") == "review_draft"]
        if len(phase_rows) != 75:
            failures.append(f"batch{index}: expected 75 review_draft rows, found {len(phase_rows)}")
        if (batch.get("safety") or {}).get("automatic_send") is not False:
            failures.append(f"batch{index}: automatic_send is not false")
        rows.extend(phase_rows)

    if len(rows) != 150:
        failures.append(f"final_set: expected 150 rows, found {len(rows)}")

    for label, key in (
        ("lead_id", "lead_id"),
        ("email", "email"),
        ("domain", "official_domain_hint"),
        ("company", "company"),
    ):
        values = [norm(row.get(key)) for row in rows]
        duplicates = [value for value, count in Counter(values).items() if value and count > 1]
        if duplicates:
            failures.append(f"duplicate_{label}: {duplicates[:10]}")

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
        bullets = [line for line in body.splitlines() if line.startswith("• ")]
        if len(bullets) != 6:
            failures.append(f"{lead_id}: expected six bullets, found {len(bullets)}")
        if body.count("€250–€500") != 1:
            failures.append(f"{lead_id}: price text count mismatch")
        if re.search(r"\b\d+\s*%", body):
            failures.append(f"{lead_id}: automation percentage found")
        company_label = str(row.get("copy_company_label") or short_company_name(str(row.get("company") or ""))).strip()
        if not company_label or company_label not in body or company_label not in subject:
            failures.append(f"{lead_id}: personalized company label missing from copy")
        if "Op jullie website staat" in body or "Your website highlights" in body:
            failures.append(f"{lead_id}: old vague opening survived")
        if language == "nl":
            if body.count("Zal ik vrijblijvend een voorbeeld design maken") != 1:
                failures.append(f"{lead_id}: NL CTA count mismatch")
            if "Geen interesse? Laat het gerust weten" not in body:
                failures.append(f"{lead_id}: NL easy-no missing")
            if not body.endswith("Groet,\nAndrew"):
                failures.append(f"{lead_id}: NL signature mismatch")
        elif language == "en":
            if body.count("Would you like me to make a no-obligation example design") != 1:
                failures.append(f"{lead_id}: EN CTA count mismatch")
            if "Not relevant? Let me know" not in body:
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
    for index, report in enumerate(reports, start=1):
        if report.get("eligible_count") != 75:
            failures.append(f"report{index}: eligible_count mismatch")
        if report.get("created_count") != 75:
            failures.append(f"report{index}: created_count mismatch")
        if report.get("existing_count") != 0 or report.get("replaced_count") != 0:
            failures.append(f"report{index}: existing/replaced should be zero")
        if report.get("review_required_count") != 75:
            failures.append(f"report{index}: review_required_count mismatch")
        if report.get("smtp_send") != "not_available":
            failures.append(f"report{index}: smtp_send must be not_available")
        for item in report.get("items") or []:
            lead_id = str(item.get("lead_id") or "")
            if lead_id in readback_by_id:
                failures.append(f"{lead_id}: duplicate artifact readback")
            readback_by_id[lead_id] = item

    for row in rows:
        lead_id = row["lead_id"]
        item = readback_by_id.get(lead_id)
        if not item:
            failures.append(f"{lead_id}: missing creation readback")
            continue
        if item.get("to") != row.get("email"):
            failures.append(f"{lead_id}: artifact To mismatch")
        if item.get("subject") != row.get("subject"):
            failures.append(f"{lead_id}: artifact subject mismatch")
        if item.get("body") != row.get("body"):
            failures.append(f"{lead_id}: artifact body mismatch")
        if item.get("review_status") != "contact-basis":
            failures.append(f"{lead_id}: artifact review status mismatch")
        if item.get("outcome") != "created":
            failures.append(f"{lead_id}: artifact outcome is not created")

    metrics = {
        "requested_total": 150,
        "artifact_rows": len(rows),
        "artifact_readbacks": len(readback_by_id),
        "unique_lead_ids": len({norm(row.get("lead_id")) for row in rows}),
        "unique_emails": len({norm(row.get("email")) for row in rows}),
        "unique_domains": len({norm(row.get("official_domain_hint")) for row in rows}),
        "unique_companies": len({norm(row.get("company")) for row in rows}),
        "language_split": dict(language_split),
        "email_source_types": dict(email_source_types),
    }
    return rows, failures, metrics


def audit_mailbox(rows: list[dict]) -> tuple[list[str], dict]:
    failures: list[str] = []
    expected = {row["lead_id"]: row for row in rows}
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        select_folder(client, folder, readonly=True)
        status, data = client.search(None, "ALL")
        if status != "OK":
            raise RuntimeError("Could not list current mijn.host drafts")

        growth_messages: dict[str, list] = defaultdict(list)
        for message_id in (data[0] if data else b"").split():
            msg = fetch_message(client, message_id)
            lead_id = normalize_text(msg.get("X-Webactueel-Lead-ID", ""))
            if lead_id.startswith("growth-"):
                growth_messages[lead_id].append(msg)

        matched = 0
        for lead_id, row in expected.items():
            messages = growth_messages.get(lead_id) or []
            if len(messages) != 1:
                failures.append(f"{lead_id}: current mailbox count={len(messages)}, expected 1")
                continue
            actual = messages[0]
            _, expected_message = build_message(row)
            if not exact_message_matches(actual, expected_message):
                failures.append(f"{lead_id}: current mailbox exact content mismatch")
                continue
            matched += 1

        metrics = {
            "draft_folder": folder,
            "mailbox_growth_draft_count": sum(len(values) for values in growth_messages.values()),
            "mailbox_unique_growth_lead_ids": len(growth_messages),
            "final_set_current_exact_matches": matched,
            "final_set_current_expected": len(expected),
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
    args = parser.parse_args()

    if len(args.batch) != 2 or len(args.report) != 2:
        raise SystemExit("Final audit requires exactly two 75-draft artifacts")

    batch_payloads = [load(path) for path in args.batch]
    reports = [load(path) for path in args.report]
    config = load(args.config)

    rows, artifact_failures, metrics = audit_rows(batch_payloads, reports, config)
    mailbox_failures, mailbox_metrics = audit_mailbox(rows)
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
            f"failures={len(failures)} exact_mailbox={mailbox_metrics['final_set_current_exact_matches']}/150 "
            "automatic_send=false"
        )
        return 2

    print(
        "FINAL_LEADS_AUDIT=green "
        "total=150 unique_lead_ids=150 unique_emails=150 unique_domains=150 unique_companies=150 "
        f"nl={metrics['language_split'].get('nl', 0)} en={metrics['language_split'].get('en', 0)} "
        "exact_mailbox=150/150 automatic_send=false smtp_send=not_available"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
