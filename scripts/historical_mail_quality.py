"""Read-only email quality checks using the current Leadscanner validator.

Input is an in-memory review record, never written to public source or logs.
Historical recipients remain excluded from new-lead workflows.
"""
from __future__ import annotations

from outreach_stages import validate_mail


def check_reviewed_copy(candidate: dict, subject: str, body: str) -> str:
    """Fixed QA verdict, no recipient or body returned."""
    if not isinstance(candidate, dict) or not isinstance(subject, str) or not isinstance(body, str):
        return "hold_invalid_input"
    if not subject.strip() or not body.strip():
        return "hold_missing_copy"
    try:
        reasons = validate_mail(candidate, subject, body)
    except (TypeError, ValueError):
        return "hold_invalid_evidence"
    return "quality_pass" if not reasons else "quality_hold"
