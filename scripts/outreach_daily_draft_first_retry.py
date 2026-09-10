#!/usr/bin/env python3
from __future__ import annotations

import json
import time

import outreach_daily_batch_drafts as base
import outreach_daily_draft_first as legacy

_original_mark_concepts = base._mark_concepts
_original_eligible = legacy.eligible


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


def _normalise_draft_mx(row):
    source = str(row.get("source") or "")
    if not source.startswith("agent_offer:"):
        return row
    try:
        meta = json.loads(source.split(":", 1)[1])
    except (ValueError, TypeError):
        return row
    if str(meta.get("contact_mx_status") or "").strip().casefold() != "missing":
        return row
    out = dict(row)
    meta["contact_mx_status"] = "unknown"
    out["source"] = "agent_offer:" + json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
    return out


def eligible_draft_first(queue_rows, suppressions, *, country: str):
    # Project Leads v14 treats MX as quality evidence for draft-first review, not
    # as live-send permission. Only normalise this evidence state; all role,
    # official-source, suppression, fit, copy and uniqueness gates stay canonical.
    normalised = [_normalise_draft_mx(row) for row in queue_rows]
    return _original_eligible(normalised, suppressions, country=country)


def main(argv=None) -> int:
    base._mark_concepts = mark_concepts_retry
    legacy.eligible = eligible_draft_first
    try:
        return legacy.main(argv)
    finally:
        base._mark_concepts = _original_mark_concepts
        legacy.eligible = _original_eligible


if __name__ == "__main__":
    raise SystemExit(main())
