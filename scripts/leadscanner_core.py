#!/usr/bin/env python3
"""Leadscanner core: research -> verified contact -> quality-checked mijn.host draft.

No Instantly imports, SMTP sends, scheduled outreach, or public prospect output.
Only the bounded public_audit is permitted in a public GitHub repository.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
import os
import re


from cold_stages import (
    filter_discovery, verify_candidates, research_candidates,
    suppress_previously_used_contact_emails,
)
from dedupe_preflight import load_registry_values, match_candidate, candidate_identity, domains_match
from outreach_stages import select_reasons, choose_value_actions, generate_mails
from overture_discovery import discover
from review_draft_stages import prepare_review_batch, audit_exact_readback
from myhost_draft import create_drafts
from update_dedupe_registry import (
    DEFAULT_SHEET_NAME, DEFAULT_SPREADSHEET_ID,
    check_registry_access, update_registry,
    _authorized_session, read_live_values,
)

MAX_DISCOVERY = 5000
MAX_RESEARCH = 100
class SafeRunError(RuntimeError):
    """A fixed diagnostic stage, never a provider URL, response or recipient."""
    pass


def fetch_registry() -> list[dict]:
    """Read historical suppressions only via the authenticated Sheets API.

    Never use a public CSV export link or place raw registry contents on disk.
    """
    session, _account = _authorized_session(read_only=True)
    values = read_live_values(session, DEFAULT_SPREADSHEET_ID, DEFAULT_SHEET_NAME)
    return load_registry_values(values)


def revalidate_drafts(batch: dict, registry: list[dict]) -> tuple[dict, int]:
    """Recheck current suppression for every draft immediately before storage."""
    rows = batch.get("rows")
    if not isinstance(rows, list) or len(rows) > MAX_RESEARCH:
        raise ValueError("draft_batch_invalid")
    if any(row.get("status") != "review_draft" or row.get("automatic_send") is not False
           or row.get("contact_basis_status") != "review_required" for row in rows):
        raise ValueError("unreviewable_draft")
    ready, suppressed, seen = [], 0, set()
    for row in rows:
        identity = {
            "company": row.get("company"),
            "website": row.get("website"),
            "official_domain": row.get("official_domain"),
            "email": row.get("email"),
            "lead_id": row.get("lead_id"),
        }
        if not row.get("lead_id") or row["lead_id"] in seen:
            raise ValueError("duplicate_draft_identity")
        seen.add(row["lead_id"])
        if match_candidate(identity, registry):
            suppressed += 1
            continue
        # Two different leads can resolve to the same official domain or
        # shared contact mailbox after crawling. Never prepare duplicate
        # drafts even when their discovery identities were different.
        normalized = candidate_identity(identity)
        if any(
            normalized["emails"] & previous["emails"]
            or normalized["lead_ids"] & previous["lead_ids"]
            or (
                normalized["company"] and
                normalized["company"] == previous["company"]
            )
            or any(
                domains_match(left, right)
                for left in normalized["domains"] for right in previous["domains"]
            )
            for previous in (candidate_identity(existing) for existing in ready)
        ):
            suppressed += 1
            continue
        ready.append(row)
    return {
        "rows": ready,
        "draft_candidate_count": len(ready),
        "review_draft_count": len(ready),
        "safety": {"automatic_send": False, "smtp_available": False,
                   "human_review_required": True},
    }, suppressed


def _params_valid(mode: str, region: str, keywords: list[str],
                  radius_km: float, discovery_limit: int, verify_limit: int) -> bool:
    return (
        mode in {"public_audit", "drafts"}
        and 1 <= len(region) <= 120
        and 1 <= len(keywords) <= 20
        and all(1 <= len(k) <= 120 and k.strip() == k for k in keywords)
        and 0.5 <= radius_km <= 50
        and 1 <= discovery_limit <= MAX_DISCOVERY
        and 1 <= verify_limit <= MAX_RESEARCH
    )


def run(*, mode: str, region: str,
        keywords: list[str], radius_km: float,
        discovery_limit: int, verify_limit: int,
        repository_private: bool) -> dict:
    if not _params_valid(mode, region, keywords, radius_km, discovery_limit, verify_limit):
        raise SafeRunError("inputs")
    if mode == "drafts" and not repository_private:
        raise SafeRunError("privacy")
    if mode == "drafts" and not os.environ.get("OUTREACH_MAIL_PASSWORD"):
        raise SafeRunError("mailbox_credentials")

    stage = "registry"
    try:
        registry = fetch_registry()
        stage = "discovery"
        raw = discover(
            region=region, bbox=None, radius_km=radius_km, keywords=keywords,
            max_results=discovery_limit, require_website=True, probe_websites=False,
        )
        stage = "filter"
        filtered = filter_discovery(raw)
        stage = "dedupe"
        kept = [candidate for candidate in filtered["candidates"]
                if not match_candidate(candidate, registry)]
        dropped = len(filtered["candidates"]) - len(kept)
        dedupe = {"status": "green", "kept": kept, "kept_count": len(kept),
                  "excluded_count": dropped}
        stage = "website"
        verified = verify_candidates(dedupe, limit=verify_limit, max_workers=8)
        stage = "research"
        researched = research_candidates(verified, limit=verify_limit, max_workers=6)
        stage = "contact_dedupe"
        researched = suppress_previously_used_contact_emails(researched, registry)
        stage = "priorities"
        reasons = select_reasons(researched)
        stage = "value"
        values = choose_value_actions(reasons)
        stage = "mail_quality"
        mail = generate_mails(values)
        stage = "draft_validation"
        batch = prepare_review_batch(mail)

        report = {
            "schema": "leadscanner-core/1.0",
            "status": "green",
            "mode": mode,
            "counts": {
                "discovered": int(raw.get("candidate_count") or 0),
                "after_filters": len(filtered["candidates"]),
                "previously_known": dropped,
                "after_dedupe": len(kept),
                "websites_verified": int(verified.get("ready_for_research_count") or 0),
                "websites_researched": int(researched.get("research_ready_count") or 0),
                "contacts_found": int(researched.get("contacts_found_count") or 0),
                "mail_quality_approved": len(batch["rows"]),
                "mail_quality_holds": sum(
                    1 for x in mail.get("candidates", [])
                    if x.get("mail_status") == "hold"),
                "suppressed_at_storage": 0,
                "draft_created": 0,
                "draft_existing_exact": 0,
                "registry_confirmed": 0,
            },
            "automatic_send": False,
            "smtp_available": False,
            "recipient_data_exposed": False,
            "public_artifacts_uploaded": False,
        }

        if mode == "drafts":
            # Freshness matters: other workflows may write to dedupe in flight.
            stage = "fresh_dedupe"
            fresh_registry = fetch_registry()
            ready, suppressed = revalidate_drafts(batch, fresh_registry)
            report["counts"]["suppressed_at_storage"] = suppressed
            if ready["rows"]:
                stage = "registry_preflight"
                check_registry_access(
                    spreadsheet_id=DEFAULT_SPREADSHEET_ID,
                    sheet_name=DEFAULT_SHEET_NAME,
                )
                stage = "myhost_imap"
                saved = create_drafts(ready, reject_changed_existing=True)
                stage = "myhost_readback"
                proof = audit_exact_readback(ready, saved)
                stage = "registry_closure"
                completed = update_registry(
                    proof,
                    spreadsheet_id=DEFAULT_SPREADSHEET_ID,
                    sheet_name=DEFAULT_SHEET_NAME,
                )
                if completed.get("exact_readback") is not True:
                    raise RuntimeError("registry_not_confirmed")
                report["counts"]["draft_created"] = int(saved["created_count"])
                report["counts"]["draft_existing_exact"] = int(saved["existing_count"])
                report["counts"]["registry_confirmed"] = (
                    int(completed["appended_count"])
                    + int(completed["already_present_count"])
                )
                if (
                    report["counts"]["draft_created"]
                    + report["counts"]["draft_existing_exact"]
                    != report["counts"]["registry_confirmed"]
                ):
                    raise RuntimeError("draft_registry_count_mismatch")
            report["status"] = "green" if ready["rows"] else "yellow"

        if mode == "public_audit" and not batch["rows"]:
            report["status"] = "yellow"
        return report
    except SafeRunError:
        raise
    except Exception:
        # Never print provider errors, addresses, site text or email bodies.
        raise SafeRunError(stage) from None


def main() -> int:
    parser = argparse.ArgumentParser(description="Research, quality check and prepare mijn.host drafts; never send")
    parser.add_argument("--mode", choices=("public_audit", "drafts"), required=True)
    parser.add_argument("--region", default="Amsterdam")
    parser.add_argument("--keywords", default="fietsenwinkel,bloemist,kapsalon")
    parser.add_argument("--radius-km", type=float, default=5)
    parser.add_argument("--discovery-limit", type=int, default=60)
    parser.add_argument("--verify-limit", type=int, default=60)
    args = parser.parse_args()
    keywords = list(dict.fromkeys(
        value.strip() for value in re.split(r"[,\n]+", args.keywords)
        if value.strip()
    ))
    try:
        # Suppress library output: external content must never reach public logs.
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            report = run(
                mode=args.mode,
                region=args.region, keywords=keywords, radius_km=args.radius_km,
                discovery_limit=args.discovery_limit, verify_limit=args.verify_limit,
                repository_private=os.environ.get("REPOSITORY_IS_PRIVATE") == "true",
            )
    except SafeRunError as exc:
        print(json.dumps({"schema": "leadscanner-core/1.0",
                          "status": "red", "failed_stage": str(exc),
                          "automatic_send": False, "recipient_data_exposed": False,
                          "public_artifacts_uploaded": False}))
        return 1
    except Exception:
        print(json.dumps({"schema": "leadscanner-core/1.0", "status": "red",
                          "failed_stage": "bootstrap",
                          "automatic_send": False, "recipient_data_exposed": False,
                          "public_artifacts_uploaded": False}))
        return 1
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
