#!/usr/bin/env python3
"""Read-only LIVE website preview that is safe to run in a public repository.

All prospect names, addresses, URLs, observations, email copy, review tokens
and snapshots exist only in the runner's memory (and in short-lived Overture /
registry temp files). They NEVER go to logs, Actions artifacts, summaries,
the registry, Instantly or a mailbox. The only published result is counts.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import re
import statistics
import tempfile

import requests

from cold_stages import filter_discovery, verify_candidates, research_candidates
from cold_run_manifest import build_manifest
from dedupe_preflight import load_registry, match_candidate
from funnel_metrics import build_funnel
from outreach_stages import (
    select_reasons, choose_value_actions, generate_mails,
    generate_sequence_facts, review_findings,
)
from overture_discovery import discover
from preview_snapshot import build_snapshot, validate_snapshot
from review_draft_stages import prepare_review_batch
from review_selection import build_review_queue, review_token, select_approved

REGISTRY_MAX_BYTES = 8_000_000
MAX_DISCOVERY = 80
MAX_VERIFY = 20
MAX_WORKERS = 6
MAX_RADIUS_KM = 12.0
# Only enum-like status codes, never untrusted text, may enter public results.
SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,49}$")


class PreviewFailed(RuntimeError):
    def __init__(self, stage: str):
        super().__init__("public_live_preview_failed")
        self.stage = stage


def safe_counts(items: list[object] | tuple[object, ...]) -> dict[str, int]:
    out: Counter[str] = Counter()
    for item in items:
        value = str(item or "").casefold()
        # Unknown values are counted, never reproduced.
        out[value if SAFE_CODE.fullmatch(value) else "other"] += 1
    return dict(sorted(out.items()))


def fetch_registry_rows(*, registry_url: str, session=requests) -> list[dict]:
    # Fail closed: no website research without the retained historical exclusions.
    if not registry_url.startswith("https://docs.google.com/spreadsheets/"):
        raise ValueError("registry_url_must_be_canonical_https_sheet")
    response = session.get(
        registry_url,
        timeout=(10, 35),
        headers={"User-Agent": "LeadscannerPublicPreview/1.0"},
    )
    response.raise_for_status()
    raw = response.content
    if not isinstance(raw, bytes) or not 0 < len(raw) <= REGISTRY_MAX_BYTES:
        raise ValueError("registry_unavailable_or_too_large")
    with tempfile.TemporaryDirectory(prefix="leadscanner-registry-") as directory:
        target = Path(directory) / "registry.csv"
        target.write_bytes(raw)
        return load_registry(target)


def validate_review_integrity(*, batch: dict, queue: dict, official: list[dict]) -> dict:
    rows = batch.get("rows") or []
    items = queue.get("items") or []
    if len(items) != len(rows):
        raise ValueError("review_queue_count_drift")
    if any(row.get("automatic_send") is not False for row in rows):
        raise ValueError("review_rows_must_not_send")
    if any(row.get("contact_basis_status") != "review_required" for row in rows):
        raise ValueError("review_must_require_human_decision")
    hashes_checked = 0
    for row, item in zip(rows, items):
        # Pure read-only equality check, NOT a decision to approve a recipient.
        if review_token(row) != item.get("approval_token"):
            raise ValueError("review_approval_token_mismatch")
        source = review_findings(row.get("selected_findings"), row.get("official_domain"))
        if source != item.get("selected_findings"):
            raise ValueError("review_source_binding_mismatch")
        hashes_checked += 1
    stale_rejected = 0
    if rows:
        altered = deepcopy(batch)
        first = altered["rows"][0]
        if first.get("selected_findings"):
            first["selected_findings"][0]["observation"] += " Veranderd."
        else:
            first["verified_observation"] += " Veranderd."
        # This must raise BEFORE any external approval or staging action.
        try:
            select_approved(altered, items[0]["approval_token"])
        except ValueError as exc:
            if "unknown_or_stale_approval_token" not in str(exc):
                raise
            stale_rejected = 1
        else:
            raise ValueError("stale_review_approval_was_accepted")
    return {
        "tokens_content_bound": hashes_checked,
        "tampered_approval_rejected": stale_rejected,
        "approved_by_human": 0,
        "external_approval_or_staging": False,
    }


def audit_live_findings(*, researched: dict, reasons: dict, mail: dict) -> dict:
    findings = []
    sites = []
    for candidate in reasons.get("candidates") or []:
        if candidate.get("outreach_status") != "ready":
            continue
        source = review_findings(candidate.get("selected_findings"), candidate.get("official_domain"))
        if not 1 <= len(source) <= 6:
            raise ValueError("selection_must_have_one_to_six_findings")
        scores = [item.get("score") for item in source]
        if any(type(score) is not int for score in scores) or scores != sorted(scores, reverse=True):
            raise ValueError("findings_not_ranked_by_evidence")
        sites.append(len(source))
        findings.extend(source)
    ready_mails = [x for x in (mail.get("candidates") or []) if x.get("mail_status") == "ready_for_human_review"]
    lengths = [len(str(candidate.get("body") or "").split()) for candidate in ready_mails]
    if len(ready_mails) != mail.get("ready_for_human_review_count"):
        raise ValueError("reviewed_mail_count_drift")
    if any(not 1 <= words <= 155 for words in lengths):
        raise ValueError("reviewed_mail_length_out_of_bounds")
    return {
        "website_pages_read": sum(len(x.get("researched_urls") or []) for x in (researched.get("candidates") or [])),
        "first_party_observations": sum(len(x.get("evidence_candidates") or []) for x in (researched.get("candidates") or [])),
        "ranked_findings": len(findings),
        "sites_with_ranked_findings": len(sites),
        "findings_per_site": safe_counts([str(n) for n in sites]),
        "finding_priorities": safe_counts([x.get("priority") for x in findings]),
        "finding_categories": safe_counts([x.get("category") for x in findings]),
        "mail_languages": safe_counts([x.get("language") for x in ready_mails]),
        "mail_words_min": min(lengths, default=0),
        "mail_words_median": int(statistics.median(lengths)) if lengths else 0,
        "mail_words_max": max(lengths, default=0),
        "mail_quality_holds": safe_counts([
            reason
            for candidate in (mail.get("candidates") or [])
            if candidate.get("value_action_status") == "proposed"
            and candidate.get("mail_status") != "ready_for_human_review"
            for reason in (candidate.get("copy_validation_reasons") or ["other"])
        ]),
    }


def run_live_preview(
    *,
    registry_url: str,
    region: str,
    keywords: list[str],
    radius_km: float,
    discovery_limit: int,
    verify_limit: int,
    run_id: int,
    run_number: int,
    head_sha: str,
) -> dict:
    """Run the original production stages, only keeping a privacy-safe audit."""
    if (
        not 1 <= discovery_limit <= MAX_DISCOVERY
        or not 1 <= verify_limit <= MAX_VERIFY
        or not 0.5 <= radius_km <= MAX_RADIUS_KM
        or not 1 <= len(keywords) <= 12
        or not 1 <= len(region) <= 120
        or any(not 1 <= len(x) <= 120 for x in keywords)
        or run_id <= 0 or run_number <= 0
        or not re.fullmatch(r"[0-9a-f]{40}", head_sha)
    ):
        raise PreviewFailed("inputs")

    stage = "registry"
    try:
        registry = fetch_registry_rows(registry_url=registry_url)
        stage = "discovery"
        raw = discover(
            region=region, bbox=None, radius_km=radius_km, keywords=keywords,
            max_results=discovery_limit, require_website=True, probe_websites=False,
        )
        stage = "filters"
        filtered = filter_discovery(raw)
        stage = "dedupe"
        kept, excluded = [], []
        for candidate in filtered["candidates"]:
            match = match_candidate(candidate, registry)
            if match:
                excluded.append({"candidate": candidate, "dedupe_match": match})
            else:
                kept.append(candidate)
        dedupe = {
            "status": "green", "registry_exclusion_count": len(registry),
            "input_count": len(filtered["candidates"]),
            "excluded_count": len(excluded), "kept_count": len(kept),
            "kept": kept, "excluded": excluded,
        }

        stage = "verification"
        verified = verify_candidates(dedupe, limit=verify_limit, max_workers=MAX_WORKERS)
        stage = "research"
        researched = research_candidates(verified, limit=verify_limit, max_workers=4)
        stage = "prioritization"
        reasons = select_reasons(researched)
        stage = "proposal"
        values = choose_value_actions(reasons)
        stage = "concepts"
        mail = generate_mails(values)
        stage = "review"
        batch = prepare_review_batch(mail)
        queue = build_review_queue(batch)
        integrity = validate_review_integrity(batch=batch, queue=queue, official=kept)
        research_quality = audit_live_findings(researched=researched, reasons=reasons, mail=mail)

        stage = "fact_only"
        facts = generate_sequence_facts(values)
        facts_batch = prepare_review_batch(facts)
        facts_queue = build_review_queue(facts_batch)
        if facts_queue["review_candidate_count"] != facts["ready_for_human_review_count"]:
            raise ValueError("fact_only_review_count_mismatch")
        if any(row.get("subject") or row.get("body") for row in facts_batch["rows"]):
            raise ValueError("fact_only_must_not_generate_mail")

        stage = "report"
        metrics = build_funnel(
            raw=raw, filtered=filtered, dedupe=dedupe, verified=verified,
            research=researched, reasons=reasons, values=values, mail=mail,
        )
        request = {
            "execution_mode": "preview",
            "preview_copy_mode": "reviewed_mail",
            "region": region, "keywords": keywords,
            "radius_km": radius_km,
            "target_candidates": discovery_limit,
            "verify_limit": verify_limit,
        }
        manifest = build_manifest(
            mode="preview", request=request, filtered=filtered,
            dedupe=dedupe, verified=verified, research=researched,
            reasons=reasons, values=values, mail=mail,
            draft_batch=batch, review_queue=queue, funnel=metrics,
        )
        stage = "preview_snapshot"
        snapshot = build_snapshot(
            request=request, batch=batch, queue=queue, manifest=manifest,
            source={
                "repository": "Yolol100/Leadscanner",
                "run_id": run_id, "run_number": run_number, "head_sha": head_sha,
            },
        )
        validate_snapshot(snapshot, repository="Yolol100/Leadscanner", run_id=run_id, head_sha=head_sha)

        # This object is the ONLY exported product. Do not insert original
        # candidate data, body copy, source URLs, review tokens or hashes.
        counts = metrics["counts"]
        report = {
            "schema": "leadscanner-public-preview-audit/1.0",
            "status": "green" if queue["review_candidate_count"] else "yellow",
            "live_source": "Overture and first-party public websites",
            "execution": "live_read_only_public",
            "registry_dedupe_active": True,
            "registry_suppression_rows": len(registry),
            "counts": {
                "discovered_with_websites": counts["discovery_raw"],
                "after_filters": counts["after_cheap_filters"],
                "excluded_historical": len(excluded),
                "after_dedupe": counts["after_dedupe"],
                "verified_contacts": counts["verified_for_research"],
                "researched_sites": counts["research_ready"],
                "ready_outreach_reasons": counts["outreach_ready"],
                "review_ready_emails": counts["mail_ready"],
                "review_queue": queue["review_candidate_count"],
                "fact_only_review_queue": facts_queue["review_candidate_count"],
            },
            "holds": {
                "verification": safe_counts([
                    x.get("contact_status") for x in verified.get("candidates") or []
                    if x.get("ready_for_research") is not True
                ]),
                "research": safe_counts([
                    x.get("research_status") for x in researched.get("candidates") or []
                    if x.get("research_status") != "ready"
                ]),
                "outreach": safe_counts([
                    x.get("outreach_hold_reason") for x in reasons.get("candidates") or []
                    if x.get("outreach_status") != "ready"
                ]),
            },
            "quality": research_quality,
            "review_integrity": integrity,
            "snapshot_in_memory_valid": True,
            "public_artifacts_uploaded": False,
            "contains_real_recipient_data": False,
            "personally_identifiable_output": False,
            "emails_sent": 0,
            "campaigns_activated": 0,
            "drafts_stored": 0,
            "registry_writes": 0,
        }
        return report
    except Exception:
        # Never put a third-party URL, contact address, exception message,
        # or original HTML/response in public Actions logs.
        raise PreviewFailed(stage) from None


def main() -> int:
    parser = argparse.ArgumentParser(description="Private-in-memory public live preview")
    parser.add_argument("--region", default="Amsterdam")
    parser.add_argument("--keywords", default="fietsenwinkel,bloemist,kapsalon")
    parser.add_argument("--radius-km", type=float, default=5.0)
    parser.add_argument("--discovery-limit", type=int, default=60)
    parser.add_argument("--verify-limit", type=int, default=16)
    args = parser.parse_args()
    keywords = list(dict.fromkeys(x.strip() for x in re.split(r"[,\n]+", args.keywords) if x.strip()))
    try:
        # Suppress all helper/library chatter, including exceptions with URLs.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = run_live_preview(
                registry_url=os.getenv("DEDUPE_REGISTRY_CSV_URL", ""),
                region=args.region, keywords=keywords,
                radius_km=args.radius_km,
                discovery_limit=args.discovery_limit, verify_limit=args.verify_limit,
                run_id=int(os.getenv("GITHUB_RUN_ID", "123456")),
                run_number=int(os.getenv("GITHUB_RUN_NUMBER", "1")),
                head_sha=os.getenv("GITHUB_SHA", "a" * 40),
            )
    except PreviewFailed as exc:
        print(json.dumps({
            "schema": "leadscanner-public-preview-audit/1.0",
            "status": "red", "failed_stage": exc.stage,
            "recipient_data_exposed": False, "emails_sent": 0,
            "public_artifacts_uploaded": False,
        }))
        return 1
    except Exception:
        print(json.dumps({
            "schema": "leadscanner-public-preview-audit/1.0",
            "status": "red", "failed_stage": "bootstrap",
            "recipient_data_exposed": False, "emails_sent": 0,
            "public_artifacts_uploaded": False,
        }))
        return 1
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
