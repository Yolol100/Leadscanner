#!/usr/bin/env python3
from __future__ import annotations

import re
import time
from typing import Mapping

import outreach_draft_first_prepare as legacy
from prospect_intelligence import canonical_domain

_original_append_row = legacy.append_row


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
    return sum(1 for existing in legacy.load(service, spreadsheet_id, sheet, headers) if _matches(sheet, existing, row))


def append_row_retry(service, spreadsheet_id: str, sheet: str, headers: list[str], row: Mapping[str, object]) -> None:
    before = _readback_count(service, spreadsheet_id, sheet, headers, row)
    if before == 1:
        return
    if before > 1:
        raise RuntimeError(f"{sheet} pre-write dedupe expected at most one row; found {before}")

    max_attempts = 4
    for attempt in range(1, max_attempts + 1):
        try:
            _original_append_row(service, spreadsheet_id, sheet, headers, row)
        except Exception as exc:
            after_error = _readback_count(service, spreadsheet_id, sheet, headers, row)
            if after_error == 1:
                return
            if after_error > 1:
                raise RuntimeError(f"{sheet} ambiguous append created duplicate rows: {after_error}") from exc
            if not _retryable(exc) or attempt >= max_attempts:
                raise
            time.sleep(min(8.0, 0.75 * (2 ** (attempt - 1))))
            continue

        after = _readback_count(service, spreadsheet_id, sheet, headers, row)
        if after == 1:
            return
        if after > 1:
            raise RuntimeError(f"{sheet} append readback found duplicate rows: {after}")
        if attempt >= max_attempts:
            raise RuntimeError(f"{sheet} append readback did not find the written row")
        time.sleep(min(8.0, 0.75 * (2 ** (attempt - 1))))

    raise RuntimeError("unreachable draft-first prepare retry state")


def main() -> int:
    legacy.append_row = append_row_retry
    try:
        return legacy.main()
    finally:
        legacy.append_row = _original_append_row


if __name__ == "__main__":
    raise SystemExit(main())
