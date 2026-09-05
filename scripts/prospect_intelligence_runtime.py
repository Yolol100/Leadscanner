#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Mapping, Sequence

from prospect_discovery import CANDIDATE_HEADERS, LEAD_HEADERS, SOURCE_HEADERS, DiscoveryError, rows_to_dicts
from prospect_intelligence import (
    ENTITY_HEADERS,
    EVIDENCE_HEADERS,
    LOOKALIKE_HEADERS,
    OBSERVATION_HEADERS,
    SIGNAL_HEADERS,
    SOURCE_METRIC_HEADERS,
    build_entities,
    build_evidence_edges,
    build_lookalike_recommendations,
    build_source_metrics,
    validate_signals,
)

CONTACT_HEADERS = [
    "candidate_id", "checked_at", "company", "website", "email", "source_url",
    "email_domain", "domain_alignment", "mx_status", "status", "reason",
]
DERIVED_TABS = {
    "ProspectEntities": ENTITY_HEADERS,
    "ProspectSourceMetrics": SOURCE_METRIC_HEADERS,
    "ProspectEvidence": EVIDENCE_HEADERS,
    "ProspectLookalikes": LOOKALIKE_HEADERS,
}
INPUT_TABS = {
    "ProspectObservations": OBSERVATION_HEADERS,
    "ProspectSignals": SIGNAL_HEADERS,
}


def load_google_service():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise DiscoveryError("GOOGLE_SERVICE_ACCOUNT_JSON is required")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DiscoveryError("GOOGLE_SERVICE_ACCOUNT_JSON is invalid JSON") from exc
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise DiscoveryError("Google API dependencies are not installed") from exc
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def get_values(service, spreadsheet_id: str, range_name: str) -> list[list[object]]:
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=range_name
    ).execute()
    return result.get("values", [])


def _sheet_titles(service, spreadsheet_id: str) -> set[str]:
    metadata = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields="sheets.properties"
    ).execute()
    return {item["properties"]["title"] for item in metadata.get("sheets", [])}


def ensure_tabs(service, spreadsheet_id: str, *, create: bool) -> tuple[set[str], list[str]]:
    required = {**INPUT_TABS, **DERIVED_TABS}
    titles = _sheet_titles(service, spreadsheet_id)
    missing = [title for title in required if title not in titles]
    if missing and create:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}} for title in missing]},
        ).execute()
    if create and missing:
        titles.update(missing)
    for title, headers in required.items():
        if title not in titles:
            continue
        values = get_values(service, spreadsheet_id, f"'{title}'!1:1")
        current = [str(value).strip() for value in values[0]] if values else []
        if not current and create:
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"'{title}'!A1",
                valueInputOption="RAW",
                body={"values": [headers]},
            ).execute()
        elif current != headers:
            raise DiscoveryError(f"{title} headers do not match the required contract")
    return titles, missing


def replace_rows(service, spreadsheet_id: str, title: str, headers: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range=f"'{title}'!A:ZZ", body={}
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{title}'!A1",
        valueInputOption="RAW",
        body={"values": [list(headers)] + [list(row) for row in rows]},
    ).execute()


def write_report(path: str, payload: Mapping[str, object]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _clamp_stale_days(raw: object) -> int:
    try:
        value = int(raw) if str(raw or "").strip() else 30
    except (TypeError, ValueError):
        value = 30
    return max(1, min(value, 365))


def run(mode: str, report_path: str) -> int:
    mode = mode.casefold().strip()
    if mode not in {"validate", "bootstrap", "refresh"}:
        raise DiscoveryError(f"unsupported mode: {mode}")
    spreadsheet_id = os.environ.get("OUTREACH_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        raise DiscoveryError("OUTREACH_SPREADSHEET_ID is required")
    service = load_google_service()
    titles, missing_tabs = ensure_tabs(service, spreadsheet_id, create=(mode == "bootstrap"))
    if mode == "bootstrap":
        write_report(report_path, {
            "mode": mode,
            "status": "ready",
            "created_or_validated_tabs": list(INPUT_TABS) + list(DERIVED_TABS),
            "send_permission": "none",
        })
        return 0

    source_rows = rows_to_dicts(get_values(service, spreadsheet_id, "'ProspectSources'!A:I"), SOURCE_HEADERS)
    candidate_rows = rows_to_dicts(get_values(service, spreadsheet_id, "'ProspectCandidates'!A:K"), CANDIDATE_HEADERS)
    observation_rows = (
        rows_to_dicts(get_values(service, spreadsheet_id, "'ProspectObservations'!A:K"), OBSERVATION_HEADERS)
        if "ProspectObservations" in titles else []
    )
    signal_rows_raw = (
        rows_to_dicts(get_values(service, spreadsheet_id, "'ProspectSignals'!A:K"), SIGNAL_HEADERS)
        if "ProspectSignals" in titles else []
    )
    contact_rows = rows_to_dicts(
        get_values(service, spreadsheet_id, "'ContactCandidates'!A:K"), CONTACT_HEADERS
    )
    lead_rows = rows_to_dicts(get_values(service, spreadsheet_id, "'Leadlijst'!A:D"), LEAD_HEADERS)
    candidate_ids = {str(row.get("candidate_id") or "").strip() for row in candidate_rows}
    candidate_ids.discard("")
    try:
        signal_rows = validate_signals(signal_rows_raw, known_candidate_ids=candidate_ids)
    except ValueError as exc:
        raise DiscoveryError(str(exc)) from exc

    stale_days = _clamp_stale_days(os.environ.get("PROSPECT_INTELLIGENCE_STALE_DAYS"))
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    entities = build_entities(candidate_rows, observation_rows, stale_days=stale_days)
    source_metrics = build_source_metrics(
        source_rows, candidate_rows, contact_rows, lead_rows, signal_rows, generated_at=generated_at
    )
    evidence = build_evidence_edges(candidate_rows, signal_rows, contact_rows, lead_rows)
    lookalikes = build_lookalike_recommendations(candidate_rows, lead_rows, generated_at=generated_at)

    if mode == "refresh":
        required_missing = [title for title in {**INPUT_TABS, **DERIVED_TABS} if title not in titles]
        if required_missing:
            raise DiscoveryError("prospect intelligence bootstrap required: " + ", ".join(required_missing))
        replace_rows(service, spreadsheet_id, "ProspectEntities", ENTITY_HEADERS, entities)
        replace_rows(service, spreadsheet_id, "ProspectSourceMetrics", SOURCE_METRIC_HEADERS, source_metrics)
        replace_rows(service, spreadsheet_id, "ProspectEvidence", EVIDENCE_HEADERS, evidence)
        replace_rows(service, spreadsheet_id, "ProspectLookalikes", LOOKALIKE_HEADERS, lookalikes)

    write_report(report_path, {
        "mode": mode,
        "status": "completed" if mode == "refresh" else "ready",
        "sources": len(source_rows),
        "candidates": len(candidate_rows),
        "observations": len(observation_rows),
        "signals": len(signal_rows),
        "entities": len(entities),
        "source_metrics": len(source_metrics),
        "evidence_edges": len(evidence),
        "lookalike_recommendations": len(lookalikes),
        "stale_days": stale_days,
        "bootstrap_required": missing_tabs,
        "send_permission": "none",
        "note": "All intelligence outputs are derived/advisory. They never change Customer Potential, compliance, contact promotion, copy or transport permission.",
    })
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate or refresh derived prospect intelligence views.")
    parser.add_argument(
        "--mode", default=os.environ.get("PROSPECT_INTELLIGENCE_MODE", "validate"),
        choices=["validate", "bootstrap", "refresh"],
    )
    parser.add_argument("--report", default="prospect-intelligence-report.json")
    args = parser.parse_args(argv)
    try:
        return run(args.mode, args.report)
    except DiscoveryError as exc:
        write_report(args.report, {"mode": args.mode, "status": "blocked", "error": str(exc)})
        print(f"prospect intelligence blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
