from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

DEFAULT_SIGNAL_MAX_AGE_DAYS = 30
MAX_SIGNAL_STRENGTH = 2


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _parse_iso(value: object) -> datetime | None:
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


def signal_timestamp(row: Mapping[str, object]) -> datetime | None:
    return _parse_iso(row.get("evidence_date")) or _parse_iso(row.get("detected_at"))


def signal_is_fresh(
    row: Mapping[str, object],
    *,
    now: datetime | None = None,
    max_age_days: int = DEFAULT_SIGNAL_MAX_AGE_DAYS,
) -> bool:
    if _text(row.get("status")).casefold() != "active":
        return False
    observed = signal_timestamp(row)
    if observed is None:
        return False
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if observed > now + timedelta(days=1):
        return False
    return observed >= now - timedelta(days=max(1, max_age_days))


def active_signal_score(
    candidate_id: str,
    rows: Sequence[Mapping[str, object]],
    *,
    now: datetime | None = None,
    max_age_days: int = DEFAULT_SIGNAL_MAX_AGE_DAYS,
) -> int:
    score = 0
    for row in rows:
        if _text(row.get("candidate_id")) != _text(candidate_id):
            continue
        if not signal_is_fresh(row, now=now, max_age_days=max_age_days):
            continue
        try:
            strength = int(_text(row.get("strength")) or "0")
        except ValueError:
            continue
        score = max(score, max(0, min(strength, MAX_SIGNAL_STRENGTH)))
    return score
