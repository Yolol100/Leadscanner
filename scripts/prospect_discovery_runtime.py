#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
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
from prospect_intelligence import OBSERVATION_HEADERS, clamp_target, make_observation_row, target_summary
from prospect_target_policy import (
    DEFAULT_EXCLUDED_COUNTRIES,
    DEFAULT_PREFERRED_COUNTRIES,
    apply_source_policy,
    parse_country_list,
    prioritize_sources,
)

SOURCE_RUN_HEADERS = [
    "run_id", "run_at", "source_id", "source_type", "source_url", "status",
    "seen", "new", "duplicates", "duration_ms", "error",
]


def env_enabled(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "ja", "y", "on"}


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


def ensure_tabs(service, spreadsheet_id: str, *, create: bool) -> set[str]:
    metadata = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields="sheets.properties"
    ).execute()
    sheets = {
        item["properties"]["title"]: item["properties"]["sheetId"]
        for item in metadata.get("sheets", [])
    }
    required = {"ProspectSources": SOURCE_HEADERS, "ProspectCandidates": CANDIDATE_HEADERS}
    optional_on_bootstrap = {
        "ProspectObservations": OBSERVATION_HEADERS,
        "ProspectSourceRuns": SOURCE_RUN_HEADERS,
    }
    missing_required = [title for title in required if title not in sheets]
    if missing_required and not create:
        raise DiscoveryError("missing spreadsheet tabs: " + ", ".join(missing_required))
    to_create = list(missing_required)
    if create:
        to_create.extend(title for title in optional_on_bootstrap if title not in sheets)
    if to_create:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}} for title in to_create]},
        ).execute()
        sheets.update({title: -1 for title in to_create})
    for title, headers in {**required, **optional_on_bootstrap}.items():
        if title not in sheets:
            continue
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
    return set(sheets)


def write_report(path: str, payload: Mapping[str, object]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def source_run_row(
    *, run_id: str, run_at: str, source: SourceSpec, status: str,
    seen: int, new_count: int, duplicate_count: int, duration_ms: int, error: str = "",
) -> list[object]:
    return [
        run_id,
        run_at,
        source.source_id,
        source.source_type,
        source.source_url,
        status,
        max(0, int(seen)),
        max(0, int(new_count)),
        max(0, int(duplicate_count)),
        max(0, int(duration_ms)),
        str(error or "")[:300],
    ]


def run(mode: str, report_path: str) -> int:
    mode = mode.casefold().strip()
    if mode not in {"validate", "bootstrap", "discover"}:
        raise DiscoveryError(f"unsupported mode: {mode}")
    spreadsheet_id = os.environ.get("OUTREACH_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        raise DiscoveryError("OUTREACH_SPREADSHEET_ID is required")
    service = load_google_service()
    sheet_titles = ensure_tabs(service, spreadsheet_id, create=(mode == "bootstrap"))
    if mode == "bootstrap":
        write_report(report_path, {
            "mode": mode,
            "status": "ready",
            "created_or_validated_tabs": [
                "ProspectSources", "ProspectCandidates", "ProspectObservations", "ProspectSourceRuns"
            ],
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

    excluded_countries = parse_country_list(
        os.environ.get("PROSPECT_DISCOVERY_EXCLUDE_COUNTRIES"), DEFAULT_EXCLUDED_COUNTRIES
    )
    preferred_countries = parse_country_list(
        os.environ.get("PROSPECT_DISCOVERY_PREFERRED_COUNTRIES"), DEFAULT_PREFERRED_COUNTRIES
    )
    exclude_agencies = env_enabled("PROSPECT_DISCOVERY_EXCLUDE_AGENCIES", True)
    extra_exclude_terms = os.environ.get("PROSPECT_DISCOVERY_EXTRA_EXCLUDE_TERMS", "")

    sources = []
    errors = []
    policy_excluded_sources = []
    for index, row in enumerate(source_rows, start=2):
        try:
            source = SourceSpec.from_row(row)
        except DiscoveryError as exc:
            errors.append(f"ProspectSources row {index}: {exc}")
            continue
        if not source.enabled:
            continue
        source, policy_reason = apply_source_policy(
            source,
            excluded_countries=excluded_countries,
            exclude_agencies=exclude_agencies,
            extra_exclude_terms=extra_exclude_terms,
        )
        if source is None:
            policy_excluded_sources.append({
                "row": index,
                "source_id": str(row.get("source_id") or ""),
                "country": str(row.get("country") or ""),
                "reason": policy_reason,
            })
            continue
        sources.append(source)
    if errors:
        raise DiscoveryError("; ".join(errors))
    sources = prioritize_sources(sources, preferred_countries)
    unapproved = [source.source_id for source in sources if not source.approved]
    if mode == "validate":
        write_report(report_path, {
            "mode": mode,
            "status": "ready",
            "enabled_sources": len(sources),
            "approved_sources": len(sources) - len(unapproved),
            "unapproved_sources": unapproved,
            "policy_excluded_sources": policy_excluded_sources,
            "excluded_countries": list(excluded_countries),
            "preferred_countries": list(preferred_countries),
            "agency_exclusion_enabled": exclude_agencies,
            "existing_candidates": len(candidate_rows),
            "existing_leads": len(lead_rows),
            "observations_available": "ProspectObservations" in sheet_titles,
            "source_runs_available": "ProspectSourceRuns" in sheet_titles,
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
    target_new = clamp_target(os.environ.get("PROSPECT_DISCOVERY_TARGET_NEW"), max_total)
    known = existing_domains(lead_rows, candidate_rows)
    discovered = []
    failures = []
    source_results = []
    source_run_rows = []
    observations = []
    observation_ids = set()
    discovered_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip() or discovered_at

    for source in sources:
        if not source.approved:
            continue
        started = time.monotonic()
        try:
            items = discover_source(source, client.fetch_text)
        except DiscoveryError as exc:
            duration_ms = round((time.monotonic() - started) * 1000)
            error = str(exc)[:300]
            failures.append({"source_id": source.source_id, "error": error})
            source_results.append({
                "source_id": source.source_id,
                "source_type": source.source_type,
                "country": source.country,
                "seen": 0,
                "new": 0,
                "duplicates": 0,
                "duration_ms": duration_ms,
                "status": "error",
            })
            source_run_rows.append(source_run_row(
                run_id=run_id, run_at=discovered_at, source=source, status="error",
                seen=0, new_count=0, duplicate_count=0, duration_ms=duration_ms, error=error,
            ))
            continue
        seen = 0
        new_count = 0
        duplicate_count = 0
        for item in items:
            domain = host_key(item.website)
            if not domain:
                continue
            seen += 1
            is_duplicate = domain in known
            observation = make_observation_row(
                run_id=run_id,
                observed_at=discovered_at,
                candidate=item,
                outcome="duplicate" if is_duplicate else "new",
            )
            if observation[0] not in observation_ids:
                observations.append(observation)
                observation_ids.add(observation[0])
            if is_duplicate:
                duplicate_count += 1
                continue
            known.add(domain)
            discovered.append(item)
            new_count += 1
            if len(discovered) >= target_new:
                break
        duration_ms = round((time.monotonic() - started) * 1000)
        source_results.append({
            "source_id": source.source_id,
            "source_type": source.source_type,
            "country": source.country,
            "seen": seen,
            "new": new_count,
            "duplicates": duplicate_count,
            "duration_ms": duration_ms,
            "status": "ok",
        })
        source_run_rows.append(source_run_row(
            run_id=run_id, run_at=discovered_at, source=source, status="ok",
            seen=seen, new_count=new_count, duplicate_count=duplicate_count, duration_ms=duration_ms,
        ))
        if len(discovered) >= target_new:
            break

    append_rows(
        service, spreadsheet_id, "'ProspectCandidates'!A:K",
        [item.as_row(discovered_at) for item in discovered],
    )
    observation_persisted = "ProspectObservations" in sheet_titles
    if observation_persisted:
        append_rows(service, spreadsheet_id, "'ProspectObservations'!A:K", observations)
    source_runs_persisted = "ProspectSourceRuns" in sheet_titles
    if source_runs_persisted:
        append_rows(service, spreadsheet_id, "'ProspectSourceRuns'!A:K", source_run_rows)

    report = {
        "mode": mode,
        "status": "completed",
        "enabled_sources": len(sources),
        "approved_sources": len(sources) - len(unapproved),
        "policy_excluded_sources": policy_excluded_sources,
        "excluded_countries": list(excluded_countries),
        "preferred_countries": list(preferred_countries),
        "agency_exclusion_enabled": exclude_agencies,
        "discovered": len(discovered),
        "dedupe_domains_after_run": len(known),
        "source_failures": failures,
        "source_results": source_results,
        "source_run_rows": len(source_run_rows),
        "source_runs_persisted": source_runs_persisted,
        "observation_rows": len(observations),
        "observations_persisted": observation_persisted,
        "note": "Candidates remain discovered-only; NL/default excluded countries and agency-like providers are filtered before candidate creation. Contact lookup is deferred to Leads, which must review fit, website evidence, compliance and approved transport state before SMTP.",
    }
    report.update(target_summary(len(discovered), target_new))
    write_report(report_path, report)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover public business domains from explicitly approved source pages, directory indexes or directory sitemaps."
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
