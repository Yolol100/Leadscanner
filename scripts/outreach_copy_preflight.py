from __future__ import annotations

import re

from outreach_sender import (
    QUEUE_HEADERS, QUEUE_SHEET, Settings, build_sheets_service,
    ensure_expected_headers, get_values, rows_from_values,
)
from outreach_sequences import SEQUENCE_HEADERS, SEQUENCE_SHEET, enabled as sequence_enabled

LEGACY_CTA_A = "Zal ik nog één concreet idee sturen?"
LEGACY_CTA_B = "Mag ik nog één concreet idee sturen?"
LEGACY_CTA_A_EN = "Would you like me to send one more concrete idea?"
LEGACY_CTA_B_EN = "May I send one more concrete idea?"
FLOW_CTA_NL_RE = re.compile(r"^(?:Zal|Mag) ik de korte voorbeeldflow voor .+ sturen\?$", re.M)
FLOW_CTA_EN_RE = re.compile(r"^(?:Would you like me to|May I) send the short example flow for .+\?$", re.M)
OPT_OUT = 'Geen interesse? Een kort "nee" is genoeg.'
SIGNATURE = "Met vriendelijke groet,\nAndrew Baeten"
OPT_OUT_EN = 'Not interested? A quick "no" is enough.'
SIGNATURE_EN = "Best regards,\nAndrew Baeten"
CASES_URL = "https://andrewbaeten.nl/category/cases"
LEGACY_FOLLOWUP_NL_RE = re.compile(
    r'^Beste .+,\n\nIk kom hier nog één keer op terug\. Als het nuttig is, stuur ik het concrete idee voor .+ graag door\.\n\nGeen interesse\? Een kort "nee" is genoeg\.\n\nMet vriendelijke groet,\nAndrew Baeten$'
)
LEGACY_FOLLOWUP_EN_RE = re.compile(
    r'^Hi .+,\n\nJust following up once\. If useful, I\'m happy to send the concrete idea for .+\.\n\nNot interested\? A quick "no" is enough\.\n\nBest regards,\nAndrew Baeten$'
)
FLOW_FOLLOWUP_NL_RE = re.compile(
    r'^Beste .+,\n\nIk kom hier nog één keer op terug\. De korte voorbeeldflow voor .+ staat klaar\.\n\n(?:Zal|Mag) ik de korte voorbeeldflow voor .+ sturen\?\n\nGeen interesse\? Een kort "nee" is genoeg\.\n\nMet vriendelijke groet,\nAndrew Baeten$'
)
FLOW_FOLLOWUP_EN_RE = re.compile(
    r'^Hi .+ team,\n\nJust following up once\. The short example flow for .+ is ready\.\n\n(?:Would you like me to|May I) send the short example flow for .+\?\n\nNot interested\? A quick "no" is enough\.\n\nBest regards,\nAndrew Baeten$'
)
BANNED_PATTERNS = (
    re.compile(r"(?i)\b(?:plan|boek|reserveer|schedule|book)\b.{0,60}\b(?:call|meeting|gesprek|agenda|minuten|minutes)\b"),
    re.compile(r"(?i)\b(?:gegarandeerd|garandeert|garantie op|levert direct meer|levert meer aanvragen|meer omzet gegarandeerd|guaranteed|guarantees|guaranteed revenue|guaranteed results)\b"),
    re.compile(r"(?i)\b(?:alleen vandaag|laatste kans|nog een plek|nog één plek|beperkt beschikbaar|mis dit niet|last chance|limited time|only today|don't miss out)\b"),
)


def _placeholder_errors(text: str) -> list[str]:
    return ["unresolved placeholder"] if re.search(r"\[[^\]]+\]", text or "") else []


def _subject_errors(subject: str) -> list[str]:
    value = str(subject or "").strip()
    if not value:
        return ["missing subject"]
    errors: list[str] = []
    if re.match(r"(?i)^(?:re|fw|fwd)\s*:", value):
        errors.append("fake reply/forward subject is not allowed")
    if re.search(r"(?i)\b(?:laatste kans|alleen vandaag|urgent|direct resultaat|mis dit niet|last chance|limited time|guaranteed results)\b", value):
        errors.append("clickbait or hype subject is not allowed")
    if re.search(r"(?i)\b(?:AI|A\.I\.|automation|automatisering|bot|chatbot)\b", value):
        errors.append("subject must focus on the prospect/process, not AI or automation buzzwords")
    errors.extend(_placeholder_errors(value))
    return errors


def _flow_cta(text: str) -> tuple[str, str]:
    nl = FLOW_CTA_NL_RE.findall(text)
    en = FLOW_CTA_EN_RE.findall(text)
    if len(nl) + len(en) != 1:
        return "", ""
    return (nl[0], "nl") if nl else (en[0], "en")


def _legacy_cta(text: str) -> tuple[str, str]:
    variants = [
        (LEGACY_CTA_A, "nl"), (LEGACY_CTA_B, "nl"),
        (LEGACY_CTA_A_EN, "en"), (LEGACY_CTA_B_EN, "en"),
    ]
    selected = [(cta, lang) for cta, lang in variants if cta in text]
    return selected[0] if len(selected) == 1 else ("", "")


def initial_copy_errors(subject: str, body: str) -> list[str]:
    text = str(body or "").strip()
    errors = _subject_errors(subject)
    if not text:
        return errors + ["missing body"]
    errors.extend(_placeholder_errors(text))
    flow_cta, flow_lang = _flow_cta(text)
    legacy_cta, legacy_lang = _legacy_cta(text)
    if bool(flow_cta) == bool(legacy_cta):
        errors.append("initial must contain exactly one supported LeadPromo CTA contract")
        return errors
    is_flow = bool(flow_cta)
    selected_cta = flow_cta or legacy_cta
    language = flow_lang or legacy_lang
    urls = re.findall(r"https?://[^\s<>]+", text)
    if is_flow:
        if urls:
            errors.append("v13.1 value-flow initial may not contain external URLs by default")
        if "voorbeeldflow" not in text.casefold() and "example flow" not in text.casefold():
            errors.append("v13.1 initial must include the concrete example-flow value asset")
    else:
        if urls != [CASES_URL] or f"\n{CASES_URL}\n" not in f"\n{text}\n":
            errors.append("legacy initial must contain only the fixed cases URL exactly once on its own line")
    if text.count(selected_cta) != 1:
        errors.append("initial must contain the selected CTA exactly once")
    opt_out = OPT_OUT if language == "nl" else OPT_OUT_EN
    signature = SIGNATURE if language == "nl" else SIGNATURE_EN
    if text.count(opt_out) != 1:
        errors.append("initial must contain the canonical language-matched easy opt-out exactly once")
    if not text.endswith(signature):
        errors.append("initial must end with the canonical language-matched Andrew Baeten signature")
    if selected_cta in text and opt_out in text and text.index(selected_cta) > text.index(opt_out):
        errors.append("initial content order violates LeadPromo")
    if any(pattern.search(text) for pattern in BANNED_PATTERNS):
        errors.append("initial contains a banned meeting, pressure or unsupported-result pattern")
    words = len(text.split())
    if words < 40 or words > 120:
        errors.append("initial length must stay within the 40-120 word hard guardrail")
    return errors


def followup_copy_errors(body: str) -> list[str]:
    text = str(body or "").strip()
    if not text:
        return ["missing follow-up body"]
    errors = _placeholder_errors(text)
    if re.search(r"https?://", text):
        errors.append("follow-up may not contain URLs")
    language = ""
    if LEGACY_FOLLOWUP_NL_RE.fullmatch(text) or FLOW_FOLLOWUP_NL_RE.fullmatch(text):
        language = "nl"
    elif LEGACY_FOLLOWUP_EN_RE.fullmatch(text) or FLOW_FOLLOWUP_EN_RE.fullmatch(text):
        language = "en"
    else:
        errors.append("follow-up must match a supported canonical NL or EN LeadPromo structure")
    expected_opt_out = OPT_OUT if language == "nl" else OPT_OUT_EN if language == "en" else ""
    if expected_opt_out and text.count(expected_opt_out) != 1:
        errors.append("follow-up must contain the canonical language-matched easy opt-out exactly once")
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
        errors.extend(f"{QUEUE_SHEET} row {row_number}: {error}" for error in queue_copy_errors(row))
    for row_number, row in enumerate(sequence_rows, start=2):
        errors.extend(f"{SEQUENCE_SHEET} row {row_number}: {error}" for error in sequence_copy_errors(row))
    if errors:
        for error in errors[:50]:
            print("copy_error=" + error)
        print(f"LEADPROMO_COPY_PREFLIGHT=blocked invalid={len(errors)}")
        return 2
    print("LEADPROMO_COPY_PREFLIGHT=green")
    return 0


if __name__ == "__main__":
    raise SystemExit(process())