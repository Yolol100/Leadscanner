from __future__ import annotations

EEA_COUNTRIES = {
    "at","be","bg","hr","cy","cz","dk","ee","fi","fr","de","gr","hu","ie","it","lv","lt","lu","mt","nl","pl","pt","ro","sk","si","es","se","is","no","li",
    "nederland","netherlands","belgie","belgium","duitsland","germany","frankrijk","france","spanje","spain","italie","italy","oostenrijk","austria","zweden","sweden","denemarken","denmark","finland","ierland","ireland","portugal","polen","poland","noorwegen","norway","ijsland","iceland","liechtenstein",
}
ALLOWED_BASES = {"consent", "existing_customer_similar", "other_verified_basis"}
LIVE_CANDIDATE_STATUSES = {"approved"}


def compliance_errors(row: dict[str, str]) -> list[str]:
    country = str(row.get("country", "")).strip().casefold()
    basis = str(row.get("compliance_basis", "")).strip().lower()
    errors: list[str] = []
    if not country:
        errors.append("missing country/jurisdiction")
    if basis not in ALLOWED_BASES:
        errors.append("missing or invalid compliance_basis")
    elif country in EEA_COUNTRIES and basis not in {"consent", "existing_customer_similar"}:
        errors.append("NL/EEA live commercial email requires consent or existing_customer_similar")
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
    ensure_expected_headers(headers, QUEUE_HEADERS + ["compliance_basis"], QUEUE_SHEET)

    candidates: list[tuple[int, dict[str, str], list[str]]] = []
    for idx, row in enumerate(rows):
        if row.get("status", "").strip().lower() not in LIVE_CANDIDATE_STATUSES:
            continue
        errors = compliance_errors(row)
        if errors:
            candidates.append((idx, row, errors))

    if settings.mode == "validate":
        if candidates:
            print(f"mode=validate compliance_invalid={len(candidates)}")
            return 2
        print("mode=validate compliance_invalid=0")
        return 0

    for idx, row, errors in candidates:
        row.update(status="blocked", last_error="; ".join(errors)[:500])
        update_row(service, settings.spreadsheet_id, QUEUE_SHEET, idx + 2, headers, row)
        log_event(service, settings, row, "blocked", detail=row["last_error"])

    print(f"mode={settings.mode} compliance_blocked={len(candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(process())
