#!/usr/bin/env python3
from __future__ import annotations

import time
from typing import Sequence

import prospect_discovery_runtime as legacy

_original_append_rows = legacy.append_rows


def _first_column_range(range_name: str) -> str:
    sheet = range_name.split('!', 1)[0]
    return f"{sheet}!A:A"


def _retryable(exc: BaseException) -> bool:
    text = str(exc).casefold()
    return isinstance(exc, (OSError, TimeoutError)) or any(token in text for token in (
        'ssl', 'eof occurred', 'timed out', 'timeout', 'connection reset', 'connection aborted',
        'temporarily unavailable', 'rate limit', '429', '500', '502', '503', '504',
    ))


def _existing_ids(service, spreadsheet_id: str, range_name: str) -> set[str]:
    max_attempts = 4
    for attempt in range(1, max_attempts + 1):
        try:
            values = legacy.get_values(service, spreadsheet_id, _first_column_range(range_name))
            return {str(row[0]).strip() for row in values if row and str(row[0]).strip()}
        except Exception as exc:
            if not _retryable(exc) or attempt >= max_attempts:
                raise
            time.sleep(min(8.0, 0.75 * (2 ** (attempt - 1))))
    raise RuntimeError('unreachable Sheets read retry state')


def append_rows_retry(service, spreadsheet_id: str, range_name: str, rows: Sequence[Sequence[object]]) -> None:
    pending = [list(row) for row in rows if row]
    if not pending:
        return
    max_attempts = 4
    for attempt in range(1, max_attempts + 1):
        existing = _existing_ids(service, spreadsheet_id, range_name)
        pending = [row for row in pending if not str(row[0]).strip() or str(row[0]).strip() not in existing]
        if not pending:
            return
        try:
            _original_append_rows(service, spreadsheet_id, range_name, pending)
            existing_after = _existing_ids(service, spreadsheet_id, range_name)
            missing = [row for row in pending if str(row[0]).strip() and str(row[0]).strip() not in existing_after]
            if missing:
                raise RuntimeError(f"Sheets append readback missing {len(missing)} row ids")
            return
        except Exception as exc:
            if not _retryable(exc) or attempt >= max_attempts:
                raise
            time.sleep(min(8.0, 0.75 * (2 ** (attempt - 1))))
    raise RuntimeError('unreachable append retry state')


def main(argv=None) -> int:
    legacy.append_rows = append_rows_retry
    try:
        return legacy.main(argv)
    finally:
        legacy.append_rows = _original_append_rows


if __name__ == '__main__':
    raise SystemExit(main())
