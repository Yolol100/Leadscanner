from __future__ import annotations

import re

from outreach_sender import (
    QUEUE_HEADERS,
    QUEUE_SHEET,
    Settings,
    build_sheets_service,
    ensure_expected_headers,
    get_values,
    rows_from_values,
)
from outreach_sequences import SEQUENCE_HEADERS, SEQUENCE_SHEET, enabled as sequence_enabled

CTA_A = "Zal ik nog één concreet idee sturen?"
CTA_B = "Mag ik nog één concreet idee sturen?"
OPT_OUT = 'Geen interesse? Een kort "nee" is genoeg.'
CASES_URL = "https://andrewbaeten.nl/category/cases"
SIGNATURE = "Met vriendelijke groet,\nAndrew Baeten"
CANONICAL_FOLLOWUP_RE = re.compile(
    r'^Beste .+,\n\n'
    r'Ik kom hier nog één keer op terug\. Als het nuttig is, stuur ik het concrete idee voor .+ graag door\.\n\n'
    r'Geen interesse\? Een kort "nee" is genoeg\.\n\n'
    r'Met vriendelijke groet,\nAndrew Baeten$'
)
BANNED_PATTERNS = (
    re.compile(r"(?i)\b(?:plan|boek|reserveer)\b.{0,60}\b(?:call|meeting|gesprek|afspraak|agenda|minuten)\b"),
    re.compile(r"(?i)\b(?:gegarandeerd|garandeert|garantie op|levert direct meer|levert meer aanvragen|meer omzet gegarandeerd)\b"),
    re.compile(r"(?i)\b(?:alleen vandaag|laatste kans|nog een plek|nog één plek|beperkt beschikbaar|mis dit niet)\b"),
)


def _placeholder_errors(text: str) -> list[str]:
    return ["unresolved placeholder"] if re.search(r"\[[^\]]+\]", text or "") else []


def _subject_errors(subject: str) -> list[str]:
    value = str(subject or "").strip()
    errors: list[str] = []
    if not value:
        return ["missing subject"]
    if re.match(r"(?i)^(?:re|fw|fwd)\s*:", value):
        errors.append("fake reply/forward subject is not allowed")
    if re.search(r"(?i)\b(?:laatste kans|alleen vandaag|urgent|direct resultaat|mis dit niet)\b", value):
        errors.append("clickbait or hype subject is not allowed")
    errors.extend(_placeholder_errors(value))
    return errors


def initial_copy_errors(subject: str, body: str) -> list[str]:
    text = str(body or "").strip()
    errors = _subject_errors(subject)
    if not text:
        return errors + ["missing body"]
    errors.extend(_placeholder_errors(text))
    urls = re.findall(r"https?://[^\s<>]+", text)
    if urls != [CASES_URL]:
        errors.append("initial must contain only the fixed cases URL exactly once")
    if f"\n{CASES_URL}\n" not in f"\n{text}\n":
        errors.append("cases URL must be a raw URL on its own line")
    cta_count = int(CTA_A in text) + int(CTA_B in text)
    if cta_count != 1 or text.count(CTA_A) > 1 or text.count(CTA_B) > 1:
        errors.append("initial must contain exactly one canonical CTA A or B")
    selected_cta = CTA_A if CTA_A in text and CTA_B not in text else CTA_B if CTA_B in text and CTA_A not in text else ""
    if text.count(OPT_OUT) != 1:
        errors.append("initial must contain the canonical easy opt-out exactly once")
    if not text.endswith(SIGNATURE):
        errors.append("initial must end with the canonical Andrew Baeten signature")
    if selected_cta and CASES_URL in text and OPT_OUT in text:
        if not (text.index(CASES_URL) < text.index(selected_cta) < text.index(OPT_OUT)):
            errors.append("initial content order violates LeadPromo")
    if any(pattern.search(text) for pattern in BANNED_PATTERNS):
        errors.append("initial contains a banned meeting, pressure or unsupported-result pattern")
    words = len(text.split())
    if words < 45 or words > 120:
        errors.append("initial length must stay within the 45-120 word hard guardrail")
    return errors


def followup_copy_errors(body: str) -> list[str]:
    text = str(body or "").strip()
    if not text:
        return ["missing follow-up body"]
    errors = _placeholder_errors(text)
    if re.search(r"https?://", text):
        errors.append("follow-up may not contain URLs")
    if not CANONICAL_FOLLOWUP_RE.fullmatch(text):
        errors.append("follow-up must match the canonical LeadPromo follow-up structure")
    if text.count(OPT_OUT) != 1:
        errors.append("follow-up must contain the canonical easy opt-out exactly once")
    if any(pattern.search(text) for pattern in BANNED_PATTERNS):
        errors.append("follow-up contains a banned meeting, pressure or unsupported-result pattern")
    return errors


def queue_copy_errors(row: dict[str, str]) -> list[str]:
    status = str(row.get("status", "")).strip().lower()
    if status == "approved":
        return initial_copy_errors(row.get("subject", ""), row.get("body", ""))
    if status == "sent" and str(row.get("followup_body", "")).strip():
        if str(row.get("followup_subject", "")).strip():
            return ["canonical follow-up must remain in-thread without a custom follow-up subject"] + followup_copy_errors(row.get("followup_body", ""))
        return followup_copy_errors(row.get("followup_body", ""))
    return []


def sequence_copy_errors(row: dict[str, str]) -> list[str]:
    if not sequence_enabled(row):
        return []
    status = str(row.get("status", "approved") or "approved").strip().lower()
    if status not in {"approved", "sent"}:
        return []
    try:
        step = int(str(row.get("step_number", "") or "0"))
    except ValueError:
        return ["invalid step_number for copy contract"]
    if step == 1:
        return initial_copy_errors(row.get("subject", ""), row.get("body", ""))
    if step == 2:
        return followup_copy_errors(row.get("body", ""))
    if step > 2:
        return ["LeadPromo default permits only initial + one follow-up; third+ touch requires a separately approved runtime contract"]
    return []


def process() -> int:
    settings = Settings.from_env()
    service = build_sheets_service()

    queue_headers, queue_rows = rows_from_values(get_values(service, settings.spreadsheet_id, QUEUE_SHEET))
    ensure_expected_headers(queue_headers, QUEUE_HEADERS + ["compliance_basis"], QUEUE_SHEET)
    sequence_headers, sequence_rows = rows_from_values(get_values(service, settings.spreadsheet_id, SEQUENCE_SHEET))
    ensure_expected_headers(sequence_headers, SEQUENCE_HEADERS, SEQUENCE_SHEET)

    errors: list[str] = []
    for row_number, row in enumerate(queue_rows, start=2):
        for error in queue_copy_errors(row):
            errors.append(f"{QUEUE_SHEET} row {row_number}: {error}")
    for row_number, row in enumerate(sequence_rows, start=2):
        for error in sequence_copy_errors(row):
            errors.append(f"{SEQUENCE_SHEET} row {row_number}: {error}")

    if errors:
        for error in errors[:50]:
            print("copy_error=" + error)
        print(f"LEADPROMO_COPY_PREFLIGHT=blocked invalid={len(errors)}")
        return 2
    print("LEADPROMO_COPY_PREFLIGHT=green")
    return 0


if __name__ == "__main__":
    raise SystemExit(process())
