#!/usr/bin/env python3
from __future__ import annotations

import time

import outreach_daily_batch_drafts as base
import outreach_daily_draft_first as legacy

_original_mark_concepts = base._mark_concepts


def _retryable(exc: BaseException) -> bool:
    value = str(exc).casefold()
    return isinstance(exc, (OSError, TimeoutError)) or any(token in value for token in (
        "ssl", "eof occurred", "timed out", "timeout", "connection reset", "connection aborted",
        "temporarily unavailable", "rate limit", "429", "500", "502", "503", "504",
    ))


def mark_concepts_retry(service, spreadsheet_id: str, selected) -> None:
    max_attempts = 4
    for attempt in range(1, max_attempts + 1):
        try:
            _original_mark_concepts(service, spreadsheet_id, selected)
            return
        except Exception as exc:
            if not _retryable(exc) or attempt >= max_attempts:
                raise
            time.sleep(min(8.0, 0.75 * (2 ** (attempt - 1))))
    raise RuntimeError("unreachable concept-status retry state")


def main(argv=None) -> int:
    base._mark_concepts = mark_concepts_retry
    try:
        return legacy.main(argv)
    finally:
        base._mark_concepts = _original_mark_concepts


if __name__ == "__main__":
    raise SystemExit(main())
