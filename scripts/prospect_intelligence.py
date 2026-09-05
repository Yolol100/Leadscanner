#!/usr/bin/env python3
"""Deterministic intelligence layer for Webactueel prospecting.

This module is deliberately transport-neutral. It derives entity, freshness,
source-performance, signal, lookalike and evidence-graph views from existing
Leadscanner/Sheet state. It never qualifies a lead, changes compliance, creates
mail copy, or sends mail.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable, Mapping, Sequence
from urllib.parse import urlparse

OBSERVATION_HEADERS = [
    "observation_id", "observed_at", "entity_id", "company", "website",
    "source_id", "source_type", "source_url", "country", "matched_terms", "outcome",
]
SIGNAL_HEADERS = [
    "signal_id", "candidate_id", "detected_at", "signal_type", "evidence_url",
    "evidence_date", "strength", "confidence", "source_id", "status", "note",
]
ENTITY_HEADERS = [
    "entity_id", "canonical_domain", "company", "aliases", "first_seen", "last_seen",
    "freshness", "candidate_count", "source_ids", "status",
]
SOURCE_METRIC_HEADERS = [
    "generated_at", "source_id", "enabled", "approved", "candidate_total", "discovered",
    "qualified", "hold", "rejected", "strong_signals", "contacts_ready", "lead_concept",
    "lead_sent", "lead_bounced", "lead_positive", "lead_negative", "lead_customer",
    "qualification_rate", "contact_rate", "customer_rate",
]
EVIDENCE_HEADERS = [
    "edge_id", "observed_at", "entity_id", "candidate_id", "edge_type", "source_ref",
    "target_ref", "evidence_url", "confidence", "note",
]
LOOKALIKE_HEADERS = [
    "generated_at", "candidate_id", "entity_id", "seed_customers", "shared_terms",
    "same_country", "similarity", "note",
]

ALLOWED_SIGNAL_CONFIDENCE = {"low", "medium", "high"}
ALLOWED_SIGNAL_STATUS = {"active", "expired", "rejected"}


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def truthy(value: object) -> bool:
    return _text(value).casefold() in {"1", "true", "yes", "ja", "y", "on"}


def stable_id(prefix: str, *parts: object, length: int = 20) -> str:
    raw = "|".join(_text(part).casefold() for part in parts).encode("utf-8")
    return f"{prefix}-" + hashlib.sha256(raw).hexdigest()[:length]


def canonical_domain(value: object) -> str:
    raw = _text(value)
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or " " in host or "." not in host:
        return ""
    return host


def entity_id_for_domain(domain: object) -> str:
    value = canonical_domain(domain)
    return stable_id("entity", value) if value else ""


def parse_iso(value: object) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def isoformat(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def freshness_state(last_seen: object, *, now: datetime | None = None, stale_days: int = 30) -> str:
    observed = parse_iso(last_seen)
    if observed is None:
        return "unknown"
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age_days = max(0.0, (now - observed).total_seconds() / 86400.0)
    return "fresh" if age_days <= max(1, stale_days) else "stale"


def split_terms(value: object) -> tuple[str, ...]:
    output: list[str] = []
    for item in re.split(r"[,;\n]", _text(value).casefold()):
        item = _text(item)
        if item and item not in output:
            output.append(item)
    return tuple(output[:50])


def clamp_target(raw: object, max_total: int) -> int:
    max_total = max(1, int(max_total))
    try:
        value = int(raw) if _text(raw) else max_total
    except (TypeError, ValueError):
        value = max_total
    return max(1, min(value, max_total))


def target_summary(discovered: int, target: int) -> dict[str, object]:
    discovered = max(0, int(discovered))
    target = max(1, int(target))
    return {
        "target_new": target,
        "target_met": discovered >= target,
        "target_gap": max(0, target - discovered),
    }


def make_observation_row(
    *, run_id: object, observed_at: object, candidate: object, outcome: str,
) -> list[str]:
    website = _text(getattr(candidate, "website", ""))
    domain = canonical_domain(website)
    source_id = _text(getattr(candidate, "source_id", ""))
    observation_id = stable_id("obs", run_id, source_id, domain)
    matched = getattr(candidate, "matched_terms", ()) or ()
    return [
        observation_id,
        _text(observed_at),
        entity_id_for_domain(domain),
        _text(getattr(candidate, "company", "")),
        website,
        source_id,
        _text(getattr(candidate, "source_type", "")),
        _text(getattr(candidate, "source_url", "")),
        _text(getattr(candidate, "country", "")),
        ", ".join(_text(term) for term in matched if _text(term)),
        outcome if outcome in {"new", "duplicate"} else "observed",
    ]


def normalize_signal(row: Mapping[str, object], *, known_candidate_ids: set[str] | None = None) -> dict[str, str]:
    candidate_id = _text(row.get("candidate_id"))
    if not candidate_id:
        raise ValueError("candidate_id is required")
    if known_candidate_ids is not None and candidate_id not in known_candidate_ids:
        raise ValueError(f"unknown candidate_id: {candidate_id}")
    signal_type = _text(row.get("signal_type")).casefold().replace(" ", "_")
    if not signal_type or not re.fullmatch(r"[a-z0-9_\-]{2,80}", signal_type):
        raise ValueError("signal_type must be a stable machine label")
    evidence_url = _text(row.get("evidence_url"))
    if evidence_url:
        parsed = urlparse(evidence_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("evidence_url must be a public http(s) URL without credentials")
    detected_at = parse_iso(row.get("detected_at"))
    if detected_at is None:
        raise ValueError("detected_at must be an ISO timestamp")
    evidence_date = _text(row.get("evidence_date"))
    if evidence_date and parse_iso(evidence_date) is None:
        raise ValueError("evidence_date must be ISO date/time when present")
    try:
        strength = int(_text(row.get("strength")))
    except ValueError as exc:
        raise ValueError("strength must be 0, 1 or 2") from exc
    if strength not in {0, 1, 2}:
        raise ValueError("strength must be 0, 1 or 2")
    confidence = _text(row.get("confidence")).casefold() or "medium"
    if confidence not in ALLOWED_SIGNAL_CONFIDENCE:
        raise ValueError("confidence must be low, medium or high")
    status = _text(row.get("status")).casefold() or "active"
    if status not in ALLOWED_SIGNAL_STATUS:
        raise ValueError("status must be active, expired or rejected")
    source_id = _text(row.get("source_id"))
    if not source_id:
        raise ValueError("source_id is required")
    signal_id = _text(row.get("signal_id")) or stable_id(
        "signal", candidate_id, signal_type, evidence_url, evidence_date or isoformat(detected_at)
    )
    return {
        "signal_id": signal_id,
        "candidate_id": candidate_id,
        "detected_at": isoformat(detected_at),
        "signal_type": signal_type,
        "evidence_url": evidence_url,
        "evidence_date": evidence_date,
        "strength": str(strength),
        "confidence": confidence,
        "source_id": source_id,
        "status": status,
        "note": _text(row.get("note"))[:500],
    }


def validate_signals(
    rows: Sequence[Mapping[str, object]], *, known_candidate_ids: set[str] | None = None
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=2):
        try:
            signal = normalize_signal(row, known_candidate_ids=known_candidate_ids)
        except ValueError as exc:
            raise ValueError(f"ProspectSignals row {index}: {exc}") from exc
        if signal["signal_id"] in seen:
            raise ValueError(f"ProspectSignals row {index}: duplicate signal_id")
        seen.add(signal["signal_id"])
        output.append(signal)
    return output


def _candidate_status(rows: Iterable[Mapping[str, object]]) -> str:
    statuses = {_text(row.get("status")).casefold() for row in rows if _text(row.get("status"))}
    if "qualified" in statuses:
        return "qualified"
    if "discovered" in statuses:
        return "discovered"
    if "hold" in statuses:
        return "hold"
    if statuses == {"rejected"}:
        return "rejected"
    return sorted(statuses)[0] if statuses else "unknown"


def build_entities(
    candidate_rows: Sequence[Mapping[str, object]],
    observation_rows: Sequence[Mapping[str, object]] = (),
    *,
    now: datetime | None = None,
    stale_days: int = 30,
) -> list[list[object]]:
    buckets: dict[str, dict[str, object]] = {}
    candidate_groups: dict[str, list[Mapping[str, object]]] = defaultdict(list)

    for row in candidate_rows:
        domain = canonical_domain(row.get("website"))
        if not domain:
            continue
        candidate_groups[domain].append(row)
        bucket = buckets.setdefault(domain, {"companies": set(), "sources": set(), "times": []})
        company = _text(row.get("company"))
        if company:
            bucket["companies"].add(company)
        source_id = _text(row.get("source_id"))
        if source_id:
            bucket["sources"].add(source_id)
        observed = parse_iso(row.get("discovered_at"))
        if observed:
            bucket["times"].append(observed)

    for row in observation_rows:
        domain = canonical_domain(row.get("website"))
        if not domain:
            continue
        bucket = buckets.setdefault(domain, {"companies": set(), "sources": set(), "times": []})
        company = _text(row.get("company"))
        if company:
            bucket["companies"].add(company)
        source_id = _text(row.get("source_id"))
        if source_id:
            bucket["sources"].add(source_id)
        observed = parse_iso(row.get("observed_at"))
        if observed:
            bucket["times"].append(observed)

    result: list[list[object]] = []
    for domain in sorted(buckets):
        bucket = buckets[domain]
        times = sorted(bucket["times"])
        first_seen = isoformat(times[0]) if times else ""
        last_seen = isoformat(times[-1]) if times else ""
        companies = sorted(bucket["companies"], key=lambda value: (len(value), value.casefold()))
        company = companies[0] if companies else domain
        aliases = [value for value in companies if value != company]
        rows = candidate_groups.get(domain, [])
        result.append([
            entity_id_for_domain(domain),
            domain,
            company,
            " | ".join(aliases),
            first_seen,
            last_seen,
            freshness_state(last_seen, now=now, stale_days=stale_days),
            len(rows),
            ", ".join(sorted(bucket["sources"])),
            _candidate_status(rows),
        ])
    return result


def _rate(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "0"
    return f"{numerator / denominator:.4f}"


def build_source_metrics(
    source_rows: Sequence[Mapping[str, object]],
    candidate_rows: Sequence[Mapping[str, object]],
    contact_rows: Sequence[Mapping[str, object]],
    lead_rows: Sequence[Mapping[str, object]],
    signal_rows: Sequence[Mapping[str, object]],
    *,
    generated_at: str,
) -> list[list[object]]:
    by_source: dict[str, dict[str, object]] = {}
    for source in source_rows:
        source_id = _text(source.get("source_id"))
        if not source_id:
            continue
        by_source[source_id] = {
            "enabled": truthy(source.get("enabled")),
            "approved": truthy(source.get("approved")),
            "candidates": [],
            "signals": 0,
            "contacts_ready": 0,
            "lead_statuses": [],
        }

    candidate_by_id: dict[str, Mapping[str, object]] = {}
    candidate_source_by_domain: dict[str, str] = {}
    for row in candidate_rows:
        candidate_id = _text(row.get("candidate_id"))
        source_id = _text(row.get("source_id"))
        domain = canonical_domain(row.get("website"))
        if candidate_id:
            candidate_by_id[candidate_id] = row
        if source_id:
            bucket = by_source.setdefault(source_id, {
                "enabled": False, "approved": False, "candidates": [], "signals": 0,
                "contacts_ready": 0, "lead_statuses": [],
            })
            bucket["candidates"].append(row)
            if domain:
                candidate_source_by_domain[domain] = source_id

    for row in signal_rows:
        if _text(row.get("status")).casefold() != "active":
            continue
        try:
            strength = int(_text(row.get("strength")) or 0)
        except ValueError:
            continue
        if strength < 2:
            continue
        candidate = candidate_by_id.get(_text(row.get("candidate_id")))
        if not candidate:
            continue
        source_id = _text(candidate.get("source_id"))
        if source_id in by_source:
            by_source[source_id]["signals"] += 1

    for row in contact_rows:
        if _text(row.get("status")).casefold() != "ready":
            continue
        candidate = candidate_by_id.get(_text(row.get("candidate_id")))
        if not candidate:
            continue
        source_id = _text(candidate.get("source_id"))
        if source_id in by_source:
            by_source[source_id]["contacts_ready"] += 1

    for row in lead_rows:
        domain = canonical_domain(row.get("Website") or row.get("website"))
        source_id = candidate_source_by_domain.get(domain)
        if not source_id or source_id not in by_source:
            continue
        by_source[source_id]["lead_statuses"].append(
            _text(row.get("Status") or row.get("status")).casefold()
        )

    output: list[list[object]] = []
    for source_id in sorted(by_source):
        bucket = by_source[source_id]
        candidates = bucket["candidates"]
        statuses = [_text(row.get("status")).casefold() for row in candidates]
        total = len(candidates)
        qualified = statuses.count("qualified")
        contact_ready = int(bucket["contacts_ready"])
        lead_statuses = list(bucket["lead_statuses"])
        customer = lead_statuses.count("klant") + lead_statuses.count("customer")
        output.append([
            generated_at,
            source_id,
            str(bool(bucket["enabled"])).upper(),
            str(bool(bucket["approved"])).upper(),
            total,
            statuses.count("discovered"),
            qualified,
            statuses.count("hold"),
            statuses.count("rejected"),
            int(bucket["signals"]),
            contact_ready,
            lead_statuses.count("concept"),
            lead_statuses.count("verzonden") + lead_statuses.count("sent"),
            lead_statuses.count("onbestelbaar") + lead_statuses.count("bounced"),
            lead_statuses.count("positief") + lead_statuses.count("positive"),
            lead_statuses.count("negatief") + lead_statuses.count("negative"),
            customer,
            _rate(qualified, total),
            _rate(contact_ready, qualified),
            _rate(customer, total),
        ])
    return output


def build_evidence_edges(
    candidate_rows: Sequence[Mapping[str, object]],
    signal_rows: Sequence[Mapping[str, object]],
    contact_rows: Sequence[Mapping[str, object]],
    lead_rows: Sequence[Mapping[str, object]],
) -> list[list[object]]:
    edges: list[list[object]] = []
    candidate_by_id: dict[str, Mapping[str, object]] = {}
    candidate_by_domain: dict[str, Mapping[str, object]] = {}

    for row in candidate_rows:
        candidate_id = _text(row.get("candidate_id"))
        domain = canonical_domain(row.get("website"))
        if not candidate_id or not domain:
            continue
        candidate_by_id[candidate_id] = row
        candidate_by_domain[domain] = row
        observed_at = _text(row.get("discovered_at"))
        source_id = _text(row.get("source_id"))
        edges.append([
            stable_id("edge", "source", candidate_id, source_id),
            observed_at,
            entity_id_for_domain(domain),
            candidate_id,
            "source_discovery",
            source_id,
            _text(row.get("website")),
            _text(row.get("source_url")),
            "high",
            f"status={_text(row.get('status')).casefold() or 'unknown'}",
        ])

    for row in signal_rows:
        candidate_id = _text(row.get("candidate_id"))
        candidate = candidate_by_id.get(candidate_id)
        if not candidate:
            continue
        domain = canonical_domain(candidate.get("website"))
        signal_id = _text(row.get("signal_id"))
        edges.append([
            stable_id("edge", "signal", signal_id or candidate_id),
            _text(row.get("detected_at")),
            entity_id_for_domain(domain),
            candidate_id,
            "signal",
            _text(row.get("source_id")),
            _text(row.get("signal_type")),
            _text(row.get("evidence_url")),
            _text(row.get("confidence")) or "medium",
            f"strength={_text(row.get('strength'))}; status={_text(row.get('status'))}",
        ])

    for row in contact_rows:
        candidate_id = _text(row.get("candidate_id"))
        candidate = candidate_by_id.get(candidate_id)
        if not candidate:
            continue
        domain = canonical_domain(candidate.get("website"))
        checked_at = _text(row.get("checked_at"))
        status = _text(row.get("status")).casefold()
        source_url = _text(row.get("source_url"))
        edges.append([
            stable_id("edge", "contact", candidate_id, source_url, status),
            checked_at,
            entity_id_for_domain(domain),
            candidate_id,
            "contact_evidence",
            source_url,
            status or "unknown",
            source_url,
            "high" if status == "ready" else "medium",
            _text(row.get("reason"))[:500],
        ])

    for row in lead_rows:
        domain = canonical_domain(row.get("Website") or row.get("website"))
        candidate = candidate_by_domain.get(domain)
        if not candidate:
            continue
        candidate_id = _text(candidate.get("candidate_id"))
        status = _text(row.get("Status") or row.get("status")).casefold()
        if not status:
            continue
        edges.append([
            stable_id("edge", "lead-status", candidate_id, status),
            "",
            entity_id_for_domain(domain),
            candidate_id,
            "lead_outcome",
            "Leadlijst",
            status,
            "",
            "medium",
            "Minimal registry status; not a full causal attribution claim.",
        ])

    edges.sort(key=lambda row: (str(row[2]), str(row[4]), str(row[0])))
    return edges


def build_lookalike_recommendations(
    candidate_rows: Sequence[Mapping[str, object]],
    lead_rows: Sequence[Mapping[str, object]],
    *,
    generated_at: str,
) -> list[list[object]]:
    customer_domains = {
        canonical_domain(row.get("Website") or row.get("website"))
        for row in lead_rows
        if _text(row.get("Status") or row.get("status")).casefold() in {"klant", "customer"}
    }
    customer_domains.discard("")
    seed_rows = [row for row in candidate_rows if canonical_domain(row.get("website")) in customer_domains]
    if not seed_rows:
        return []

    seed_terms: set[str] = set()
    seed_countries: set[str] = set()
    for row in seed_rows:
        seed_terms.update(split_terms(row.get("matched_terms")))
        country = _text(row.get("country")).casefold()
        if country:
            seed_countries.add(country)

    output: list[list[object]] = []
    for row in candidate_rows:
        domain = canonical_domain(row.get("website"))
        if not domain or domain in customer_domains:
            continue
        candidate_id = _text(row.get("candidate_id"))
        terms = set(split_terms(row.get("matched_terms")))
        union = terms | seed_terms
        shared = sorted(terms & seed_terms)
        term_score = len(shared) / len(union) if union else 0.0
        country = _text(row.get("country")).casefold()
        same_country = bool(country and country in seed_countries)
        country_score = 1.0 if same_country else 0.0
        similarity = round((0.7 * term_score) + (0.3 * country_score), 4)
        if similarity <= 0:
            continue
        output.append([
            generated_at,
            candidate_id,
            entity_id_for_domain(domain),
            len(seed_rows),
            ", ".join(shared),
            str(same_country).upper(),
            f"{similarity:.4f}",
            "Advisory only; never changes Customer Potential or send permission.",
        ])
    output.sort(key=lambda row: (-float(row[6]), str(row[1])))
    return output
