from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from zoneinfo import ZoneInfo

from outreach_mailboxes import (
    MailboxConfig,
    choose_initial_mailbox,
    enabled_mailboxes,
    load_mailboxes_from_env,
    mailbox_is_available,
    mailbox_map,
)
from outreach_replyhub import REPLY_HEADERS, REPLY_SHEET, sync_replyhub
from outreach_sender import (
    LOG_HEADERS,
    LOG_SHEET,
    QUEUE_HEADERS,
    QUEUE_SHEET,
    SUPPRESSION_HEADERS,
    SUPPRESSION_SHEET,
    Settings,
    append_row,
    build_message,
    build_sheets_service,
    ensure_expected_headers,
    get_values,
    iso,
    log_event,
    next_action as legacy_next_action,
    normalize_address,
    parse_dt,
    rows_from_values,
    smtp_send,
    suppression_match,
    suppression_sets,
    update_row,
    utcnow,
    validate_row as legacy_validate_row,
    verification_is_fresh,
    within_send_window,
    resolve_followup_mailbox,
)
from outreach_sequences import (
    SEQUENCE_HEADERS,
    SEQUENCE_SHEET,
    SequenceAction,
    build_sequence_message,
    group_sequence_rows,
    next_due_after_send,
    next_sequence_action,
    validate_sequence_rows,
)

STOP_STATUSES = {
    "replied",
    "bounced",
    "opted_out",
    "blocked",
    "manual_review",
    "error",
    "sending",
    "sequence_complete",
}


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class Candidate:
    queue_index: int
    queue_row: dict[str, str]
    kind: str
    stage: int
    sequence_action: SequenceAction | None = None

    @property
    def is_initial(self) -> bool:
        return self.stage == 1


def _sequence_sent_rows(
    sequence_rows: Iterable[dict[str, str]],
) -> Iterable[dict[str, str]]:
    for row in sequence_rows:
        if str(row.get("status", "")).strip().lower() != "sent":
            continue
        if not parse_dt(row.get("sent_at", "")):
            continue
        yield row


def _sequence_leads(sequence_rows: Iterable[dict[str, str]]) -> set[str]:
    return {
        str(row.get("lead_id", "")).strip()
        for row in sequence_rows
        if str(row.get("lead_id", "")).strip()
    }


def transport_events(
    queue_rows: Iterable[dict[str, str]],
    sequence_rows: Iterable[dict[str, str]],
) -> list[tuple[datetime, str, str, int]]:
    sequence_rows = list(sequence_rows)
    sequenced = _sequence_leads(sequence_rows)
    events: list[tuple[datetime, str, str, int]] = []
    for row in _sequence_sent_rows(sequence_rows):
        dt = parse_dt(row.get("sent_at", ""))
        if not dt:
            continue
        events.append(
            (
                dt,
                str(row.get("sender_mailbox_id", "")).strip() or "unassigned",
                str(row.get("lead_id", "")).strip(),
                int(str(row.get("step_number", "1") or "1")),
            )
        )
    for row in queue_rows:
        lead_id = str(row.get("lead_id", "")).strip()
        if lead_id in sequenced:
            continue
        mailbox_id = str(row.get("sender_mailbox_id", "")).strip() or "unassigned"
        initial = parse_dt(row.get("sent_at", ""))
        if initial:
            events.append((initial, mailbox_id, lead_id, 1))
        follow = parse_dt(row.get("followup_sent_at", ""))
        if follow:
            events.append((follow, mailbox_id, lead_id, 2))
    return events


def count_events_today(
    events: Iterable[tuple[datetime, str, str, int]],
    now: datetime,
    timezone_name: str,
) -> int:
    tz = ZoneInfo(timezone_name)
    today = now.astimezone(tz).date()
    return sum(1 for dt, _, _, _ in events if dt.astimezone(tz).date() == today)


def count_initials_today(
    events: Iterable[tuple[datetime, str, str, int]],
    now: datetime,
    timezone_name: str,
) -> int:
    tz = ZoneInfo(timezone_name)
    today = now.astimezone(tz).date()
    return sum(
        1
        for dt, _, _, stage in events
        if stage == 1 and dt.astimezone(tz).date() == today
    )


def mailbox_event_state(
    events: Iterable[tuple[datetime, str, str, int]],
    now: datetime,
    timezone_name: str,
) -> tuple[dict[str, int], dict[str, datetime]]:
    tz = ZoneInfo(timezone_name)
    today = now.astimezone(tz).date()
    counts: dict[str, int] = {}
    last_sent: dict[str, datetime] = {}
    for dt, mailbox_id, _, _ in events:
        if dt.astimezone(tz).date() == today:
            counts[mailbox_id] = counts.get(mailbox_id, 0) + 1
        previous = last_sent.get(mailbox_id)
        if previous is None or dt > previous:
            last_sent[mailbox_id] = dt
    return counts, last_sent


def _common_errors(row: dict[str, str]) -> list[str]:
    errors: list[str] = []
    if not str(row.get("lead_id", "")).strip():
        errors.append("missing lead_id")
    if "@" not in normalize_address(row.get("email", "")):
        errors.append("invalid email syntax")
    if str(row.get("compliance_status", "")).strip().lower() != "approved":
        errors.append("compliance_status is not approved")
    if str(row.get("opt_out_mode", "")).strip().lower() != "reply_optout":
        errors.append(
            "direct SMTP route requires reply_optout; provider_required needs a provider with the required unsubscribe mechanism"
        )
    return errors


def build_candidates(
    queue_rows: list[dict[str, str]],
    sequence_grouped: dict[str, list[tuple[int, dict[str, str]]]],
    *,
    now: datetime,
    jitter_max_minutes: int,
) -> list[Candidate]:
    result: list[Candidate] = []
    for idx, row in enumerate(queue_rows):
        if str(row.get("status", "")).strip().lower() in STOP_STATUSES:
            continue
        lead_id = str(row.get("lead_id", "")).strip()
        lead_sequence = sequence_grouped.get(lead_id, [])
        if lead_sequence:
            action = next_sequence_action(
                lead_sequence,
                now=now,
                jitter_max_minutes=jitter_max_minutes,
            )
            if action:
                result.append(
                    Candidate(
                        queue_index=idx,
                        queue_row=row,
                        kind="sequence",
                        stage=action.step_number,
                        sequence_action=action,
                    )
                )
            continue
        legacy = legacy_next_action(row, now)
        if legacy:
            result.append(
                Candidate(
                    queue_index=idx,
                    queue_row=row,
                    kind="legacy",
                    stage=1 if legacy == "initial" else 2,
                )
            )
    return result


def _candidate_sort_key(candidate: Candidate, prioritize_new: bool) -> tuple[int, int, str]:
    initial_rank = 0 if prioritize_new else 1
    follow_rank = 1 if prioritize_new else 0
    rank = initial_rank if candidate.is_initial else follow_rank
    return (rank, candidate.stage, str(candidate.queue_row.get("lead_id", "")))


def _update_sequence_row(
    service,
    settings: Settings,
    sequence_headers: list[str],
    row_number: int,
    row: dict[str, str],
) -> None:
    update_row(
        service,
        settings.spreadsheet_id,
        SEQUENCE_SHEET,
        row_number,
        sequence_headers,
        row,
    )


def _select_mailbox(
    candidate: Candidate,
    *,
    active_mailboxes: list[MailboxConfig],
    configured_mailboxes: dict[str, MailboxConfig],
    mailbox_counts: dict[str, int],
    mailbox_last_sent: dict[str, datetime],
    now: datetime,
) -> tuple[MailboxConfig | None, str]:
    if candidate.is_initial:
        mailbox = choose_initial_mailbox(
            active_mailboxes,
            sent_today=mailbox_counts,
            last_sent_at=mailbox_last_sent,
            now=now,
            lead_id=str(candidate.queue_row.get("lead_id", "")),
        )
        return mailbox, "" if mailbox else "no sending mailbox currently has available capacity"
    mailbox, reason = resolve_followup_mailbox(
        candidate.queue_row,
        configured=configured_mailboxes,
        enabled=active_mailboxes,
    )
    if mailbox is None:
        return None, reason
    if not mailbox_is_available(
        mailbox,
        sent_today=mailbox_counts.get(mailbox.mailbox_id, 0),
        last_sent_at=mailbox_last_sent.get(mailbox.mailbox_id),
        now=now,
    ):
        return None, f"assigned mailbox {mailbox.mailbox_id} is waiting for capacity/pacing"
    return mailbox, ""


def _validate_candidate(candidate: Candidate) -> list[str]:
    if candidate.kind == "legacy":
        return legacy_validate_row(
            candidate.queue_row,
            "initial" if candidate.stage == 1 else "followup",
        )
    errors = _common_errors(candidate.queue_row)
    assert candidate.sequence_action is not None
    if not str(candidate.sequence_action.row.get("body", "")).strip():
        errors.append("sequence body missing")
    if not candidate.sequence_action.effective_subject:
        errors.append("sequence subject missing")
    if str(candidate.sequence_action.row.get("status", "approved")).strip().lower() != "approved":
        errors.append("sequence variant is not approved")
    return errors


def _send_sequence_candidate(
    service,
    settings: Settings,
    queue_headers: list[str],
    sequence_headers: list[str],
    sequence_grouped: dict[str, list[tuple[int, dict[str, str]]]],
    candidate: Candidate,
    mailbox: MailboxConfig,
    jitter_max_minutes: int,
) -> tuple[datetime, str]:
    assert candidate.sequence_action is not None
    action = candidate.sequence_action
    queue_row = candidate.queue_row
    sequence_row = action.row
    queue_row.update(
        status="sending",
        stage=str(action.step_number),
        last_error="",
        sender_mailbox_id=mailbox.mailbox_id,
        sender_email=mailbox.sender_email,
    )
    sequence_row.update(
        selected="true",
        scheduled_at=sequence_row.get("scheduled_at", "") or iso(action.due_at),
        last_error="",
        sender_mailbox_id=mailbox.mailbox_id,
        sender_email=mailbox.sender_email,
    )
    update_row(
        service,
        settings.spreadsheet_id,
        QUEUE_SHEET,
        candidate.queue_index + 2,
        queue_headers,
        queue_row,
    )
    _update_sequence_row(
        service,
        settings,
        sequence_headers,
        action.row_number,
        sequence_row,
    )

    msg = build_sequence_message(queue_row, action, mailbox)
    smtp_send(msg, mailbox)
    sent_at = utcnow()
    message_id = str(msg["Message-ID"])
    sequence_row.update(
        status="sent",
        sent_at=iso(sent_at),
        message_id=message_id,
        last_error="",
    )
    _update_sequence_row(
        service,
        settings,
        sequence_headers,
        action.row_number,
        sequence_row,
    )

    lead_id = str(queue_row.get("lead_id", ""))
    lead_rows = sequence_grouped.get(lead_id, [])
    next_due = next_due_after_send(
        lead_rows,
        sent_step=action.step_number,
        sent_at=sent_at,
        jitter_max_minutes=jitter_max_minutes,
    )
    if action.step_number == 1:
        queue_row.update(sent_at=iso(sent_at), message_id=message_id)
    elif action.step_number == 2:
        queue_row.update(followup_sent_at=iso(sent_at), followup_message_id=message_id)
    queue_row.update(
        status="sequence_complete" if action.is_final_step else "sent",
        next_send_at="" if next_due is None else iso(next_due),
        last_error="",
    )
    update_row(
        service,
        settings.spreadsheet_id,
        QUEUE_SHEET,
        candidate.queue_index + 2,
        queue_headers,
        queue_row,
    )
    log_event(
        service,
        settings,
        queue_row,
        "sequence_step_sent",
        message_id=message_id,
        detail=(
            f"sequence={action.sequence_id} version={action.sequence_version} "
            f"step={action.step_number} variant={action.variant_id}"
        ),
        mailbox=mailbox,
    )
    return sent_at, message_id


def _send_legacy_candidate(
    service,
    settings: Settings,
    queue_headers: list[str],
    candidate: Candidate,
    mailbox: MailboxConfig,
) -> tuple[datetime, str]:
    row = candidate.queue_row
    row.update(
        status="sending",
        stage=str(candidate.stage),
        last_error="",
        sender_mailbox_id=mailbox.mailbox_id,
        sender_email=mailbox.sender_email,
    )
    update_row(
        service,
        settings.spreadsheet_id,
        QUEUE_SHEET,
        candidate.queue_index + 2,
        queue_headers,
        row,
    )
    msg = build_message(row, mailbox, candidate.stage)
    smtp_send(msg, mailbox)
    sent_at = utcnow()
    message_id = str(msg["Message-ID"])
    if candidate.stage == 1:
        row.update(status="sent", sent_at=iso(sent_at), message_id=message_id)
        if row.get("followup_body", "").strip():
            delay_days = int(row.get("followup_delay_days", "3") or "3")
            from datetime import timedelta

            row["next_send_at"] = iso(sent_at + timedelta(days=max(1, delay_days)))
    else:
        row.update(
            status="followup_sent",
            followup_sent_at=iso(sent_at),
            followup_message_id=message_id,
            next_send_at="",
        )
    update_row(
        service,
        settings.spreadsheet_id,
        QUEUE_SHEET,
        candidate.queue_index + 2,
        queue_headers,
        row,
    )
    log_event(service, settings, row, row["status"], message_id=message_id, mailbox=mailbox)
    return sent_at, message_id


def process() -> int:
    settings = Settings.from_env()
    max_new_leads = _int_env("OUTREACH_MAX_NEW_LEADS_PER_DAY", 100, 1, 100)
    prioritize_new = _bool_env("OUTREACH_PRIORITIZE_NEW_LEADS", False)
    jitter_max = _int_env("OUTREACH_RANDOM_JITTER_MINUTES", 0, 0, 120)

    mailboxes = load_mailboxes_from_env(
        mode=settings.mode,
        default_daily_limit=settings.daily_send_limit,
    )
    active_mailboxes = enabled_mailboxes(mailboxes)
    configured_mailboxes = mailbox_map(mailboxes)

    service = build_sheets_service()
    queue_headers, queue_rows = rows_from_values(
        get_values(service, settings.spreadsheet_id, QUEUE_SHEET)
    )
    suppression_headers, suppression_rows = rows_from_values(
        get_values(service, settings.spreadsheet_id, SUPPRESSION_SHEET)
    )
    log_headers, _ = rows_from_values(get_values(service, settings.spreadsheet_id, LOG_SHEET))
    sequence_headers, sequence_rows = rows_from_values(
        get_values(service, settings.spreadsheet_id, SEQUENCE_SHEET)
    )
    reply_headers, reply_rows = rows_from_values(
        get_values(service, settings.spreadsheet_id, REPLY_SHEET)
    )
    ensure_expected_headers(queue_headers, QUEUE_HEADERS, QUEUE_SHEET)
    ensure_expected_headers(suppression_headers, SUPPRESSION_HEADERS, SUPPRESSION_SHEET)
    ensure_expected_headers(log_headers, LOG_HEADERS, LOG_SHEET)
    ensure_expected_headers(sequence_headers, SEQUENCE_HEADERS, SEQUENCE_SHEET)
    ensure_expected_headers(reply_headers, REPLY_HEADERS, REPLY_SHEET)

    sequence_errors = validate_sequence_rows(sequence_rows)
    if sequence_errors:
        raise RuntimeError("sequence contract failed: " + "; ".join(sequence_errors[:20]))

    if settings.mode == "live":
        synced = sync_replyhub(
            service,
            settings,
            queue_headers,
            queue_rows,
            reply_rows,
            active_mailboxes,
        )
        if synced:
            queue_headers, queue_rows = rows_from_values(
                get_values(service, settings.spreadsheet_id, QUEUE_SHEET)
            )
            _, suppression_rows = rows_from_values(
                get_values(service, settings.spreadsheet_id, SUPPRESSION_SHEET)
            )
            _, reply_rows = rows_from_values(
                get_values(service, settings.spreadsheet_id, REPLY_SHEET)
            )

    suppressed_emails, suppressed_domains = suppression_sets(suppression_rows)
    now = utcnow()
    sequence_grouped = group_sequence_rows(sequence_rows)
    events = transport_events(queue_rows, sequence_rows)
    send_count = count_events_today(events, now, settings.timezone_name)
    initials_today = count_initials_today(events, now, settings.timezone_name)
    mailbox_counts, mailbox_last_sent = mailbox_event_state(
        events,
        now,
        settings.timezone_name,
    )
    sends_this_run = 0

    if settings.mode == "live" and not within_send_window(
        now,
        settings.timezone_name,
        settings.send_window_start,
        settings.send_window_end,
    ):
        print("Outside configured send window; reply sync completed, no outbound mail sent.")
        return 0

    candidates = build_candidates(
        queue_rows,
        sequence_grouped,
        now=now,
        jitter_max_minutes=jitter_max,
    )
    candidates.sort(key=lambda item: _candidate_sort_key(item, prioritize_new))

    for candidate in candidates:
        row = candidate.queue_row
        errors = _validate_candidate(candidate)
        if suppression_match(row.get("email", ""), suppressed_emails, suppressed_domains):
            errors.append("recipient is suppressed")
        if errors:
            if settings.mode == "validate":
                print(f"{row.get('lead_id', candidate.queue_index + 2)}: {'; '.join(errors)}")
            else:
                row.update(status="blocked", last_error="; ".join(errors)[:500])
                update_row(
                    service,
                    settings.spreadsheet_id,
                    QUEUE_SHEET,
                    candidate.queue_index + 2,
                    queue_headers,
                    row,
                )
                log_event(service, settings, row, "blocked", detail=row["last_error"])
            continue

        if candidate.is_initial and not verification_is_fresh(
            row,
            now,
            settings.verification_max_age_days,
        ):
            if settings.mode == "validate":
                print(f"{row.get('lead_id')}: verification required")
            else:
                row.update(
                    status="verification_pending",
                    last_error="fresh verifier readback required",
                )
                update_row(
                    service,
                    settings.spreadsheet_id,
                    QUEUE_SHEET,
                    candidate.queue_index + 2,
                    queue_headers,
                    row,
                )
                log_event(
                    service,
                    settings,
                    row,
                    "verification_pending",
                    detail=row["last_error"],
                )
            continue

        if settings.mode != "live":
            continue
        if send_count >= settings.daily_send_limit or sends_this_run >= settings.max_sends_per_run:
            break
        if candidate.is_initial and initials_today >= max_new_leads:
            continue

        mailbox, reason = _select_mailbox(
            candidate,
            active_mailboxes=active_mailboxes,
            configured_mailboxes=configured_mailboxes,
            mailbox_counts=mailbox_counts,
            mailbox_last_sent=mailbox_last_sent,
            now=utcnow(),
        )
        if mailbox is None:
            if not candidate.is_initial and row.get("last_error", "") != reason:
                row["last_error"] = reason[:500]
                update_row(
                    service,
                    settings.spreadsheet_id,
                    QUEUE_SHEET,
                    candidate.queue_index + 2,
                    queue_headers,
                    row,
                )
                log_event(service, settings, row, "followup_deferred", detail=reason)
            continue

        try:
            if candidate.kind == "sequence":
                sent_at, _ = _send_sequence_candidate(
                    service,
                    settings,
                    queue_headers,
                    sequence_headers,
                    sequence_grouped,
                    candidate,
                    mailbox,
                    jitter_max,
                )
            else:
                sent_at, _ = _send_legacy_candidate(
                    service,
                    settings,
                    queue_headers,
                    candidate,
                    mailbox,
                )
            send_count += 1
            sends_this_run += 1
            if candidate.is_initial:
                initials_today += 1
            mailbox_counts[mailbox.mailbox_id] = mailbox_counts.get(mailbox.mailbox_id, 0) + 1
            mailbox_last_sent[mailbox.mailbox_id] = sent_at
        except Exception as exc:
            row.update(status="error", last_error=f"{type(exc).__name__}: {exc}"[:500])
            update_row(
                service,
                settings.spreadsheet_id,
                QUEUE_SHEET,
                candidate.queue_index + 2,
                queue_headers,
                row,
            )
            if candidate.sequence_action is not None:
                sequence_row = candidate.sequence_action.row
                sequence_row.update(status="error", last_error=row["last_error"])
                _update_sequence_row(
                    service,
                    settings,
                    sequence_headers,
                    candidate.sequence_action.row_number,
                    sequence_row,
                )
            log_event(
                service,
                settings,
                row,
                "send_error",
                detail=row["last_error"],
                mailbox=mailbox,
            )

    mailbox_summary = ",".join(
        f"{mailbox.mailbox_id}:{mailbox_counts.get(mailbox.mailbox_id, 0)}/{mailbox.daily_limit}"
        for mailbox in active_mailboxes
    )
    print(
        f"mode={settings.mode} rows={len(queue_rows)} candidates={len(candidates)} "
        f"sends_this_run={sends_this_run} sends_today={send_count} "
        f"initials_today={initials_today}/{max_new_leads} mailboxes={mailbox_summary}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(process())
