from __future__ import annotations

import os
from dataclasses import replace

import outreach_campaign_runtime as runtime
from prospect_target_policy import canonical_country

POSTAL_PLACEHOLDER = "{{OUTREACH_POSTAL_ADDRESS}}"
_ORIGINAL_BUILD_MESSAGE = runtime.build_message
_ORIGINAL_BUILD_SEQUENCE_MESSAGE = runtime.build_sequence_message


def _no_external_verifier_required(row: dict[str, str], now, max_age_days: int) -> bool:
    """Direct mijn.host SMTP uses syntax, suppression, compliance and bounce readback, not Reoon."""
    return True


def _private_postal_address() -> str:
    address = os.getenv("OUTREACH_POSTAL_ADDRESS", "").strip()
    if not address:
        raise RuntimeError("OUTREACH_POSTAL_ADDRESS is required for US commercial email")
    return address


def _inject_private_postal(row: dict[str, str], body: str) -> str:
    body = str(body or "")
    if canonical_country(row.get("country", "")) != "US":
        return body
    address = _private_postal_address()
    if POSTAL_PLACEHOLDER not in body:
        raise RuntimeError("US commercial email is missing the private postal placeholder")
    return body.replace(POSTAL_PLACEHOLDER, address)


def _append_private_us_footer(row: dict[str, str], body: str) -> str:
    body = str(body or "").strip()
    if canonical_country(row.get("country", "")) != "US":
        return body
    address = _private_postal_address()
    if address.casefold() in body.casefold():
        return body
    return body + f"\n\nThis is a commercial message.\n{address}"


def _build_message_with_private_postal(row: dict[str, str], mailbox, stage: int):
    outbound = dict(row)
    body_key = "body" if stage == 1 else "followup_body"
    if stage == 1:
        outbound[body_key] = _inject_private_postal(outbound, outbound.get(body_key, ""))
    else:
        outbound[body_key] = _append_private_us_footer(outbound, outbound.get(body_key, ""))
    return _ORIGINAL_BUILD_MESSAGE(outbound, mailbox, stage)


def _build_sequence_message_with_private_postal(queue_row: dict[str, str], action, mailbox):
    if canonical_country(queue_row.get("country", "")) != "US":
        return _ORIGINAL_BUILD_SEQUENCE_MESSAGE(queue_row, action, mailbox)
    sequence_row = dict(action.row)
    if action.step_number == 1:
        sequence_row["body"] = _inject_private_postal(queue_row, sequence_row.get("body", ""))
    else:
        sequence_row["body"] = _append_private_us_footer(queue_row, sequence_row.get("body", ""))
    return _ORIGINAL_BUILD_SEQUENCE_MESSAGE(queue_row, replace(action, row=sequence_row), mailbox)


def _restore_blank_workflow_defaults() -> None:
    # GitHub Actions renders an unset repository variable as an empty string.
    # Settings.from_env only applies its defaults when the variable is absent,
    # so normalize the two send-window values here without changing policy.
    defaults = {
        "OUTREACH_SEND_WINDOW_START": "08:00",
        "OUTREACH_SEND_WINDOW_END": "18:00",
    }
    for name, value in defaults.items():
        if not os.getenv(name, "").strip():
            os.environ[name] = value


def process() -> int:
    _restore_blank_workflow_defaults()
    runtime.verification_is_fresh = _no_external_verifier_required
    runtime.build_message = _build_message_with_private_postal
    runtime.build_sequence_message = _build_sequence_message_with_private_postal
    return runtime.process()


if __name__ == "__main__":
    raise SystemExit(process())
