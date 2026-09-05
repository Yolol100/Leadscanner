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
    DEFAULT_TIMEOUT,
    HARD_MAX_BYTES,
    HARD_TIMEOUT,
    DiscoveryError,
    clamp_float,
    clamp_int,
    root_url,
    rows_to_dicts,
)
from prospect_intelligence import SIGNAL_HEADERS, normalize_signal
from prospect_signal_discovery import discover_official_signals, stable_signal_id

ALLOWED_CANDIDATE_STATUSES = {"discovered", "qualified", "hold"}
DEFAULT_MAX_CANDIDATES = 10
HARD_MAX_CANDIDATES = 25
SOURCE_ID = "official-site-signal"


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


def sheet_titles(service, spreadsheet_id: str) -> set[str]:
    metadata = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields="sheets.properties.title"
    ).execute()
    return {item["properties"]["title"] for item in metadata.get("sheets", [])}


def write_report(path: str, payload: Mapping[str, object]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def select_candidates(rows: Sequence[Mapping[str, object]], limit: int) -> list[Mapping[str, object]]:
    output: list[Mapping[str, object]] = []
    for row in rows:
        status = str(row.get("status") or "").strip().casefold()
        candidate_id = str(row.get("candidate_id") or "").strip()
        website = root_url(str(row.get("website") or ""))
        if status not in ALLOWED_CANDIDATE_STATUSES or not candidate_id or not website:
            continue
        output.append(row)
        if len(output) >= limit:
            break
    return output


def signal_row(signal: Mapping[str, object]) -> list[object]:
    return [signal.get(header, "") for header in SIGNAL_HEADERS]


def update_signal_row(service, spreadsheet_id: str, row_number: int, signal: Mapping[str, object]) -> None:
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'ProspectSignals'!A{row_number}:K{row_number}",
        valueInputOption="RAW",
        body={"values": [signal_row(signal)]},
    ).execute()


def append_signal_rows(service, spreadsheet_id: str, rows: Sequence[Mapping[str, object]]) -> None:
    if not rows:
        return
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range="'ProspectSignals'!A:K",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [signal_row(row) for row in rows]},
    ).execute()


def run(mode: str, report_path: str) -> int:
    mode = mode.casefold().strip()
    if mode not in {"validate", "discover"}:
        raise DiscoveryError(f"unsupported mode: {mode}")
    spreadsheet_id = os.environ.get("OUTREACH_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        raise DiscoveryError("OUTREACH_SPREADSHEET_ID is required")

    service = load_google_service()
    titles = sheet_titles(service, spreadsheet_id)
    candidate_rows = rows_to_dicts(
        get_values(service, spreadsheet_id, "'ProspectCandidates'!A:K"), CANDIDATE_HEADERS
    )
    signal_tab_ready = "ProspectSignals" in titles
    signal_rows = []
    if signal_tab_ready:
        signal_rows = rows_to_dicts(
            get_values(service, spreadsheet_id, "'ProspectSignals'!A:K"), SIGNAL_HEADERS
        )
    limit = clamp_int(
        os.environ.get("PROSPECT_SIGNAL_MAX_CANDIDATES"),
        DEFAULT_MAX_CANDIDATES,
        1,
        HARD_MAX_CANDIDATES,
    )
    selected = select_candidates(candidate_rows, limit)
    if mode == "validate":
        write_report(report_path, {
            "mode": mode,
            "status": "ready" if signal_tab_ready else "bootstrap_required",
            "candidate_rows": len(candidate_rows),
            "eligible_candidates": len(selected),
            "signal_rows": len(signal_rows),
            "prospect_signals_ready": signal_tab_ready,
            "send_permission": "none",
        })
        return 0
    if not signal_tab_ready:
        raise DiscoveryError("ProspectSignals tab is missing; run prospect intelligence bootstrap first")

    known_candidate_ids = {str(row.get("candidate_id") or "").strip() for row in candidate_rows}
    known_candidate_ids.discard("")
    existing: dict[str, tuple[int, dict[str, object]]] = {}
    for offset, row in enumerate(signal_rows, start=2):
        signal_id = str(row.get("signal_id") or "").strip()
        if signal_id:
            existing[signal_id] = (offset, dict(row))

    client = BoundedHttpClient(
        user_agent=os.environ.get(
            "PROSPECT_SIGNAL_USER_AGENT",
            "WebactueelProspectSignalDiscovery/1.0 (+https://andrewbaeten.nl)",
        ),
        timeout=clamp_float(os.environ.get("PROSPECT_SIGNAL_TIMEOUT_SECONDS"), DEFAULT_TIMEOUT, 1.0, HARD_TIMEOUT),
        max_bytes=clamp_int(os.environ.get("PROSPECT_SIGNAL_MAX_BYTES"), DEFAULT_MAX_BYTES, 16_384, HARD_MAX_BYTES),
        min_interval=clamp_float(os.environ.get("PROSPECT_SIGNAL_MIN_INTERVAL_SECONDS"), 0.25, 0.0, 5.0),
    )
    detected_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    appended: list[dict[str, str]] = []
    updated = 0
    expired = 0
    failures: list[dict[str, str]] = []
    scanned_candidates: set[str] = set()
    seen_signal_ids: set[str] = set()

    for candidate in selected:
        candidate_id = str(candidate.get("candidate_id") or "").strip()
        website = root_url(str(candidate.get("website") or ""))
        try:
            homepage_html = client.fetch_text(website)
            evidence = discover_official_signals(website, homepage_html, fetch_text=client.fetch_text)
        except DiscoveryError as exc:
            failures.append({"candidate_id": candidate_id, "website": website, "error": str(exc)[:300]})
            continue
        scanned_candidates.add(candidate_id)
        for item in evidence:
            signal_id = stable_signal_id(candidate_id, item.signal_type, item.evidence_url)
            payload = normalize_signal({
                "signal_id": signal_id,
                "candidate_id": candidate_id,
                "detected_at": detected_at,
                "signal_type": item.signal_type,
                "evidence_url": item.evidence_url,
                "evidence_date": detected_at,
                "strength": str(item.strength),
                "confidence": item.confidence,
                "source_id": SOURCE_ID,
                "status": "active",
                "note": item.note,
            }, known_candidate_ids=known_candidate_ids)
            seen_signal_ids.add(signal_id)
            if signal_id in existing:
                row_number, old = existing[signal_id]
                if any(str(old.get(key) or "") != str(payload.get(key) or "") for key in SIGNAL_HEADERS[2:]):
                    update_signal_row(service, spreadsheet_id, row_number, payload)
                    updated += 1
            else:
                appended.append(payload)
                existing[signal_id] = (-1, dict(payload))

    for signal_id, (row_number, old) in list(existing.items()):
        if row_number < 2:
            continue
        candidate_id = str(old.get("candidate_id") or "").strip()
        source_id = str(old.get("source_id") or "").strip()
        status = str(old.get("status") or "").strip().casefold()
        if source_id != SOURCE_ID or status != "active" or candidate_id not in scanned_candidates or signal_id in seen_signal_ids:
            continue
        payload = dict(old)
        payload["detected_at"] = detected_at
        payload["status"] = "expired"
        payload["note"] = "Not redetected on the latest successful bounded official-site signal scan."
        normalized = normalize_signal(payload, known_candidate_ids=known_candidate_ids)
        update_signal_row(service, spreadsheet_id, row_number, normalized)
        expired += 1

    append_signal_rows(service, spreadsheet_id, appended)
    write_report(report_path, {
        "mode": mode,
        "status": "completed",
        "eligible_candidates": len(selected),
        "scanned_candidates": len(scanned_candidates),
        "new_signals": len(appended),
        "updated_signals": updated,
        "expired_signals": expired,
        "failures": failures,
        "send_permission": "none",
        "note": "Signals are official-site evidence only and remain advisory. They never change Customer Potential, qualification, compliance, contact promotion, copy or transport permission.",
    })
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover bounded official-site prospect signals.")
    parser.add_argument(
        "--mode", default=os.environ.get("PROSPECT_SIGNAL_MODE", "validate"),
        choices=["validate", "discover"],
    )
    parser.add_argument("--report", default="prospect-signal-report.json")
    args = parser.parse_args(argv)
    try:
        return run(args.mode, args.report)
    except DiscoveryError as exc:
        write_report(args.report, {"mode": args.mode, "status": "blocked", "error": str(exc)})
        print(f"prospect signal discovery blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
