#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time

import outreach_daily_batch_drafts as base
import outreach_daily_draft_first as legacy
from prospect_discovery import host_key

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


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().casefold() in {"1", "true", "yes", "on"}


def _load_net_new_baseline() -> dict[str, set[str]]:
    path = os.getenv("DRAFT_FIRST_BASELINE_FILE", "").strip()
    required = _truthy_env("DRAFT_FIRST_REQUIRE_NET_NEW")
    if not path:
        if required:
            raise RuntimeError("net-new baseline path is required")
        return {"lead_ids": set(), "domains": set(), "emails": set()}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        if required:
            raise RuntimeError(f"net-new baseline unavailable: {exc}") from exc
        return {"lead_ids": set(), "domains": set(), "emails": set()}
    if not isinstance(raw, dict):
        if required:
            raise RuntimeError("net-new baseline must be a JSON object")
        return {"lead_ids": set(), "domains": set(), "emails": set()}

    lead_ids = {str(value).strip() for value in raw.get("lead_ids", []) if str(value).strip()}
    domains = {
        str(value).strip().casefold().removeprefix("www.")
        for value in raw.get("domains", [])
        if str(value).strip()
    }
    emails = {str(value).strip().casefold() for value in raw.get("emails", []) if str(value).strip()}
    return {"lead_ids": lead_ids, "domains": domains, "emails": emails}


def _filter_net_new(candidates, rejected):
    baseline = _load_net_new_baseline()
    if not any(baseline.values()):
        return candidates, rejected
    accepted = []
    updated_rejected = dict(rejected)
    for candidate in candidates:
        reasons = []
        if candidate.lead_id in baseline["lead_ids"]:
            reasons.append("lead id existed before run")
        if host_key(candidate.website) in baseline["domains"]:
            reasons.append("domain existed before run")
        if candidate.email.casefold() in baseline["emails"]:
            reasons.append("email existed before run")
        if reasons:
            updated_rejected[candidate.lead_id] = ["not net-new versus pre-run baseline", *reasons]
            continue
        accepted.append(candidate)
    return accepted, updated_rejected


def eligible_draft_first(queue_rows, suppressions, *, country: str):
    # Project Leads v14 treats MX as quality evidence for draft-first review, not
    # as live-send permission. Only normalise this evidence state; all role,
    # official-source, suppression, fit, copy and uniqueness gates stay canonical.
    normalised = [_normalise_draft_mx(row) for row in queue_rows]
    candidates, rejected = _original_eligible(normalised, suppressions, country=country)
    return _filter_net_new(candidates, rejected)


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
