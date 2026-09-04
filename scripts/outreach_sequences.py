from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from hashlib import sha256
from typing import Iterable

from outreach_mailboxes import MailboxConfig
from outreach_sender import domain_of, parse_dt, utcnow

SEQUENCE_SHEET = "OutreachSequences"
SEQUENCE_HEADERS = [
    "lead_id",
    "sequence_id",
    "sequence_version",
    "step_number",
    "variant_id",
    "enabled",
    "subject",
    "body",
    "wait_minutes",
    "status",
    "selected",
    "scheduled_at",
    "sent_at",
    "message_id",
    "sender_mailbox_id",
    "sender_email",
    "last_error",
    "source",
]
MAX_SEQUENCE_STEPS = 50
MAX_VARIANTS_PER_STEP = 26
ALLOWED_VARIANTS = tuple(chr(code) for code in range(ord("A"), ord("Z") + 1))
ALLOWED_STATUSES = {"approved", "sent", "error", "paused", "not_selected"}


def truthy(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def enabled(row: dict[str, str]) -> bool:
    raw = str(row.get("enabled", "true") or "true").strip().lower()
    return raw not in {"0", "false", "no", "n", "off", "disabled"}


def _int(value: str, default: int = 0) -> int:
    try:
        return int(str(value or "").strip() or default)
    except ValueError:
        return default


def sequence_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        str(row.get("lead_id", "")).strip(),
        str(row.get("sequence_id", "")).strip(),
        str(row.get("sequence_version", "")).strip() or "1",
    )


def validate_sequence_rows(rows: Iterable[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    by_lead: dict[str, list[dict[str, str]]] = {}
    seen_keys: set[tuple[str, str, str, int, str]] = set()

    for row_number, row in enumerate(rows, start=2):
        lead_id, sequence_id, version = sequence_key(row)
        if not lead_id and not any(str(v).strip() for v in row.values()):
            continue
        if not lead_id:
            errors.append(f"row {row_number}: lead_id is required")
            continue
        if not sequence_id:
            errors.append(f"row {row_number}: sequence_id is required")
        step = _int(row.get("step_number", ""), -1)
        if step < 1 or step > MAX_SEQUENCE_STEPS:
            errors.append(f"row {row_number}: step_number must be between 1 and {MAX_SEQUENCE_STEPS}")
        variant = str(row.get("variant_id", "A") or "A").strip().upper()
        if variant not in ALLOWED_VARIANTS:
            errors.append(f"row {row_number}: variant_id must be A-Z")
        status = str(row.get("status", "approved") or "approved").strip().lower()
        if status not in ALLOWED_STATUSES:
            errors.append(f"row {row_number}: unsupported status {status}")
        wait = _int(row.get("wait_minutes", ""), -1)
        if wait < 0:
            errors.append(f"row {row_number}: wait_minutes must be >= 0")
        if step == 1 and wait != 0:
            errors.append(f"row {row_number}: step 1 wait_minutes must be 0")
        if enabled(row):
            if step == 1 and not str(row.get("subject", "")).strip():
                errors.append(f"row {row_number}: enabled step 1 variant requires subject")
            if not str(row.get("body", "")).strip():
                errors.append(f"row {row_number}: enabled variant requires body")
        key = (lead_id, sequence_id, version, step, variant)
        if key in seen_keys:
            errors.append(f"row {row_number}: duplicate sequence step/variant {key}")
        seen_keys.add(key)
        by_lead.setdefault(lead_id, []).append(row)

    for lead_id, lead_rows in by_lead.items():
        identities = {(sequence_key(row)[1], sequence_key(row)[2]) for row in lead_rows if enabled(row)}
        if len(identities) > 1:
            errors.append(f"lead {lead_id}: multiple enabled sequence identities are not allowed")
        steps: dict[int, list[dict[str, str]]] = {}
        for row in lead_rows:
            if not enabled(row):
                continue
            steps.setdefault(_int(row.get("step_number", ""), -1), []).append(row)
        positive_steps = sorted(step for step in steps if step > 0)
        if positive_steps and positive_steps != list(range(1, max(positive_steps) + 1)):
            errors.append(f"lead {lead_id}: enabled sequence steps must be contiguous from 1")
        for step, variants in steps.items():
            if len(variants) > MAX_VARIANTS_PER_STEP:
                errors.append(
                    f"lead {lead_id} step {step}: max {MAX_VARIANTS_PER_STEP} enabled variants"
                )
            waits = {_int(row.get("wait_minutes", ""), -1) for row in variants}
            if len(waits) > 1:
                errors.append(f"lead {lead_id} step {step}: all variants must use the same wait_minutes")
            selected = [row for row in variants if truthy(row.get("selected", ""))]
            if len(selected) > 1:
                errors.append(f"lead {lead_id} step {step}: only one variant may be selected")
            for row in selected:
                if str(row.get("status", "")).strip().lower() == "sent":
                    if not str(row.get("sent_at", "")).strip() or not str(row.get("message_id", "")).strip():
                        errors.append(
                            f"lead {lead_id} step {step}: sent selected variant requires sent_at and message_id"
                        )
    return errors


def group_sequence_rows(
    rows: Iterable[dict[str, str]],
) -> dict[str, list[tuple[int, dict[str, str]]]]:
    grouped: dict[str, list[tuple[int, dict[str, str]]]] = {}
    for row_number, row in enumerate(rows, start=2):
        lead_id = str(row.get("lead_id", "")).strip()
        if lead_id:
            grouped.setdefault(lead_id, []).append((row_number, row))
    return grouped


def _variant_sort_key(item: tuple[int, dict[str, str]]) -> tuple[str, int]:
    row_number, row = item
    return (str(row.get("variant_id", "A") or "A").strip().upper(), row_number)


def _stable_variant_index(lead_id: str, sequence_id: str, version: str, step: int, size: int) -> int:
    digest = sha256(f"{lead_id}|{sequence_id}|{version}|{step}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % size


def _jitter_minutes(lead_id: str, sequence_id: str, step: int, maximum: int) -> int:
    if maximum <= 0:
        return 0
    digest = sha256(f"jitter|{lead_id}|{sequence_id}|{step}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % (maximum + 1)


@dataclass(frozen=True)
class SequenceAction:
    row_number: int
    row: dict[str, str]
    step_number: int
    variant_id: str
    sequence_id: str
    sequence_version: str
    due_at: datetime
    previous_message_id: str
    references: tuple[str, ...]
    effective_subject: str
    is_final_step: bool


def _active_rows(lead_rows: list[tuple[int, dict[str, str]]]) -> list[tuple[int, dict[str, str]]]:
    return [item for item in lead_rows if enabled(item[1])]


def _step_map(
    lead_rows: list[tuple[int, dict[str, str]]],
) -> dict[int, list[tuple[int, dict[str, str]]]]:
    result: dict[int, list[tuple[int, dict[str, str]]]] = {}
    for item in _active_rows(lead_rows):
        step = _int(item[1].get("step_number", ""), -1)
        if step > 0:
            result.setdefault(step, []).append(item)
    for variants in result.values():
        variants.sort(key=_variant_sort_key)
    return result


def _sent_variant(variants: list[tuple[int, dict[str, str]]]) -> tuple[int, dict[str, str]] | None:
    selected_sent = [
        item
        for item in variants
        if truthy(item[1].get("selected", ""))
        and str(item[1].get("status", "")).strip().lower() == "sent"
        and parse_dt(item[1].get("sent_at", ""))
    ]
    if selected_sent:
        return selected_sent[0]
    sent = [
        item
        for item in variants
        if str(item[1].get("status", "")).strip().lower() == "sent"
        and parse_dt(item[1].get("sent_at", ""))
    ]
    return sent[0] if sent else None


def _selected_unsent(variants: list[tuple[int, dict[str, str]]]) -> tuple[int, dict[str, str]] | None:
    for item in variants:
        row = item[1]
        if truthy(row.get("selected", "")) and str(row.get("status", "approved")).strip().lower() == "approved":
            return item
    return None


def _choose_variant(
    variants: list[tuple[int, dict[str, str]]],
    lead_id: str,
    sequence_id: str,
    version: str,
    step: int,
) -> tuple[int, dict[str, str]] | None:
    selected = _selected_unsent(variants)
    if selected:
        return selected
    eligible = [
        item
        for item in variants
        if str(item[1].get("status", "approved") or "approved").strip().lower() == "approved"
    ]
    if not eligible:
        return None
    return eligible[_stable_variant_index(lead_id, sequence_id, version, step, len(eligible))]


def next_sequence_action(
    lead_rows: list[tuple[int, dict[str, str]]],
    *,
    now: datetime,
    jitter_max_minutes: int = 0,
) -> SequenceAction | None:
    active = _active_rows(lead_rows)
    if not active:
        return None
    lead_id, sequence_id, version = sequence_key(active[0][1])
    steps = _step_map(active)
    if not steps:
        return None

    sent_by_step: dict[int, tuple[int, dict[str, str]]] = {}
    for step, variants in steps.items():
        sent = _sent_variant(variants)
        if sent:
            sent_by_step[step] = sent

    next_step = None
    for step in sorted(steps):
        if step not in sent_by_step:
            next_step = step
            break
    if next_step is None:
        return None
    if next_step > 1 and next_step - 1 not in sent_by_step:
        return None

    chosen = _choose_variant(steps[next_step], lead_id, sequence_id, version, next_step)
    if chosen is None:
        return None
    row_number, row = chosen

    if next_step == 1:
        scheduled = parse_dt(row.get("scheduled_at", ""))
        due_at = scheduled or now
    else:
        previous = sent_by_step[next_step - 1][1]
        previous_sent = parse_dt(previous.get("sent_at", ""))
        if not previous_sent:
            return None
        wait_minutes = _int(row.get("wait_minutes", ""), 0)
        due_at = previous_sent + timedelta(minutes=wait_minutes)
        due_at += timedelta(minutes=_jitter_minutes(lead_id, sequence_id, next_step, jitter_max_minutes))
    if due_at > now:
        return None

    references: list[str] = []
    previous_subject = ""
    for step in sorted(sent_by_step):
        if step >= next_step:
            continue
        sent_row = sent_by_step[step][1]
        message_id = str(sent_row.get("message_id", "")).strip()
        if message_id:
            references.append(message_id)
        if str(sent_row.get("subject", "")).strip():
            previous_subject = str(sent_row.get("subject", "")).strip()
    effective_subject = str(row.get("subject", "")).strip() or previous_subject
    previous_message_id = references[-1] if references else ""
    return SequenceAction(
        row_number=row_number,
        row=row,
        step_number=next_step,
        variant_id=str(row.get("variant_id", "A") or "A").strip().upper(),
        sequence_id=sequence_id,
        sequence_version=version,
        due_at=due_at,
        previous_message_id=previous_message_id,
        references=tuple(references),
        effective_subject=effective_subject,
        is_final_step=next_step == max(steps),
    )


def deterministic_sequence_message_id(
    lead_id: str,
    sequence_id: str,
    version: str,
    step: int,
    variant_id: str,
    sender_email: str,
) -> str:
    domain = domain_of(sender_email) or "localhost"
    digest = sha256(
        f"{lead_id}|{sequence_id}|{version}|{step}|{variant_id}".encode("utf-8")
    ).hexdigest()[:32]
    return f"<{digest}.s{step}{variant_id.lower()}@{domain}>"


def build_sequence_message(
    queue_row: dict[str, str],
    action: SequenceAction,
    mailbox: MailboxConfig,
) -> EmailMessage:
    body = str(action.row.get("body", "")).strip()
    if not action.effective_subject or not body:
        raise ValueError("subject/body missing for requested sequence step")
    msg = EmailMessage()
    msg["From"] = (
        f"{mailbox.sender_name} <{mailbox.sender_email}>"
        if mailbox.sender_name
        else mailbox.sender_email
    )
    msg["To"] = queue_row["email"]
    msg["Subject"] = action.effective_subject
    msg["Date"] = format_datetime(utcnow())
    msg["Message-ID"] = deterministic_sequence_message_id(
        queue_row["lead_id"],
        action.sequence_id,
        action.sequence_version,
        action.step_number,
        action.variant_id,
        mailbox.sender_email,
    )
    if action.previous_message_id:
        msg["In-Reply-To"] = action.previous_message_id
    if action.references:
        msg["References"] = " ".join(action.references[-20:])
    msg.set_content(body)
    return msg


def next_due_after_send(
    lead_rows: list[tuple[int, dict[str, str]]],
    *,
    sent_step: int,
    sent_at: datetime,
    jitter_max_minutes: int = 0,
) -> datetime | None:
    steps = _step_map(lead_rows)
    next_step = sent_step + 1
    if next_step not in steps:
        return None
    lead_id, sequence_id, _ = sequence_key(steps[next_step][0][1])
    variants = steps[next_step]
    wait = _int(variants[0][1].get("wait_minutes", ""), 0)
    return sent_at + timedelta(minutes=wait + _jitter_minutes(lead_id, sequence_id, next_step, jitter_max_minutes))
