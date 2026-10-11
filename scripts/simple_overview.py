#!/usr/bin/env python3
"""A short operator view over the existing, safety-audited run manifest.

Keeps advanced diagnostics in JSON; prints only aggregate counts in Dutch.
Never loads contact records, message copy or campaign credentials.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


COUNT_LABELS = {
    "discovery_after_cheap_filters": "Websites na eerste selectie",
    "dedupe_kept": "Nog niet eerder benaderd",
    "verified_for_research": "Officiële websites geverifieerd",
    "research_ready": "Websites onderzocht",
    "outreach_reason_ready": "Bruikbare observaties gevonden",
    "review_queue_candidates": "Klaar voor beoordeling",
    "approved_for_instantly": "Goedgekeurd",
    "instantly_staged": "Klaargezet in Instantly",
    "approved_for_draft": "Goedgekeurd",
    "draft_created": "Concepten opgeslagen",
    "draft_existing_exact": "Bestaande concepten bevestigd",
    "suppressed_after_preview": "Terecht overgeslagen na nieuwe controle",
}
DROP_LABELS = {
    "cheap_filter": "Eerste selectie",
    "dedupe": "Al bekend of uitgesloten",
    "verification": "Contact niet bevestigd",
    "research": "Geen bruikbaar onderzoek",
    "outreach": "Geen concrete observatie",
    "value_action": "Geen passend voorstel",
    "mail": "Concept voldoet niet",
}
MODES = {
    "preview": ("Onderzoeken", "Bekijk de review-queue en keur alleen de gewenste contacten goed."),
    "instantly_stage": ("Klaarzetten", "Controleer de campagne apart. Verzenden vereist nieuwe expliciete goedkeuring."),
    "draft": ("Concepten bewaren", "Controleer de opgeslagen concepten. Er is niets verzonden."),
}


def render_overview(manifest: dict) -> str:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "leadscanner-cold-run-manifest/1.0":
        raise ValueError("overview_requires_a_valid_manifest")
    mode = manifest.get("execution_mode")
    if mode not in MODES:
        raise ValueError("overview_unsupported_execution_mode")
    safety, closure = manifest.get("safety") or {}, manifest.get("closure") or {}
    if safety.get("automatic_send") is not False or closure.get("automatic_send") is not False:
        raise ValueError("overview_requires_no_send_evidence")
    counts = manifest.get("counts") or {}
    if not isinstance(counts, dict):
        raise ValueError("overview_counts_must_be_object")
    for key in COUNT_LABELS:
        number = counts.get(key, 0)
        if type(number) is not int or number < 0:
            raise ValueError("overview_counts_must_be_nonnegative_integers")

    title, next_action = MODES[mode]
    lines = ["# Leadscanner — eenvoudig overzicht", "",
             f"**Actie:** {title}", "**Verzonden:** 0 (geen automatische e-mails)", ""]
    if mode == "preview":
        lines.extend([
            "## 1. Zoeken en controleren", "",
            f"- Websites na eerste selectie: **{counts.get('discovery_after_cheap_filters', 0)}**",
            f"- Na de historische dubbele-contactcontrole: **{counts.get('dedupe_kept', 0)}**",
            f"- Websites geverifieerd: **{counts.get('verified_for_research', 0)}**", "",
            "## 2. Website onderzoeken", "",
            f"- Onderzochte websites met bruikbare bronnen: **{counts.get('research_ready', 0)}**",
            f"- Websites met concrete bevindingen: **{counts.get('outreach_reason_ready', 0)}**", "",
            "## 3. Belangrijkste punten kiezen", "",
            "- Per website maximaal zes onderbouwde, geprioriteerde bevindingen; minder als er onvoldoende bewijs is.",
        ])
        copy_mode = (manifest.get("request") or {}).get("preview_copy_mode", "reviewed_mail")
        lines.extend(["", "## 4. Beoordelen", "",
                      f"- Contacten klaar voor beoordeling: **{counts.get('review_queue_candidates', 0)}**",
                      "- " + ("Alleen feiten, nog geen e-mailtekst." if copy_mode == "instantly_sequence"
                             else "Persoonlijke conceptmails, nog niet verzonden.")])
        reasons = (manifest.get("diagnostics") or {}).get("drop_reasons") or {}
        if isinstance(reasons, dict):
            ranked = sorted(
                ((sum(int(n) for n in details.values()), DROP_LABELS.get(name, name))
                 for name, details in reasons.items() if isinstance(details, dict)
                 and all(type(n) is int and n >= 0 for n in details.values())),
                reverse=True,
            )[:3]
            useful = [(n, label) for n, label in ranked if n]
            if useful:
                lines.extend(["", "## Grootste oorzaken van uitval", ""])
                lines.extend(f"- {label}: {n}" for n, label in useful)
    elif mode == "instantly_stage":
        lines.extend([
            f"- Goedgekeurd: **{counts.get('approved_for_instantly', 0)}**",
            f"- Klaargezet in Instantly: **{counts.get('instantly_staged', 0)}**",
            f"- Uitgesloten na hercontrole: **{counts.get('suppressed_after_preview', 0)}**",
            "- Campagneactivering staat los van deze stap.",
        ])
    else:
        lines.extend([
            f"- Goedgekeurd: **{counts.get('approved_for_draft', 0)}**",
            f"- Concepten opgeslagen: **{counts.get('draft_created', 0)}**",
            f"- Bestaande concepten bevestigd: **{counts.get('draft_existing_exact', 0)}**",
        ])
    lines.extend(["", "## Volgende stap", "", next_action, "",
                  "Technische controles, bronbewijs en gedetailleerde redenen blijven beschikbaar in de JSON-rapporten."])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(args.input).read_text(encoding="utf-8"))
    overview = render_overview(manifest)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(overview, encoding="utf-8")
    print("LEADSCANNER_OVERVIEW=green automatic_send=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
