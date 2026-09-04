from __future__ import annotations

import outreach_campaign_runtime as runtime


def _no_external_verifier_required(row: dict[str, str], now, max_age_days: int) -> bool:
    """Direct mijn.host SMTP uses syntax, suppression, compliance and bounce readback, not Reoon."""
    return True


def process() -> int:
    runtime.verification_is_fresh = _no_external_verifier_required
    return runtime.process()


if __name__ == "__main__":
    raise SystemExit(process())
