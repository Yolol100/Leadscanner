from __future__ import annotations

import hashlib
import re

import run_50_personalized_drafts_v2 as runner
from outreach_site_personalization import (
    _context_candidates,
    _sanitize_html,
    _title_descriptors,
)
from prospect_discovery import BoundedHttpClient, DiscoveryError, parse_page

_original_rows_from_values = runner.rows_from_values

def _compat_rows_from_values(values):
    return [], _original_rows_from_values(values)

runner.rows_from_values = _compat_rows_from_values
runner.MAX_CONTACT_PASSES = 6
runner.MAX_PREPARE_PASSES = 6

_original_selected_rows = runner.selected_rows
_original_build_drafts = runner.build_drafts

_GENERIC = {
    "quote", "quotes", "quote request", "quote requests", "request quote", "request a quote",
    "request a free quote", "free quote", "get a quote", "get quote", "request pricing", "pricing request",
    "contact", "contact us", "request", "offerte", "offerte aanvraag", "offerte aanvragen",
    "vraag vrijblijvend een offerte aan", "vrijblijvende offerte", "vrijblijvende offertes",
    "prijs aanvragen", "aanvraag",
}
_LOW = {
    "home", "about", "about us", "over ons", "our team", "ons team", "meet the team", "team",
    "our story", "our history", "history", "mission", "mission and vision", "vision", "company",
    "management team", "leadership", "skip to content", "menu", "search", "sitemap", "site map",
    "learn more", "read more", "more info", "contact", "contact us", "privacy", "privacy policy",
    "terms", "terms and conditions", "news", "blog", "careers", "jobs", "downloads", "resources",
}
_FILE_RE = re.compile(r"\.(?:pdf|docx?|xlsx?|pptx?|zip|jpe?g|png|gif|webp)\b", re.I)
_PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{6,}\d)")
_URL_RE = re.compile(r"(?:https?://|www\.)", re.I)
_EMAIL_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_CONTEXT_CACHE: dict[str, str] = {}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (text or "").casefold())).strip()


def _strong(text: str) -> bool:
    value = (text or "").strip()
    norm = _norm(value)
    if not norm or norm in _GENERIC or norm in _LOW:
        return False
    if _FILE_RE.search(value) or _PHONE_RE.search(value) or _URL_RE.search(value) or _EMAIL_RE.search(value):
        return False
    if not re.search(r"[A-Za-zÀ-ÿ]{3,}", value):
        return False
    return True


def _resolve_anchor(row: dict[str, str]) -> str:
    lead_id = str(row.get("lead_id", "")).strip()
    if lead_id in _CONTEXT_CACHE:
        return _CONTEXT_CACHE[lead_id]
    meta = runner.parse_agent_source(row.get("source", ""))
    current = str(meta.get("personalization_anchor", "")).strip()
    if _strong(current):
        _CONTEXT_CACHE[lead_id] = current
        return current

    website = str(row.get("website", "")).strip()
    company = str(row.get("company", "")).strip()
    process = str(meta.get("personalization_process_label", "")).strip()
    resolved = ""
    if website:
        try:
            client = BoundedHttpClient(
                user_agent="WebactueelNaturalDraft/1.0 (+https://andrewbaeten.nl)",
                timeout=8.0,
                max_bytes=524288,
                min_interval=0.25,
            )
            page = parse_page(_sanitize_html(client.fetch_text(website)), website)
            candidates = []
            candidates.extend(_context_candidates(page, evidence_url=website, company=company, process_label=process))
            candidates.extend(_title_descriptors(page, company))
            for candidate in candidates:
                if _strong(candidate) and _norm(candidate) != _norm(process):
                    resolved = candidate.strip()
                    break
        except (DiscoveryError, OSError, ValueError):
            resolved = ""
    _CONTEXT_CACHE[lead_id] = resolved
    return resolved


def _selected_rows() -> list[dict[str, str]]:
    source = _original_selected_rows()
    accepted: list[dict[str, str]] = []
    for row in source:
        anchor = _resolve_anchor(row)
        if not anchor:
            continue
        copy = dict(row)
        copy["__human_anchor"] = anchor
        accepted.append(copy)
    print(f"HUMAN_CONTEXT_GATE accepted={len(accepted)} weak_or_unresolved={len(source)-len(accepted)}", flush=True)
    return accepted

runner.selected_rows = _selected_rows


def _company(row: dict[str, str]) -> str:
    return re.sub(r"\s+", " ", str(row.get("company", "")).strip())


def _process(row: dict[str, str]) -> str:
    meta = runner.parse_agent_source(row.get("source", ""))
    return str(meta.get("personalization_process_label", "")).strip() or ("offerteaanvraag" if str(row.get("country", "")).upper() in {"NL", "BE"} else "quote request")


def _variant(row: dict[str, str]) -> int:
    return hashlib.sha256(str(row.get("lead_id", "")).encode("utf-8")).digest()[0] % 3


def _english(row: dict[str, str], anchor: str, process: str) -> str:
    company = _company(row)
    v = _variant(row)
    openings = [
        f"I was looking at the {process} route on your site and noticed {anchor}.",
        f"While looking at how {company} handles {process} online, {anchor} stood out to me.",
        f"I came across {anchor} in the part of your site that leads into {process}.",
    ]
    ideas = [
        "One small idea: collect only the request details that are still missing before it reaches the team, so the first review starts with a more complete request.",
        "A simple improvement could be to ask for any missing request details first and then pass the complete request to the person who actually reviews it.",
        "I would keep it simple: fill in the missing request information before the handoff, without changing the rest of your quote process.",
    ]
    ctas = [
        f"Would you like me to send a short example using {anchor} as the starting point?",
        f"Want me to send a simple example of how that could work for {company}?",
        f"Would it be useful if I sent over a short example for {company}?",
    ]
    return (
        f"Hi {company} team,\n\n{openings[v]}\n\n{ideas[v]}\n\n{ctas[v]}\n\n"
        "Not relevant? A quick \"no\" is enough.\n\nThis is a commercial message.\n\n"
        "Best regards,\nAndrew Baeten\n{{OUTREACH_POSTAL_ADDRESS}}\nandrewbaeten.nl"
    )


def _dutch(row: dict[str, str], anchor: str, process: str) -> str:
    company = _company(row)
    v = _variant(row)
    openings = [
        f"Ik bekeek de route rond {process} op jullie site en daar viel {anchor} me op.",
        f"Toen ik keek hoe {company} {process} online heeft ingericht, kwam ik {anchor} tegen.",
        f"Op jullie site kwam ik {anchor} tegen binnen de route naar {process}.",
    ]
    ideas = [
        "Een klein idee: laat een aanvrager vóór de beoordeling alleen de ontbrekende gegevens aanvullen, zodat jullie team meteen met een completere aanvraag verder kan.",
        "Je zou eerst alleen de ontbrekende aanvraaggegevens kunnen uitvragen en daarna de complete aanvraag bij degene laten landen die hem echt beoordeelt.",
        "Ik zou het simpel houden: eerst ontbrekende aanvraaginfo aanvullen en daarna pas doorzetten, zonder de rest van jullie offerteproces te veranderen.",
    ]
    ctas = [
        f"Zal ik een kort voorbeeld sturen met {anchor} als uitgangspunt?",
        f"Zal ik een eenvoudig voorbeeld sturen van hoe dat voor {company} kan werken?",
        f"Is het nuttig als ik daar een kort voorbeeld voor {company} van stuur?",
    ]
    return (
        f"Hallo team van {company},\n\n{openings[v]}\n\n{ideas[v]}\n\n{ctas[v]}\n\n"
        "Niet relevant? Een kort \"nee\" is genoeg.\n\nDit is een commercieel bericht.\n\n"
        "Met vriendelijke groet,\nAndrew Baeten\nandrewbaeten.nl"
    )


def _build_drafts(rows_to_draft: list[dict[str, str]]):
    rewritten = []
    for row in rows_to_draft:
        copy = dict(row)
        anchor = str(copy.get("__human_anchor", "")).strip() or _resolve_anchor(copy)
        if not anchor:
            raise RuntimeError(f"human context disappeared for {copy.get('lead_id')}")
        process = _process(copy)
        country = str(copy.get("country", "")).strip().upper()
        copy["body"] = _dutch(copy, anchor, process) if country in {"NL", "BE"} else _english(copy, anchor, process)
        rewritten.append(copy)
    return _original_build_drafts(rewritten)

runner.build_drafts = _build_drafts

if __name__ == "__main__":
    raise SystemExit(runner.main())
