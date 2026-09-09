from __future__ import annotations

import hashlib
import re

import run_50_personalized_drafts_v2 as runner

# Adapter compatibility for the temporary v2 runner.
_original_rows_from_values = runner.rows_from_values

def _compat_rows_from_values(values):
    return [], _original_rows_from_values(values)

runner.rows_from_values = _compat_rows_from_values

# Keep the continuation bounded but avoid repeatedly burning all contact passes
# on the same robots-blocked candidate.
runner.MAX_CONTACT_PASSES = 6
runner.MAX_PREPARE_PASSES = 6

_original_selected_rows = runner.selected_rows
_original_build_drafts = runner.build_drafts

_GENERIC = {
    "quote", "quotes", "quote request", "quote requests", "request quote", "request a quote",
    "get a quote", "get quote", "request pricing", "pricing request", "contact", "contact us",
    "request", "offerte", "offerte aanvragen", "prijs aanvragen", "aanvraag",
}
_LOW_VALUE = {
    "our team", "ons team", "meet the team", "about", "about us", "over ons", "home",
    "company", "our story", "contact us", "contact", "learn more", "read more", "more info",
    "privacy", "privacy policy", "terms", "news", "blog", "careers", "jobs",
}
_FILE_RE = re.compile(r"\.(?:pdf|docx?|xlsx?|pptx?|zip|jpe?g|png|gif|webp)\b", re.I)
_PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{6,}\d)")
_URL_RE = re.compile(r"(?:https?://|www\.)", re.I)
_EMAIL_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (text or "").casefold())).strip()


def _human_ok(row: dict[str, str]) -> bool:
    meta = runner.parse_agent_source(row.get("source", ""))
    anchor = str(meta.get("personalization_anchor", "")).strip()
    if not anchor:
        return False
    norm = _norm(anchor)
    if not norm or norm in _GENERIC or norm in _LOW_VALUE:
        return False
    if _FILE_RE.search(anchor) or _PHONE_RE.search(anchor) or _URL_RE.search(anchor) or _EMAIL_RE.search(anchor):
        return False
    if not re.search(r"[A-Za-zÀ-ÿ]{3,}", anchor):
        return False
    if not str(meta.get("fact", "")).strip() or not str(meta.get("value_asset_summary", "")).strip():
        return False
    return True


def _selected_rows() -> list[dict[str, str]]:
    source = _original_selected_rows()
    accepted = [row for row in source if _human_ok(row)]
    print(f"HUMAN_COPY_GATE accepted={len(accepted)} weak_rejected={len(source)-len(accepted)}", flush=True)
    return accepted

runner.selected_rows = _selected_rows


def _clean_company(company: str) -> str:
    return re.sub(r"\s+", " ", (company or "").strip())


def _english_body(row: dict[str, str], anchor: str, process: str, variant: int) -> str:
    company = _clean_company(row.get("company", ""))
    process_phrase = process or "quote request"
    if _norm(anchor) == _norm(process_phrase):
        openers = [
            f"I was looking at the {anchor} route on your site.",
            f"I came across the {anchor} path on {company}'s site.",
            f"I had a look at how {company} handles {anchor} online.",
        ]
    else:
        openers = [
            f"I noticed {anchor} in the part of your site that leads into {process_phrase}.",
            f"While looking at {company}'s {process_phrase} route, {anchor} stood out to me.",
            f"I came across {anchor} alongside the {process_phrase} path on your site.",
        ]
    ideas = [
        "One small idea: ask only for the request details that are still missing before it reaches the team, so the first review starts with a more complete request.",
        "A simple improvement could be to collect any missing request details before the team reviews it, without changing the rest of your quote process.",
        "I would keep it simple: fill in the missing request information first, then pass the complete request to the person who actually needs to review it.",
    ]
    ctas = [
        f"Would you like me to send a short example using {anchor} as the starting point?",
        f"Want me to send a short example of how that could work for {company}?",
        f"Would it be useful if I sent over a simple example for {company}?",
    ]
    return (
        f"Hi {company} team,\n\n"
        f"{openers[variant]}\n\n"
        f"{ideas[variant]}\n\n"
        f"{ctas[variant]}\n\n"
        "Not relevant? A quick \"no\" is enough.\n\n"
        "This is a commercial message.\n\n"
        "Best regards,\n"
        "Andrew Baeten\n"
        "{{OUTREACH_POSTAL_ADDRESS}}\n"
        "andrewbaeten.nl"
    )


def _dutch_body(row: dict[str, str], anchor: str, process: str, variant: int) -> str:
    company = _clean_company(row.get("company", ""))
    process_phrase = process or "offerteaanvraag"
    if _norm(anchor) == _norm(process_phrase):
        openers = [
            f"Ik bekeek de route rond {anchor} op jullie site.",
            f"Ik kwam op de site van {company} de route {anchor} tegen.",
            f"Ik keek even hoe {company} {anchor} online heeft ingericht.",
        ]
    else:
        openers = [
            f"Op jullie site viel {anchor} me op binnen de route naar {process_phrase}.",
            f"Toen ik naar de {process_phrase}-route van {company} keek, viel {anchor} me op.",
            f"Ik kwam {anchor} tegen naast de route {process_phrase} op jullie site.",
        ]
    ideas = [
        "Een klein idee: laat een aanvrager vóór de beoordeling alleen de ontbrekende gegevens aanvullen, zodat jullie team meteen met een completere aanvraag verder kan.",
        "Je zou daar eerst alleen de ontbrekende aanvraaggegevens kunnen uitvragen en daarna de complete aanvraag bij het team laten landen, zonder de rest van het offerteproces te veranderen.",
        "Ik zou het simpel houden: eerst ontbrekende aanvraaginfo aanvullen, daarna pas doorzetten naar degene die de offerte of intake echt beoordeelt.",
    ]
    ctas = [
        f"Zal ik een kort voorbeeld sturen met {anchor} als uitgangspunt?",
        f"Zal ik een eenvoudig voorbeeld sturen van hoe dat voor {company} kan werken?",
        f"Is het nuttig als ik daar een kort voorbeeld voor {company} van stuur?",
    ]
    return (
        f"Hallo team van {company},\n\n"
        f"{openers[variant]}\n\n"
        f"{ideas[variant]}\n\n"
        f"{ctas[variant]}\n\n"
        "Niet relevant? Een kort \"nee\" is genoeg.\n\n"
        "Dit is een commercieel bericht.\n\n"
        "Met vriendelijke groet,\n"
        "Andrew Baeten\n"
        "andrewbaeten.nl"
    )


def _human_body(row: dict[str, str]) -> str:
    meta = runner.parse_agent_source(row.get("source", ""))
    anchor = str(meta.get("personalization_anchor", "")).strip()
    process = str(meta.get("personalization_process_label", "")).strip()
    digest = hashlib.sha256(str(row.get("lead_id", "")).encode("utf-8")).digest()
    variant = digest[0] % 3
    country = str(row.get("country", "")).strip().upper()
    if country in {"NL", "BE"}:
        return _dutch_body(row, anchor, process, variant)
    return _english_body(row, anchor, process, variant)


def _build_drafts(rows_to_draft: list[dict[str, str]]):
    # Temporarily swap the queue body with the human rewrite only for IMAP draft
    # rendering. The canonical queue stays manual_review/non-sendable and is not
    # rewritten by this temporary execution branch.
    rewritten = []
    for row in rows_to_draft:
        copy = dict(row)
        copy["body"] = _human_body(copy)
        rewritten.append(copy)
    return _original_build_drafts(rewritten)

runner.build_drafts = _build_drafts

if __name__ == "__main__":
    raise SystemExit(runner.main())
