from __future__ import annotations

import re
import unicodedata

EEA_COUNTRIES = {
    "at", "be", "bg", "hr", "cy", "cz", "dk", "ee", "fi", "fr", "de", "gr", "hu", "ie", "it", "lv", "lt", "lu", "mt", "nl", "pl", "pt", "ro", "sk", "si", "es", "se", "is", "no", "li",
    "nederland", "netherlands", "belgie", "belgium", "duitsland", "deutschland", "germany", "frankrijk", "france", "spanje", "spain", "italie", "italy", "oostenrijk", "austria", "zweden", "sweden", "denemarken", "denmark", "finland", "ierland", "ireland", "portugal", "polen", "poland", "noorwegen", "norway", "ijsland", "iceland", "liechtenstein",
}

COMPLIANCE_PASSED = "COMPLIANCE_PASSED"
COMPLIANCE_NOT_PROVEN = "COMPLIANCE_NOT_PROVEN"
COMPLIANCE_BLOCKED = "COMPLIANCE_BLOCKED"
COMPLIANCE_STATUSES = {COMPLIANCE_PASSED, COMPLIANCE_NOT_PROVEN, COMPLIANCE_BLOCKED}

GATE_1 = "gate_1_consent"
GATE_2 = "gate_2_explicit_designation"
GATE_3 = "gate_3_existing_customer_similar"
ALLOWED_GATES = {GATE_1, GATE_2, GATE_3}
ALLOWED_BASES = {"consent", "explicit_designation", "existing_customer_similar"}
GATE_TO_BASIS = {
    GATE_1: "consent",
    GATE_2: "explicit_designation",
    GATE_3: "existing_customer_similar",
}
LIVE_CANDIDATE_STATUSES = {"prepared", "manual_review", "approved"}
GENERIC_LOCAL_PARTS = {"info", "contact", "hallo", "hello", "post", "mail", "office", "sales"}

COMPLIANCE_HEADERS = [
    "contact_verified",
    "contact_source",
    "compliance_basis",
    "compliance_gate_used",
    "compliance_evidence",
    "compliance_source",
    "compliance_checked_at",
    "compliance_purpose_match",
    "outreach_allowed",
]


def _country_tokens(country: str) -> set[str]:
    raw = unicodedata.normalize("NFKD", str(country or "").casefold())
    ascii_text = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return set(re.findall(r"[a-z]{2,}", ascii_text))


def country_is_eea(country: str) -> bool:
    return bool(_country_tokens(country) & EEA_COUNTRIES)


def _truthy(value: object) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _status(value: object) -> str:
    return str(value or "").strip().upper()


def generic_local_part(email: str) -> bool:
    address = str(email or "").strip().casefold()
    local = address.split("@", 1)[0] if "@" in address else ""
    return local in GENERIC_LOCAL_PARTS


def compliance_errors(row: dict[str, str]) -> list[str]:
    """Validate an already asserted compliance state. Never promote a row to PASS."""
    country = str(row.get("country", "")).strip()
    status = _status(row.get("compliance_status"))
    contact_verified = _truthy(row.get("contact_verified"))
    outreach_allowed = _truthy(row.get("outreach_allowed"))
    gate = str(row.get("compliance_gate_used", "")).strip().casefold()
    basis = str(row.get("compliance_basis", "")).strip().casefold()
    evidence = str(row.get("compliance_evidence", "")).strip()
    source = str(row.get("compliance_source", "")).strip()
    checked_at = str(row.get("compliance_checked_at", "")).strip()
    purpose_match = _truthy(row.get("compliance_purpose_match"))

    errors: list[str] = []
    if not country:
        errors.append("missing country/jurisdiction")
    if not contact_verified:
        errors.append("contact_verified is not true")
    if not str(row.get("contact_source", "")).strip():
        errors.append("missing contact_source")
    if status not in COMPLIANCE_STATUSES:
        errors.append("missing or invalid compliance_status")
        return errors

    if status != COMPLIANCE_PASSED:
        if outreach_allowed:
            errors.append("outreach_allowed must be false unless compliance is passed")
        return errors

    if not outreach_allowed:
        errors.append("COMPLIANCE_PASSED requires outreach_allowed=true")
    if gate not in ALLOWED_GATES:
        errors.append("COMPLIANCE_PASSED requires a valid compliance_gate_used")
    if basis not in ALLOWED_BASES:
        errors.append("COMPLIANCE_PASSED requires a valid compliance_basis")
    if gate in GATE_TO_BASIS and basis != GATE_TO_BASIS[gate]:
        errors.append("compliance_basis does not match compliance_gate_used")
    if not evidence:
        errors.append("COMPLIANCE_PASSED requires compliance_evidence")
    if not source:
        errors.append("COMPLIANCE_PASSED requires compliance_source")
    if not checked_at:
        errors.append("COMPLIANCE_PASSED requires compliance_checked_at")

    if country_is_eea(country) and gate == GATE_2:
        if not purpose_match:
            errors.append("Gate 2 requires explicit purpose match")
        if not evidence:
            errors.append("Gate 2 requires explicit designation evidence")

    return errors


def process() -> int:
    from outreach_sender import (
        QUEUE_HEADERS,
        QUEUE_SHEET,
        Settings,
        build_sheets_service,
        ensure_expected_headers,
        get_values,
        log_event,
        rows_from_values,
        update_row,
    )

    settings = Settings.from_env()
    service = build_sheets_service()
    headers, rows = rows_from_values(get_values(service, settings.spreadsheet_id, QUEUE_SHEET))
    ensure_expected_headers(headers, QUEUE_HEADERS + COMPLIANCE_HEADERS, QUEUE_SHEET)

    candidates: list[tuple[int, dict[str, str], list[str]]] = []
    for idx, row in enumerate(rows):
        if row.get("status", "").strip().casefold() not in LIVE_CANDIDATE_STATUSES:
            continue
        errors = compliance_errors(row)
        if errors or _status(row.get("compliance_status")) != COMPLIANCE_PASSED:
            candidates.append((idx, row, errors or ["compliance is not proven"]))

    if settings.mode == "validate":
        if candidates:
            print(f"mode=validate compliance_invalid={len(candidates)}")
            return 2
        print("mode=validate compliance_invalid=0")
        return 0

    for idx, row, errors in candidates:
        if _status(row.get("compliance_status")) != COMPLIANCE_BLOCKED:
            row["compliance_status"] = COMPLIANCE_NOT_PROVEN
        row["outreach_allowed"] = "false"
        row["last_error"] = "; ".join(errors)[:500]
        update_row(service, settings.spreadsheet_id, QUEUE_SHEET, idx + 2, headers, row)
        log_event(service, settings, row, "compliance_not_proven", detail=row["last_error"])

    print(f"mode={settings.mode} compliance_blocked={len(candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(process())
