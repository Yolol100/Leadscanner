#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Mapping

import outreach_daily_batch_drafts as base
from outreach_draft_first_user_contract import initial_copy_errors
from outreach_sender import build_sheets_service, get_values, rows_from_values
from prospect_discovery import host_key, hosts_related
from prospect_target_policy import canonical_country

COPY_CONTRACT = "draft_first_v14"
AUTOMATION_ID = "agent_sales_draft_first_v14"
NET_NEW_AGENTS = {"front_desk_sales", "quote_intake", "review_concierge", "customer_support", "commerce"}
GENERIC_NAV_ANCHORS = {
    "skip to content", "home", "homepage", "menu", "main menu", "navigation",
    "learn more", "read more", "about", "about us", "contact", "contact us",
}


def text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def email(value: object) -> str:
    return text(value).casefold()


def parse_meta(row: Mapping[str, object]) -> dict:
    raw = str(row.get("source", ""))
    if not raw.startswith("agent_offer:"):
        return {}
    try:
        data = json.loads(raw.split(":", 1)[1])
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def meaningful_personalization(meta: Mapping[str, object], website: str) -> tuple[bool, str]:
    anchor = text(meta.get("personalization_anchor") or meta.get("business_process"))
    observation = text(meta.get("observation"))
    evidence_url = text(meta.get("evidence_url"))
    domain = host_key(website)
    if not observation or not text(meta.get("value_asset_summary")):
        return False, "missing observation/value"
    if not evidence_url or not hosts_related(host_key(evidence_url), domain):
        return False, "personalization evidence is not on official site"
    if not anchor:
        return False, "missing personalization anchor"
    normalized = re.sub(r"\s+", " ", anchor).strip().casefold().rstrip(".:;!?")
    if normalized in GENERIC_NAV_ANCHORS or normalized.startswith("skip to content"):
        return False, "generic navigation personalization anchor"
    if not re.search(r"[a-zA-Z]{3,}", anchor):
        return False, "non-semantic personalization anchor"
    observation_normalized = re.sub(r"\s+", " ", observation).strip().casefold().rstrip(".:;!?")
    if observation_normalized in GENERIC_NAV_ANCHORS or observation_normalized.startswith("skip to content"):
        return False, "generic navigation observation"
    return True, ""


def eligible(queue_rows, suppressions, *, country: str):
    suppressed_emails, suppressed_domains = base._suppression_sets(suppressions)
    accepted = []
    rejected = {}
    seen_domains = set()
    seen_emails = set()
    for row in queue_rows:
        lead_id = text(row.get("lead_id"))
        if not lead_id:
            continue
        meta = parse_meta(row)
        website = text(row.get("website"))
        domain = host_key(website)
        address = email(row.get("email"))
        address_domain = address.rsplit("@", 1)[1] if "@" in address else ""
        errors = []
        if text(row.get("status")).casefold() not in {"manual_review", "prepared"}:
            errors.append("queue status not draft-first eligible")
        if text(row.get("compliance_status")).casefold() != "manual_review":
            errors.append("draft-first requires manual_review compliance state")
        if canonical_country(text(row.get("country"))) != canonical_country(country):
            errors.append("country mismatch")
        if any(text(row.get(field)) for field in base.TERMINAL_QUEUE_FIELDS):
            errors.append("terminal send/reply/bounce evidence")
        if not address or "@" not in address or not base._role_is_usable(address):
            errors.append("invalid or blocked mailbox role")
        if address in suppressed_emails or address_domain in suppressed_domains:
            errors.append("suppressed")
        if not meta or text(meta.get("automation")) != AUTOMATION_ID or text(meta.get("copy_contract")) != COPY_CONTRACT:
            errors.append("draft-first metadata missing/stale")
        agent = text(meta.get("primary_agent_type") or meta.get("agent_type")).casefold()
        if agent not in NET_NEW_AGENTS:
            errors.append("unsupported net-new agent")
        if text(meta.get("draft_fit")).upper() not in {"A", "B"}:
            errors.append("draft fit is not A/B")
        try:
            score = int(str(meta.get("customer_potential", 0)))
        except (TypeError, ValueError):
            score = 0
        if score < 6:
            errors.append("customer potential below draft-first threshold")
        source_url = text(meta.get("email_source_url"))
        if not source_url or not hosts_related(host_key(source_url), domain):
            errors.append("email is not evidenced on official site")
        if text(meta.get("contact_mx_status")).casefold() == "missing":
            errors.append("recipient domain MX missing")
        personal_ok, personal_error = meaningful_personalization(meta, website)
        if not personal_ok:
            errors.append(personal_error)
        errors.extend(f"copy: {item}" for item in initial_copy_errors(text(row.get("subject")), str(row.get("body") or "")))
        if domain in seen_domains:
            errors.append("duplicate domain in batch")
        if address in seen_emails:
            errors.append("duplicate email in batch")
        if errors:
            rejected[lead_id] = errors
            continue
        accepted.append(base.Candidate(
            lead_id=lead_id, company=text(row.get("company")), website=website, email=address,
            subject=text(row.get("subject")), body=str(row.get("body") or ""),
            country=canonical_country(country),
            anchor=text(meta.get("personalization_anchor") or meta.get("business_process")), score=score,
        ))
        seen_domains.add(domain)
        seen_emails.add(address)
    accepted.sort(key=lambda item: (-item.score, item.lead_id))
    return accepted, rejected


def run(*, target: int, country: str, run_key: str, count_only: bool) -> int:
    spreadsheet_id = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id or not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("OUTREACH_SPREADSHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON are required")
    service = build_sheets_service()
    _, queue_rows = rows_from_values(get_values(service, spreadsheet_id, base.QUEUE_SHEET))
    _, suppression_rows = rows_from_values(get_values(service, spreadsheet_id, base.SUPPRESSION_SHEET))
    candidates, rejected = eligible(queue_rows, suppression_rows, country=country)
    ready = len(candidates)
    if count_only:
        print(f"DRAFT_FIRST_READY={ready} target={target} country={canonical_country(country)}")
        return 0
    if ready < target:
        raise RuntimeError(f"draft-first target not ready: ready={ready} target={target}")
    selected = candidates[:target]
    selection = {
        "run_key": run_key, "target": target, "country": canonical_country(country),
        "copy_contract": COPY_CONTRACT, "send_permission": "none", "smtp_send": "not_invoked",
        "selected": [
            {"lead_id": item.lead_id, "company": item.company, "website": item.website,
             "website_host": host_key(item.website), "email": item.email, "score": item.score}
            for item in selected
        ],
        "rejected_count": len(rejected),
    }
    with open("daily-draft-selection.json", "w", encoding="utf-8") as handle:
        json.dump(selection, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")

    if not os.getenv("OUTREACH_MAIL_PASSWORD", "").strip():
        raise RuntimeError("OUTREACH_MAIL_PASSWORD is required for IMAP draft creation")
    daily_limit = int(os.getenv("OUTREACH_DAILY_LIMIT", "50") or "50")
    mailboxes = base.enabled_mailboxes(base.load_mailboxes_from_env(mode="validate", default_daily_limit=daily_limit))
    mailbox_id = os.getenv("OUTREACH_DRAFT_MAILBOX_ID", "primary").strip() or "primary"
    mailbox = next((item for item in mailboxes if item.mailbox_id == mailbox_id), None)
    if mailbox is None:
        raise RuntimeError(f"configured draft mailbox not found: {mailbox_id}")

    imap = None
    receipts = []
    try:
        imap, folder = base._open_imap(mailbox)
        for item in selected:
            receipts.append(base._append_or_readback(imap, folder, mailbox, item))
        base._verify_receipts(imap, folder, receipts)
    finally:
        if imap is not None:
            try:
                imap.logout()
            except Exception:
                pass
    base._mark_concepts(service, spreadsheet_id, selected)
    with open("daily-draft-receipts.json", "w", encoding="utf-8") as handle:
        json.dump([receipt.__dict__ for receipt in receipts], handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    appended = sum(1 for receipt in receipts if receipt.action == "appended")
    existing = sum(1 for receipt in receipts if receipt.action == "existing")
    print(f"DRAFT_FIRST_DRAFTS=green selected={len(selected)} drafts={len(receipts)} appended={appended} existing={existing} target={target} folder={folder} queue=manual_review send_permission=none smtp_send=not_invoked")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, required=True)
    parser.add_argument("--country", required=True)
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--count-only", action="store_true")
    args = parser.parse_args(argv)
    if args.target < 1 or args.target > 50:
        print("DRAFT_FIRST_DRAFTS=blocked detail=target must be 1..50 smtp_send=not_invoked", file=sys.stderr)
        return 2
    try:
        return run(target=args.target, country=args.country, run_key=args.run_key, count_only=args.count_only)
    except (RuntimeError, ValueError, IndexError) as exc:
        print(f"DRAFT_FIRST_DRAFTS=blocked detail={exc} smtp_send=not_invoked", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
