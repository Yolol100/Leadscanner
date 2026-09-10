#!/usr/bin/env python3
from __future__ import annotations

import time
from typing import Mapping

import outreach_draft_first_prepare as legacy
from prospect_intelligence import canonical_domain

_original_append_row = legacy.append_row
_original_load = legacy.load
_original_candidate_ok = legacy.candidate_ok


def _text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _email(value: object) -> str:
    return _text(value).casefold()


def _retryable(exc: BaseException) -> bool:
    value = str(exc).casefold()
    return isinstance(exc, (OSError, TimeoutError)) or any(token in value for token in (
        "ssl", "eof occurred", "timed out", "timeout", "connection reset", "connection aborted",
        "temporarily unavailable", "rate limit", "429", "500", "502", "503", "504",
    ))


def load_retry(service, spreadsheet_id: str, sheet: str, expected_headers: list[str]):
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            return _original_load(service, spreadsheet_id, sheet, expected_headers)
        except Exception as exc:
            if not _retryable(exc) or attempt >= max_attempts:
                raise
            time.sleep(min(8.0, 0.5 * (2 ** (attempt - 1))))
    raise RuntimeError("unreachable draft-first read retry state")


def _matches(sheet: str, existing: Mapping[str, object], desired: Mapping[str, object]) -> bool:
    if sheet == legacy.QUEUE_SHEET:
        return bool(
            _text(desired.get("lead_id"))
            and _text(existing.get("lead_id")) == _text(desired.get("lead_id"))
            and _email(existing.get("email")) == _email(desired.get("email"))
        )
    if sheet == legacy.LEAD_SHEET:
        desired_domain = canonical_domain(desired.get("Website") or desired.get("website"))
        existing_domain = canonical_domain(existing.get("Website") or existing.get("website"))
        desired_email = _email(desired.get("E-mail") or desired.get("email"))
        existing_email = _email(existing.get("E-mail") or existing.get("email"))
        return bool(desired_domain and desired_domain == existing_domain and desired_email == existing_email)
    return all(_text(existing.get(key)) == _text(value) for key, value in desired.items() if _text(value))


def _readback_count(service, spreadsheet_id: str, sheet: str, headers: list[str], row: Mapping[str, object]) -> int:
    return sum(1 for existing in load_retry(service, spreadsheet_id, sheet, headers) if _matches(sheet, existing, row))


def _column_letter(number: int) -> str:
    if number < 1:
        raise ValueError("header width must be positive")
    out = ""
    while number:
        number, rem = divmod(number - 1, 26)
        out = chr(65 + rem) + out
    return out


def _append_once(service, spreadsheet_id: str, sheet: str, headers: list[str], row: Mapping[str, object]) -> None:
    # Important: never use A:ZZ here. Google values.append discovers a logical table
    # inside the supplied range; a range wider than the real schema can cause later
    # appends to drift sideways when stray cells exist. Bound the table to the exact
    # schema width and overwrite the next empty logical row instead of inserting rows.
    last_col = _column_letter(len(headers))
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet}'!A:{last_col}",
        valueInputOption="RAW",
        insertDataOption="OVERWRITE",
        includeValuesInResponse=True,
        body={"values": [[str(row.get(header, "")) for header in headers]]},
    ).execute()


def _readback_until_settled(service, spreadsheet_id: str, sheet: str, headers: list[str], row: Mapping[str, object]) -> int:
    max_checks = 6
    for check in range(1, max_checks + 1):
        count = _readback_count(service, spreadsheet_id, sheet, headers, row)
        if count:
            return count
        if check < max_checks:
            time.sleep(min(6.0, 0.5 * (2 ** (check - 1))))
    return 0


def append_row_retry(service, spreadsheet_id: str, sheet: str, headers: list[str], row: Mapping[str, object]) -> None:
    before = _readback_count(service, spreadsheet_id, sheet, headers, row)
    if before == 1:
        return
    if before > 1:
        raise RuntimeError(f"{sheet} pre-write dedupe expected at most one row; found {before}")

    # One logical write only. If the transport result is ambiguous we reconcile with
    # read-only checks. We never automatically write the same record again because
    # that is exactly how duplicate/diagonal queue corruption was created previously.
    write_error: Exception | None = None
    try:
        _append_once(service, spreadsheet_id, sheet, headers, row)
    except Exception as exc:
        write_error = exc
        if not _retryable(exc):
            raise

    after = _readback_until_settled(service, spreadsheet_id, sheet, headers, row)
    if after == 1:
        return
    if after > 1:
        raise RuntimeError(f"{sheet} append reconciliation found duplicate rows: {after}") from write_error
    if write_error is not None:
        raise RuntimeError(f"{sheet} ambiguous append not visible after readback; refusing duplicate write") from write_error
    raise RuntimeError(f"{sheet} append acknowledged but row not visible after readback; refusing duplicate write")


def candidate_ok_draft_first(candidate, qualification, contact, *, country: str) -> bool:
    # Project Leads v14: MX is quality evidence for draft_first, not an absolute
    # concept blocker. Preserve every other official-site/role/fit gate by delegating
    # to the canonical predicate after normalising only this one evidence state.
    if _text(contact.get("mx_status")).casefold() == "missing":
        contact = dict(contact)
        contact["mx_status"] = "unknown"
    return _original_candidate_ok(candidate, qualification, contact, country=country)


def main() -> int:
    legacy.load = load_retry
    legacy.append_row = append_row_retry
    legacy.candidate_ok = candidate_ok_draft_first
    try:
        return legacy.main()
    finally:
        legacy.load = _original_load
        legacy.append_row = _original_append_row
        legacy.candidate_ok = _original_candidate_ok


if __name__ == "__main__":
    raise SystemExit(main())
