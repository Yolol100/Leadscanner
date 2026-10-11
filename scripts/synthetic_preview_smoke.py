#!/usr/bin/env python3
"""Full synthetic, offline preview smoke test; no network or personal data.

Exercises ranked research findings, reviewed copy, fact-only review, exact
approvals, sealed snapshots and operator summaries without sending or staging.
"""
from __future__ import annotations

import copy
import io
import json
import os
import socket
import zipfile
from unittest.mock import patch

from cold_run_manifest import build_manifest
from outreach_stages import (
    choose_value_actions, generate_mails, generate_sequence_facts, select_reasons,
)
from preview_snapshot import _snapshot_from_zip, build_snapshot, validate_snapshot
from review_draft_stages import prepare_review_batch
from review_selection import build_review_queue, render_csv, render_markdown, select_approved
from simple_overview import render_overview

REPO = "Yolol100/Leadscanner"
DOMAIN = "voorbeeld.invalid"
ADDRESS = "info@voorbeeld.invalid"  # Reserved, never a real recipient.


def example_evidence(text: str, path: str) -> dict:
    return {
        "text": text,
        "source_type": "official_site",
        "source_url": f"https://{DOMAIN}/{path}",
        "page_type": "process",
    }


def candidate() -> dict:
    return {
        "name_hint": "Fictieve Voorbeeldwinkel",
        "official_domain": DOMAIN,
        "official_url": f"https://{DOMAIN}/",
        "public_business_email": ADDRESS,
        "research_status": "ready",
        "evidence_candidates": [
            example_evidence(
                "Klanten kunnen online een afspraak aanvragen voor onderhoud en reparatie.",
                "afspraak",
            ),
            example_evidence(
                "Vraag online een offerte aan via ons formulier voor maatwerk.",
                "offerte",
            ),
            example_evidence(
                "Klanten kunnen via de website bestellen en afhalen in onze winkel.",
                "bestellen",
            ),
            example_evidence(
                "U kunt uw bestelling retourneren via ons retourformulier voor klanten.",
                "retour",
            ),
            example_evidence(
                "Onze klanten vinden antwoorden in de kennisbank met veelgestelde vragen.",
                "informatie",
            ),
        ],
        "automatic_send": False,
    }


def _safe_network_forbidden(*_args, **_kwargs):
    raise AssertionError("synthetic_preview_must_not_access_network")


def run_smoke() -> dict:
    with patch.object(socket.socket, "connect", side_effect=_safe_network_forbidden):
        reasons = select_reasons({"candidates": [candidate()]})
        if reasons["ready_count"] != 1:
            raise AssertionError("synthetic_outreach_not_ready")
        points = reasons["candidates"][0]["selected_findings"]
        if len(points) != 5 or [p["score"] for p in points] != sorted(
            (p["score"] for p in points), reverse=True,
        ):
            raise AssertionError("synthetic_ranked_findings_invalid")
        if not all(point["source_url"].startswith(f"https://{DOMAIN}/") for point in points):
            raise AssertionError("synthetic_cross_domain_evidence")
        values = choose_value_actions(reasons)
        if values["ready_count"] != 1:
            raise AssertionError("synthetic_value_action_not_ready")
        mail = generate_mails(values)
        if mail["ready_for_human_review_count"] != 1:
            raise AssertionError("synthetic_reviewed_mail_not_ready")
        draft = prepare_review_batch(mail)
        queue = build_review_queue(draft)
        if queue["review_candidate_count"] != 1:
            raise AssertionError("synthetic_queue_invalid")

        review_markdown = render_markdown(queue)
        review_csv = render_csv(queue)
        if not (
            ADDRESS in review_markdown
            and ADDRESS in review_csv
            and review_markdown.count(f"https://{DOMAIN}/") >= 5
            and "Belangrijkste bevindingen" in review_markdown
        ):
            raise AssertionError("synthetic_review_sources_missing")
        token = queue["items"][0]["approval_token"]
        selection = select_approved(draft, token)
        if selection["approval"]["approved_count"] != 1:
            raise AssertionError("synthetic_review_approval_not_bound")
        changed = copy.deepcopy(draft)
        changed["rows"][0]["selected_findings"][0]["observation"] += " Veranderd."
        try:
            select_approved(changed, token)
        except ValueError as exc:
            if "unknown_or_stale_approval_token" not in str(exc):
                raise
        else:
            raise AssertionError("synthetic_stale_review_approved")

        request = {
            "execution_mode": "preview",
            "region": "Fictieve plaats",
            "keywords": ["fictieve winkel"],
            "target_candidates": 1,
            "verify_limit": 1,
            "radius_km": 1.0,
            "preview_copy_mode": "reviewed_mail",
        }
        manifest = build_manifest(
            mode="preview", request=request,
            filtered={"candidate_count": 1},
            dedupe={"kept_count": 1},
            verified={"ready_for_research_count": 1},
            research={"research_ready_count": 1},
            reasons=reasons, values=values, mail=mail,
            draft_batch=draft, review_queue=queue,
        )
        if manifest["closure"]["automatic_send"] is not False:
            raise AssertionError("synthetic_preview_send_flag")
        overview = render_overview(manifest)
        if ADDRESS in overview or "Klaar voor beoordeling" not in overview:
            # Overview must be aggregate-only.
            if ADDRESS in overview or "Contacten klaar voor beoordeling" not in overview:
                raise AssertionError("synthetic_overview_privacy_invalid")
        head_sha = os.getenv("GITHUB_SHA", "a" * 40)
        if len(head_sha) != 40:
            head_sha = "a" * 40
        snapshot = build_snapshot(
            request=request, batch=draft, queue=queue, manifest=manifest,
            source={
                "repository": REPO,
                "run_id": 123456,
                "run_number": 1,
                "head_sha": head_sha,
            },
        )
        validate_snapshot(snapshot, repository=REPO, run_id=123456, head_sha=head_sha)
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w") as archive:
            archive.writestr("preview-snapshot.json", json.dumps(snapshot, ensure_ascii=False))
        loaded = _snapshot_from_zip(memory.getvalue())
        if loaded["preview_id"] != snapshot["preview_id"]:
            raise AssertionError("synthetic_snapshot_archive_not_exact")

        facts = generate_sequence_facts(values)
        if facts["ready_for_human_review_count"] != 1:
            raise AssertionError("synthetic_sequence_review_not_ready")
        fact_draft = prepare_review_batch(facts)
        fact_queue = build_review_queue(fact_draft)
        if fact_queue["items"][0]["body"] or fact_queue["items"][0]["findings_count"] != 5:
            raise AssertionError("synthetic_sequence_wrote_mail")
        if selection["safety"]["automatic_send"] is not False:
            raise AssertionError("synthetic_approval_send_flag")

    # Only aggregate results are returned / printed. Fake recipient stays local.
    return {
        "status": "green",
        "mode": "offline_synthetic_preview",
        "website_candidates": 1,
        "ranked_findings": len(points),
        "review_candidates": queue["review_candidate_count"],
        "verified_snapshot": True,
        "stale_approval_rejected": True,
        "fact_only_mode_verified": True,
        "network_calls": 0,
        "mailbox_mutations": 0,
        "campaign_mutations": 0,
        "automatic_send": False,
        "real_prospects": 0,
    }


def main() -> int:
    result = run_smoke()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
