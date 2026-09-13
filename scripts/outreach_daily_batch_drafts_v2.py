#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import outreach_daily_batch_drafts as base
from prospect_discovery import hosts_related
from prospect_target_policy import canonical_country


_ORIGINAL_CANDIDATE_ERRORS = base.candidate_errors
AGENTS = tuple(base.AGENT_HINTS)


def hardened_role_is_usable(address: str) -> bool:
    address = base._email(address)
    if "@" not in address:
        return False
    local = address.rsplit("@", 1)[0].casefold()
    compact = re.sub(r"[^a-z0-9]+", "", local)
    tokens = {token for token in re.split(r"[^a-z0-9]+", local) if token}
    blocked_compact = {re.sub(r"[^a-z0-9]+", "", item) for item in base.ROLE_MISMATCH_LOCAL_PARTS}
    blocked_tokens = {
        "hr", "humanresources", "careers", "career", "jobs", "job", "recruiting",
        "recruitment", "recruiter", "privacy", "legal", "billing", "payroll", "press",
        "media", "webmaster", "abuse", "postmaster",
    }
    if compact in blocked_compact or tokens.intersection(blocked_tokens):
        return False
    if compact.endswith("hr") and len(compact) <= 32:
        return False
    return True


def _draft_qualification_ok(candidate, qualification) -> bool:
    tier = base._text(qualification.get("tier")).upper()
    candidate_status = base._text(candidate.get("status")).casefold()
    qualification_status = base._text(qualification.get("status")).casefold()
    potential = base._score(qualification.get("customer_potential"))
    if potential < 6:
        return False
    if tier == "A":
        return candidate_status == "qualified" and qualification_status == "qualified"
    if tier == "B":
        return candidate_status == "hold" and qualification_status == "hold"
    return False


def _official_contact_ok(queue_row, candidate, contact) -> bool:
    website = base._text(candidate.get("website") or queue_row.get("website"))
    website_host = base.host_key(website)
    evidence_host = base.host_key(base._text(contact.get("source_url")))
    recipient = base._email(queue_row.get("email"))
    contact_email = base._email(contact.get("email"))
    return bool(
        website_host
        and evidence_host
        and hosts_related(website_host, evidence_host)
        and recipient
        and contact_email == recipient
        and base._text(contact.get("status")).casefold() in {"ready", "manual_review"}
        and base._text(contact.get("mx_status")).casefold() == "present"
    )


def hardened_candidate_errors(
    queue_row, *, agent_type: str, country: str, candidate, qualification, contact,
    source, lead_statuses, suppressed_emails, suppressed_domains,
):
    errors = _ORIGINAL_CANDIDATE_ERRORS(
        queue_row,
        agent_type=agent_type,
        country=country,
        candidate=candidate,
        qualification=qualification,
        contact=contact,
        source=source,
        lead_statuses=lead_statuses,
        suppressed_emails=suppressed_emails,
        suppressed_domains=suppressed_domains,
    )

    qualification_ok = bool(candidate and qualification and _draft_qualification_ok(candidate, qualification))
    if qualification_ok:
        removable = {
            "candidate is not qualified",
            "qualification status is not qualified",
            "qualification tier is not A",
            "customer potential is below A threshold",
        }
        errors = [item for item in errors if item not in removable]

        meta = base._parse_meta(queue_row.get("source"))
        tier = base._text(qualification.get("tier")).upper()
        if (
            meta
            and base._text(meta.get("qualification_tier")).upper() == tier
            and base._score(meta.get("customer_potential")) >= 6
        ):
            errors = [item for item in errors if item != "queue metadata does not prove A-tier qualification"]

    if contact and _official_contact_ok(queue_row, candidate, contact):
        contact_removable = {
            "recipient domain is not aligned to official website",
            "contact is not ready",
            "contact domain alignment is not proven",
        }
        errors = [item for item in errors if item not in contact_removable]

    queue_country = canonical_country(base._text(queue_row.get("country")))
    source_country = canonical_country(base._text(source.get("country"))) if source else ""
    if source_country and source_country != queue_country:
        errors.append("prospect source country conflicts with campaign")
    return errors


base._role_is_usable = hardened_role_is_usable
base.candidate_errors = hardened_candidate_errors


def _load_json(path: str, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _eligible_by_agent(country: str):
    spreadsheet_id = base.os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id or not base.os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("OUTREACH_SPREADSHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON are required")
    service = base.build_sheets_service()
    state = base._load_state(service, spreadsheet_id)
    output = {}
    for agent in AGENTS:
        eligible, _ = base.eligible_candidates(
            state[0], agent_type=agent, country=country, candidates=state[1], qualifications=state[2],
            contacts=state[3], sources=state[4], leads=state[5], suppressions=state[6],
        )
        output[agent] = eligible
    return output


def _auto_plan(target: int, country: str):
    by_agent = _eligible_by_agent(country)
    combined = []
    for agent, items in by_agent.items():
        for item in items:
            combined.append((item.score, item.lead_id, agent, item))
    combined.sort(key=lambda row: (-row[0], row[1]))

    chosen = []
    seen_leads = set()
    seen_domains = set()
    seen_emails = set()
    for _score, _lead_id, agent, item in combined:
        domain = base.host_key(item.website)
        if item.lead_id in seen_leads or domain in seen_domains or item.email in seen_emails:
            continue
        chosen.append((agent, item))
        seen_leads.add(item.lead_id)
        seen_domains.add(domain)
        seen_emails.add(item.email)
        if len(chosen) >= target:
            break

    counts = {agent: 0 for agent in AGENTS}
    for agent, _item in chosen:
        counts[agent] += 1
    return chosen, counts


def _run_chunks(*, target: int, agent_type: str, country: str, run_key: str) -> int:
    remaining = target
    all_selected = []
    all_receipts = []
    chunk_no = 0

    while remaining > 0:
        if agent_type == "auto":
            chosen, counts = _auto_plan(remaining, country)
            if not chosen:
                break
            plan = [(agent, count) for agent, count in counts.items() if count]
        else:
            plan = [(agent_type, remaining)]

        progressed = 0
        for agent, wanted in plan:
            left = wanted
            while left > 0:
                chunk_no += 1
                chunk = min(50, left)
                rc = base.process(
                    target=chunk,
                    agent_type=agent,
                    country=country,
                    run_key=f"{run_key}.c{chunk_no}",
                    count_only=False,
                )
                if rc != 0:
                    return rc
                selection = _load_json("daily-draft-selection.json", {})
                receipts = _load_json("daily-draft-receipts.json", [])
                selected = selection.get("selected", [])
                if not selected:
                    left = 0
                    continue
                for row in selected:
                    row["agent_type"] = agent
                all_selected.extend(selected)
                all_receipts.extend(receipts)
                made = len(selected)
                progressed += made
                remaining -= made
                left -= made
                if made < chunk:
                    left = 0
                if remaining <= 0:
                    break
            if remaining <= 0:
                break

        if progressed == 0:
            break

    base._write_json("daily-draft-selection.json", {
        "run_key": run_key,
        "agent_type": agent_type,
        "country": canonical_country(country),
        "target": target,
        "selected": all_selected,
        "selected_count": len(all_selected),
        "send_permission": "none",
        "transport": "IMAP_DRAFT_ONLY",
    })
    base._write_json("daily-draft-receipts.json", all_receipts)

    if len(all_selected) != target:
        raise RuntimeError(f"only {len(all_selected)} eligible unique leads available for target {target}")
    print(
        f"DAILY_LEAD_DRAFTS=green selected={len(all_selected)} drafts={len(all_receipts)} "
        f"target={target} agent={agent_type} smtp_send=not_invoked"
    )
    return 0


def process(*, target: int, agent_type: str, country: str, run_key: str, count_only: bool = False) -> int:
    if target < 1:
        raise ValueError("target must be at least 1")
    if agent_type != "auto" and agent_type not in AGENTS:
        raise ValueError("agent_type must be auto or a supported agent")
    if not base.SAFE_RUN_KEY.fullmatch(run_key):
        raise ValueError("run_key contains unsupported characters")

    if count_only:
        if agent_type == "auto":
            chosen, _counts = _auto_plan(target, country)
            ready = len(chosen)
        else:
            by_agent = _eligible_by_agent(country)
            ready = len(by_agent.get(agent_type, []))
        print(f"DAILY_DRAFT_READY={ready} target={target} agent={agent_type} country={canonical_country(country)}")
        return 0

    return _run_chunks(target=target, agent_type=agent_type, country=country, run_key=run_key)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Create any requested number of idempotent mijn.host drafts without SMTP send permission.")
    parser.add_argument("--target", type=int, default=200)
    parser.add_argument("--agent-type", default="auto")
    parser.add_argument("--country", required=True)
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--count-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        return process(
            target=args.target,
            agent_type=args.agent_type.strip().casefold(),
            country=args.country.strip(),
            run_key=args.run_key.strip(),
            count_only=args.count_only,
        )
    except (RuntimeError, ValueError, OSError, base.imaplib.IMAP4.error) as exc:
        base._write_json("daily-draft-error.json", {
            "status": "blocked", "error": str(exc), "send_permission": "none", "smtp_send": "not_invoked",
        })
        print(f"DAILY_LEAD_DRAFTS=blocked detail={exc} smtp_send=not_invoked", file=base.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
