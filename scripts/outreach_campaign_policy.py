from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off", ""}


@dataclass(frozen=True)
class PolicyDecision:
    send_allowed: bool
    reason: str
    effective_mode: str
    effective_daily_limit: int
    effective_max_sends_per_run: int
    ramp_day: int | None


def parse_bool(value: str | None, *, default: bool = False, name: str = "value") -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be true or false")


def parse_optional_date(value: str | None, *, name: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must use YYYY-MM-DD") from exc


def decide_policy(
    *,
    now: datetime,
    timezone_name: str,
    mode: str,
    daily_limit: int,
    max_sends_per_run: int,
    natural_pacing: bool,
    campaign_start_date: date | None,
    campaign_end_date: date | None,
    slow_ramp_enabled: bool,
    ramp_start_date: date | None,
    ramp_start_limit: int,
    ramp_increment_per_day: int,
) -> PolicyDecision:
    mode = mode.strip().lower()
    if mode not in {"validate", "verify", "live"}:
        raise ValueError("OUTREACH_MODE must be validate, verify, or live")
    if not 1 <= daily_limit <= 100:
        raise ValueError("OUTREACH_DAILY_LIMIT must be between 1 and 100")
    if not 1 <= max_sends_per_run <= 10:
        raise ValueError("OUTREACH_MAX_SENDS_PER_RUN must be between 1 and 10")
    if not 1 <= ramp_start_limit <= 100:
        raise ValueError("OUTREACH_RAMP_START_LIMIT must be between 1 and 100")
    if not 1 <= ramp_increment_per_day <= 100:
        raise ValueError("OUTREACH_RAMP_INCREMENT_PER_DAY must be between 1 and 100")
    if campaign_start_date and campaign_end_date and campaign_end_date < campaign_start_date:
        raise ValueError("OUTREACH_CAMPAIGN_END_DATE cannot be before OUTREACH_CAMPAIGN_START_DATE")

    local_date = now.astimezone(ZoneInfo(timezone_name)).date()
    send_allowed = True
    reason = "active_window"

    if campaign_start_date and local_date < campaign_start_date:
        send_allowed = False
        reason = "campaign_not_started"
    elif campaign_end_date and local_date > campaign_end_date:
        send_allowed = False
        reason = "campaign_ended"

    effective_daily_limit = daily_limit
    ramp_day: int | None = None
    if slow_ramp_enabled:
        if ramp_start_date is None:
            raise ValueError("OUTREACH_RAMP_START_DATE is required when slow ramp is enabled")
        if local_date < ramp_start_date:
            send_allowed = False
            reason = "ramp_not_started"
            ramp_day = 0
            effective_daily_limit = min(daily_limit, ramp_start_limit)
        else:
            ramp_day = (local_date - ramp_start_date).days + 1
            effective_daily_limit = min(
                daily_limit,
                ramp_start_limit + (ramp_day - 1) * ramp_increment_per_day,
            )

    effective_max_sends_per_run = 1 if natural_pacing else max_sends_per_run
    effective_mode = "validate" if mode == "live" and not send_allowed else mode

    return PolicyDecision(
        send_allowed=send_allowed,
        reason=reason,
        effective_mode=effective_mode,
        effective_daily_limit=effective_daily_limit,
        effective_max_sends_per_run=effective_max_sends_per_run,
        ramp_day=ramp_day,
    )


def decision_from_env(now: datetime | None = None) -> PolicyDecision:
    now = now or datetime.now(timezone.utc)
    timezone_name = os.getenv("OUTREACH_TIMEZONE", "Europe/Amsterdam").strip() or "Europe/Amsterdam"
    return decide_policy(
        now=now,
        timezone_name=timezone_name,
        mode=os.getenv("OUTREACH_MODE", "validate"),
        daily_limit=int(os.getenv("OUTREACH_DAILY_LIMIT", "50") or "50"),
        max_sends_per_run=int(os.getenv("OUTREACH_MAX_SENDS_PER_RUN", "2") or "2"),
        natural_pacing=parse_bool(
            os.getenv("OUTREACH_NATURAL_PACING"), default=False, name="OUTREACH_NATURAL_PACING"
        ),
        campaign_start_date=parse_optional_date(
            os.getenv("OUTREACH_CAMPAIGN_START_DATE"), name="OUTREACH_CAMPAIGN_START_DATE"
        ),
        campaign_end_date=parse_optional_date(
            os.getenv("OUTREACH_CAMPAIGN_END_DATE"), name="OUTREACH_CAMPAIGN_END_DATE"
        ),
        slow_ramp_enabled=parse_bool(
            os.getenv("OUTREACH_SLOW_RAMP_ENABLED"), default=False, name="OUTREACH_SLOW_RAMP_ENABLED"
        ),
        ramp_start_date=parse_optional_date(
            os.getenv("OUTREACH_RAMP_START_DATE"), name="OUTREACH_RAMP_START_DATE"
        ),
        ramp_start_limit=int(os.getenv("OUTREACH_RAMP_START_LIMIT", "2") or "2"),
        ramp_increment_per_day=int(os.getenv("OUTREACH_RAMP_INCREMENT_PER_DAY", "2") or "2"),
    )


def emit_github_outputs(decision: PolicyDecision) -> None:
    pairs = {
        "send_allowed": "true" if decision.send_allowed else "false",
        "reason": decision.reason,
        "effective_mode": decision.effective_mode,
        "effective_daily_limit": str(decision.effective_daily_limit),
        "effective_max_sends_per_run": str(decision.effective_max_sends_per_run),
        "ramp_day": "" if decision.ramp_day is None else str(decision.ramp_day),
    }
    output_path = os.getenv("GITHUB_OUTPUT", "").strip()
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as handle:
            for key, value in pairs.items():
                handle.write(f"{key}={value}\n")
    for key, value in pairs.items():
        print(f"{key}={value}")


def main() -> int:
    decision = decision_from_env()
    emit_github_outputs(decision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
