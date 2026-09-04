#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Mapping, Sequence

from prospect_discovery import (
    BoundedHttpClient,
    CANDIDATE_HEADERS,
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_TOTAL,
    DEFAULT_TIMEOUT,
    HARD_MAX_BYTES,
    HARD_MAX_TOTAL,
    HARD_TIMEOUT,
    LEAD_HEADERS,
    SOURCE_HEADERS,
    DiscoveryError,
    SourceSpec,
    clamp_float,
    clamp_int,
    discover_source,
    existing_domains,
    host_key,
    rows_to_dicts,
)


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


def append_rows(service, spreadsheet_id: str, range_name: str, rows: Sequence[Sequence[object]]) -> None:
    if not rows:
        return
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [list(row) for row in rows]},
    ).execute()


def ensure_tabs(service, spreadsheet_id: str, *, create: bool) -> None:
    metadata = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields="sheets.properties"
    ).execute()
    sheets = {
        item["properties"]["title"]: item["properties"]["sheetId"]
        for item in metadata.get("sheets", [])
    }
    required = {"ProspectSources": SOURCE_HEADERS, "ProspectCandidates": CANDIDATE_HEADERS}
    missing = [title for title in required if title not in sheets]
    if missing and not create:
        raise DiscoveryError("missing spreadsheet tabs: " + ", ".join(missing))
    if missing:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}} for title in missing]},
        ).execute()
    for title, headers in required.items():
        values = get_values(service, spreadsheet_id, f"'{title}'!1:1")
        current = [str(v).strip() for v in values[0]] if values else []
        if not current and create:
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"'{title}'!A1",
                valueInputOption="RAW",
                body={"values": [headers]},
            ).execute()
        elif current != headers:
            raise DiscoveryError(f"{title} headers do not match the required contract")


def write_report(path: str, payload: Mapping[str, object]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def run(mode: str, report_path: str) -> int:
    mode = mode.casefold().strip()
    if mode not in {"validate", "bootstrap", "discover"}:
        raise DiscoveryError(f"unsupported mode: {mode}")
    spreadsheet_id = os.environ.get("OUTREACH_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        raise DiscoveryError("OUTREACH_SPREADSHEET_ID is required")
    service = load_google_service()
    ensure_tabs(service, spreadsheet_id, create=(mode == "bootstrap"))
    if mode == "bootstrap":
        write_report(report_path, {
            "mode": mode, "status": "ready",
            "created_or_validated_tabs": ["ProspectSources", "ProspectCandidates"],
        })
        return 0

    source_rows = rows_to_dicts(
        get_values(service, spreadsheet_id, "'ProspectSources'!A:I"), SOURCE_HEADERS
    )
    candidate_rows = rows_to_dicts(
        get_values(service, spreadsheet_id, "'ProspectCandidates'!A:K"), CANDIDATE_HEADERS
    )
    lead_rows = rows_to_dicts(
        get_values(service, spreadsheet_id, "'Leadlijst'!A:D"), LEAD_HEADERS
    )
    sources = []
    errors = []
    for index, row in enumerate(source_rows, start=2):
        try:
            source = SourceSpec.from_row(row)
        except DiscoveryError as exc:
            errors.append(f"ProspectSources row {index}: {exc}")
            continue
        if source.enabled:
            sources.append(source)
    if errors:
        raise DiscoveryError("; ".join(errors))
    unapproved = [source.source_id for source in sources if not source.approved]
    if mode == "validate":
        write_report(report_path, {
            "mode": mode, "status": "ready", "enabled_sources": len(sources),
            "approved_sources": len(sources) - len(unapproved),
            "unapproved_sources": unapproved, "existing_candidates": len(candidate_rows),
            "existing_leads": len(lead_rows),
        })
        return 0

    client = BoundedHttpClient(
        user_agent=os.environ.get("PROSPECT_DISCOVERY_USER_AGENT", "WebactueelProspectDiscovery/1.0 (+https://andrewbaeten.nl)"),
        timeout=clamp_float(os.environ.get("PROSPECT_DISCOVERY_TIMEOUT_SECONDS"), DEFAULT_TIMEOUT, 1.0, HARD_TIMEOUT),
        max_bytes=clamp_int(os.environ.get("PROSPECT_DISCOVERY_MAX_BYTES"), DEFAULT_MAX_BYTES, 16_384, HARD_MAX_BYTES),
        min_interval=clamp_float(os.environ.get("PROSPECT_DISCOVERY_MIN_INTERVAL_SECONDS"), 0.25, 0.0, 5.0),
    )
    max_total = clamp_int(
        os.environ.get("PROSPECT_DISCOVERY_MAX_TOTAL"), DEFAULT_MAX_TOTAL, 1, HARD_MAX_TOTAL
    )
    known = existing_domains(lead_rows, candidate_rows)
    discovered = []
    failures = []
    for source in sources:
        if not source.approved:
            continue
        try:
            items = discover_source(source, client.fetch_text)
        except DiscoveryError as exc:
            failures.append({"source_id": source.source_id, "error": str(exc)[:300]})
            continue
        for item in items:
            domain = host_key(item.website)
            if not domain or domain in known:
                continue
            known.add(domain)
            discovered.append(item)
            if len(discovered) >= max_total:
                break
        if len(discovered) >= max_total:
            break

    discovered_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    append_rows(
        service, spreadsheet_id, "'ProspectCandidates'!A:K",
        [item.as_row(discovered_at) for item in discovered],
    )
    write_report(report_path, {
        "mode": mode, "status": "completed", "enabled_sources": len(sources),
        "approved_sources": len(sources) - len(unapproved), "discovered": len(discovered),
        "dedupe_domains_after_run": len(known), "source_failures": failures,
        "note": "Candidates remain discovered-only; contact lookup is deferred to Leads, which must review fit, evidence, compliance and approved transport state before SMTP.",
    })
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover public business domains from explicitly approved source pages."
    )
    parser.add_argument(
        "--mode", default=os.environ.get("PROSPECT_DISCOVERY_MODE", "validate"),
        choices=["validate", "bootstrap", "discover"],
    )
    parser.add_argument("--report", default="prospect-discovery-report.json")
    args = parser.parse_args(argv)
    try:
        return run(args.mode, args.report)
    except DiscoveryError as exc:
        write_report(args.report, {"mode": args.mode, "status": "blocked", "error": str(exc)})
        print(f"prospect discovery blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
