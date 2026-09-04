from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from outreach_campaign_runtime import transport_events
from outreach_replyhub import REPLY_SHEET
from outreach_sender import (
    QUEUE_SHEET,
    SUPPRESSION_SHEET,
    build_sheets_service,
    get_values,
    iso,
    parse_dt,
    rows_from_values,
)
from outreach_sequences import SEQUENCE_SHEET

VARIANT_ANALYTICS_SHEET = "VariantAnalytics"
VARIANT_ANALYTICS_HEADERS = [
    "generated_at",
    "sequence_id",
    "sequence_version",
    "step_number",
    "variant_id",
    "sends",
    "replies_attributed",
    "bounces_attributed",
    "opt_outs_attributed",
    "reply_rate",
    "bounce_rate",
    "opt_out_rate",
    "recommendation",
    "note",
]
MAILBOX_HEALTH_SHEET = "MailboxHealth"
MAILBOX_HEALTH_HEADERS = [
    "generated_at",
    "mailbox_id",
    "sender_email",
    "sends_30d",
    "replies_30d",
    "bounces_30d",
    "opt_outs_30d",
    "reply_rate",
    "bounce_rate",
    "opt_out_rate",
    "state",
    "note",
]


def _pct(numerator: int, denominator: int) -> float:
    return 0.0 if denominator <= 0 else round(100.0 * numerator / denominator, 2)


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    value = int(raw)
    return max(minimum, min(value, maximum))


def _float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    value = float(raw)
    return max(minimum, min(value, maximum))


def _selected_sent_sequence_rows(
    rows: Iterable[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if str(row.get("status", "")).strip().lower() != "sent":
            continue
        if not parse_dt(row.get("sent_at", "")):
            continue
        lead_id = str(row.get("lead_id", "")).strip()
        if lead_id:
            result[lead_id].append(row)
    for lead_rows in result.values():
        lead_rows.sort(key=lambda row: parse_dt(row.get("sent_at", "")) or datetime.min.replace(tzinfo=timezone.utc))
    return result


def _latest_touch_before(
    rows: list[dict[str, str]], event_at: datetime | None
) -> dict[str, str] | None:
    if event_at is None:
        return None
    eligible = [
        row
        for row in rows
        if (sent := parse_dt(row.get("sent_at", ""))) and sent <= event_at
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda row: parse_dt(row.get("sent_at", "")) or event_at)


def build_variant_rows(
    queue_rows: Iterable[dict[str, str]],
    sequence_rows: Iterable[dict[str, str]],
    *,
    generated_at: datetime,
    min_samples: int = 20,
) -> list[dict[str, str]]:
    queue_by_lead = {
        str(row.get("lead_id", "")).strip(): row
        for row in queue_rows
        if str(row.get("lead_id", "")).strip()
    }
    sent_by_lead = _selected_sent_sequence_rows(sequence_rows)
    metrics: dict[tuple[str, str, int, str], dict[str, int]] = defaultdict(
        lambda: {"sends": 0, "replies": 0, "bounces": 0, "opt_outs": 0}
    )

    for lead_id, rows in sent_by_lead.items():
        for row in rows:
            key = (
                str(row.get("sequence_id", "")).strip() or "sequence",
                str(row.get("sequence_version", "1")).strip() or "1",
                int(str(row.get("step_number", "1") or "1")),
                str(row.get("variant_id", "A")).strip().upper() or "A",
            )
            metrics[key]["sends"] += 1

        queue = queue_by_lead.get(lead_id, {})
        status = str(queue.get("status", "")).strip().lower()
        event_at = parse_dt(queue.get("reply_at", ""))
        if status == "bounced":
            event_at = parse_dt(queue.get("bounce_at", ""))
        touch = _latest_touch_before(rows, event_at)
        if touch is None:
            continue
        key = (
            str(touch.get("sequence_id", "")).strip() or "sequence",
            str(touch.get("sequence_version", "1")).strip() or "1",
            int(str(touch.get("step_number", "1") or "1")),
            str(touch.get("variant_id", "A")).strip().upper() or "A",
        )
        if status == "replied":
            metrics[key]["replies"] += 1
        elif status == "bounced":
            metrics[key]["bounces"] += 1
        elif status == "opted_out":
            metrics[key]["opt_outs"] += 1

    grouped_rates: dict[tuple[str, str, int], list[tuple[tuple[str, str, int, str], float, int]]] = defaultdict(list)
    for key, values in metrics.items():
        rate = _pct(values["replies"], values["sends"])
        grouped_rates[key[:3]].append((key, rate, values["sends"]))

    output: list[dict[str, str]] = []
    for key in sorted(metrics):
        values = metrics[key]
        sequence_id, version, step, variant = key
        reply_rate = _pct(values["replies"], values["sends"])
        peers = [item for item in grouped_rates[key[:3]] if item[2] >= min_samples]
        if values["sends"] < min_samples:
            recommendation = "insufficient_data"
            note = f"need at least {min_samples} sends before comparing variants"
        elif len(peers) < 2:
            recommendation = "no_comparison"
            note = "not enough sampled peer variants"
        else:
            best_rate = max(item[1] for item in peers)
            if reply_rate == best_rate:
                recommendation = "leader"
                note = "highest observed reply rate in this step"
            elif best_rate - reply_rate >= 5.0 and reply_rate <= best_rate / 2:
                recommendation = "review"
                note = "materially below the observed step leader; owner review recommended"
            else:
                recommendation = "keep"
                note = "no strong reply-rate signal to pause this approved variant"
        output.append(
            {
                "generated_at": iso(generated_at),
                "sequence_id": sequence_id,
                "sequence_version": version,
                "step_number": str(step),
                "variant_id": variant,
                "sends": str(values["sends"]),
                "replies_attributed": str(values["replies"]),
                "bounces_attributed": str(values["bounces"]),
                "opt_outs_attributed": str(values["opt_outs"]),
                "reply_rate": str(reply_rate),
                "bounce_rate": str(_pct(values["bounces"], values["sends"])),
                "opt_out_rate": str(_pct(values["opt_outs"], values["sends"])),
                "recommendation": recommendation,
                "note": note,
            }
        )
    return output


def build_mailbox_health_rows(
    queue_rows: Iterable[dict[str, str]],
    sequence_rows: Iterable[dict[str, str]],
    *,
    generated_at: datetime,
    timezone_name: str,
    bounce_alert_rate: float = 5.0,
) -> list[dict[str, str]]:
    queue_rows = list(queue_rows)
    sequence_rows = list(sequence_rows)
    cutoff = generated_at - timedelta(days=30)
    events = [event for event in transport_events(queue_rows, sequence_rows) if event[0] >= cutoff]
    sends: dict[str, int] = defaultdict(int)
    sender_emails: dict[str, str] = {}
    for _, mailbox_id, lead_id, _ in events:
        sends[mailbox_id] += 1
        queue = next((row for row in queue_rows if str(row.get("lead_id", "")).strip() == lead_id), None)
        if queue and queue.get("sender_email"):
            sender_emails[mailbox_id] = str(queue.get("sender_email", ""))

    outcomes: dict[str, dict[str, int]] = defaultdict(lambda: {"replies": 0, "bounces": 0, "opt_outs": 0})
    for row in queue_rows:
        mailbox_id = str(row.get("sender_mailbox_id", "")).strip()
        if not mailbox_id:
            continue
        sender_emails.setdefault(mailbox_id, str(row.get("sender_email", "")))
        status = str(row.get("status", "")).strip().lower()
        event_at = parse_dt(row.get("bounce_at", "")) if status == "bounced" else parse_dt(row.get("reply_at", ""))
        if not event_at or event_at < cutoff:
            continue
        if status == "replied":
            outcomes[mailbox_id]["replies"] += 1
        elif status == "bounced":
            outcomes[mailbox_id]["bounces"] += 1
        elif status == "opted_out":
            outcomes[mailbox_id]["opt_outs"] += 1

    output: list[dict[str, str]] = []
    mailbox_ids = sorted(set(sends) | set(outcomes) | set(sender_emails))
    for mailbox_id in mailbox_ids:
        sent = sends.get(mailbox_id, 0)
        values = outcomes[mailbox_id]
        bounce_rate = _pct(values["bounces"], sent)
        if sent < 20:
            state = "insufficient_data"
            note = "transport metrics only; not a warmup or inbox-placement score"
        elif bounce_rate >= bounce_alert_rate:
            state = "review_bounces"
            note = f"30-day bounce rate reached configured alert threshold {bounce_alert_rate}%"
        else:
            state = "observed"
            note = "transport metrics only; not a warmup or inbox-placement score"
        output.append(
            {
                "generated_at": iso(generated_at),
                "mailbox_id": mailbox_id,
                "sender_email": sender_emails.get(mailbox_id, ""),
                "sends_30d": str(sent),
                "replies_30d": str(values["replies"]),
                "bounces_30d": str(values["bounces"]),
                "opt_outs_30d": str(values["opt_outs"]),
                "reply_rate": str(_pct(values["replies"], sent)),
                "bounce_rate": str(bounce_rate),
                "opt_out_rate": str(_pct(values["opt_outs"], sent)),
                "state": state,
                "note": note,
            }
        )
    return output


def replace_sheet_rows(service, spreadsheet_id: str, sheet_name: str, headers: list[str], rows: list[dict[str, str]]) -> None:
    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'!A:AZ",
        body={},
    ).execute()
    values = [headers] + [[row.get(header, "") for header in headers] for row in rows]
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def render_summary(
    queue_rows: list[dict[str, str]],
    sequence_rows: list[dict[str, str]],
    reply_rows: list[dict[str, str]],
    variant_rows: list[dict[str, str]],
    health_rows: list[dict[str, str]],
    suppression_count: int,
) -> str:
    events = transport_events(queue_rows, sequence_rows)
    total_sends = len(events)
    step1 = sum(1 for _, _, _, stage in events if stage == 1)
    followups = total_sends - step1
    replies = sum(1 for row in queue_rows if str(row.get("status", "")).strip().lower() == "replied")
    bounces = sum(1 for row in queue_rows if str(row.get("status", "")).strip().lower() == "bounced")
    optouts = sum(1 for row in queue_rows if str(row.get("status", "")).strip().lower() == "opted_out")
    new_replies = sum(1 for row in reply_rows if str(row.get("triage_status", "")).strip().lower() == "new")
    review_variants = sum(1 for row in variant_rows if row.get("recommendation") == "review")
    health_alerts = sum(1 for row in health_rows if row.get("state") == "review_bounces")
    lines = [
        "## Controlled outreach analytics v2",
        "",
        f"- SMTP-accepted messages: **{total_sends}** (step 1: **{step1}**, follow-ups: **{followups}**)",
        f"- replies: **{replies}** ({_pct(replies, step1)}% of sequences started)",
        f"- bounces: **{bounces}** ({_pct(bounces, step1)}% of sequences started)",
        f"- opt-outs: **{optouts}** ({_pct(optouts, step1)}% of sequences started)",
        f"- ReplyInbox items awaiting triage: **{new_replies}**",
        f"- variant rows recommended for owner review: **{review_variants}**",
        f"- mailbox transport alerts: **{health_alerts}**",
        f"- suppression rows: **{suppression_count}**",
        "",
        "> SMTP acceptance and local transport metrics are not proof of inbox placement, sender reputation, or warmup health.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    spreadsheet_id = os.environ["OUTREACH_SPREADSHEET_ID"]
    timezone_name = os.getenv("OUTREACH_TIMEZONE", "Europe/Amsterdam").strip() or "Europe/Amsterdam"
    min_samples = _int_env("OUTREACH_VARIANT_MIN_SAMPLES", 20, 5, 10000)
    bounce_alert_rate = _float_env("OUTREACH_MAILBOX_BOUNCE_ALERT_RATE", 5.0, 0.1, 100.0)
    generated_at = datetime.now(timezone.utc)

    service = build_sheets_service()
    _, queue_rows = rows_from_values(get_values(service, spreadsheet_id, QUEUE_SHEET))
    _, sequence_rows = rows_from_values(get_values(service, spreadsheet_id, SEQUENCE_SHEET))
    _, reply_rows = rows_from_values(get_values(service, spreadsheet_id, REPLY_SHEET))
    _, suppression_rows = rows_from_values(get_values(service, spreadsheet_id, SUPPRESSION_SHEET))

    variant_rows = build_variant_rows(
        queue_rows,
        sequence_rows,
        generated_at=generated_at,
        min_samples=min_samples,
    )
    health_rows = build_mailbox_health_rows(
        queue_rows,
        sequence_rows,
        generated_at=generated_at,
        timezone_name=timezone_name,
        bounce_alert_rate=bounce_alert_rate,
    )
    replace_sheet_rows(
        service,
        spreadsheet_id,
        VARIANT_ANALYTICS_SHEET,
        VARIANT_ANALYTICS_HEADERS,
        variant_rows,
    )
    replace_sheet_rows(
        service,
        spreadsheet_id,
        MAILBOX_HEALTH_SHEET,
        MAILBOX_HEALTH_HEADERS,
        health_rows,
    )
    report = render_summary(
        queue_rows,
        sequence_rows,
        reply_rows,
        variant_rows,
        health_rows,
        len(suppression_rows),
    )
    print(report)
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
