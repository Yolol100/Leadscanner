from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import unquote, urlparse

from prospect_discovery import BoundedHttpClient, DiscoveryError, hosts_related, parse_page

NON_USER_FACING_BLOCK_RE = re.compile(r"(?is)<!--.*?-->|<(script|style|noscript|template)\b[^>]*>.*?</\1\s*>")
HIDDEN_ELEMENT_RE = re.compile(r"(?is)<([a-z][a-z0-9:-]*)\b(?=[^>]*(?:\bhidden\b|aria-hidden\s*=\s*[\"']?true|style\s*=\s*[\"'][^\"']*(?:display\s*:\s*none|visibility\s*:\s*hidden)))[^>]*>.*?</\1\s*>")
SUSPICIOUS_RE = re.compile(r"(?i)\b(?:ignore previous|system prompt|developer message|jailbreak|prompt injection|do not trust)\b")

AGENT_HINTS = {
    "front_desk_sales": ("book", "booking", "appointment", "schedule", "reserve", "consultation", "contact", "afspraak", "reserver"),
    "quote_intake": ("quote", "estimate", "pricing", "price", "intake", "offerte", "prijs", "aanvraag"),
    "commerce": ("shop", "store", "product", "collection", "catalog", "cart", "checkout", "buy", "webshop", "winkelwagen"),
    "customer_support": ("support", "help", "faq", "service", "return", "shipping", "warranty", "order", "retour"),
    "review_concierge": ("review", "testimonial", "customer stor", "rating", "beoordeling", "ervaring"),
}

GENERIC_PROCESS_LABELS = {
    "book", "book now", "booking", "appointment", "appointments", "schedule", "schedule now",
    "contact", "contact us", "get in touch", "request a quote", "get a quote", "quote", "free quote",
    "estimate", "free estimate", "pricing", "shop", "shop now", "store", "products", "product",
    "cart", "checkout", "support", "help", "faq", "customer service", "returns", "reviews", "testimonials",
    "afspraak", "contact opnemen", "offerte", "offerte aanvragen", "prijs aanvragen", "webshop", "producten",
    "winkelwagen", "klantenservice", "veelgestelde vragen", "retour", "reviews", "beoordelingen",
}

NAV_OR_LOW_VALUE = {
    "home", "about", "about us", "over ons", "contact", "privacy", "privacy policy", "terms", "cookies",
    "login", "sign in", "register", "news", "blog", "careers", "jobs", "facebook", "instagram", "linkedin",
    "youtube", "menu", "search", "sitemap", "learn", "downloads", "store finder", "all products", "view all products",
}

ACTION_PREFIX_RE = re.compile(r"(?i)^(?:view|learn|read|see|discover|explore|shop|buy|request|get|ask|contact)\b")


@dataclass(frozen=True)
class Personalization:
    anchor: str
    process_label: str
    observation: str
    value: str
    evidence_url: str


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _sanitize_html(html: str) -> str:
    cleaned = NON_USER_FACING_BLOCK_RE.sub(" ", html or "")
    return HIDDEN_ELEMENT_RE.sub(" ", cleaned)


def _safe_visible_label(value: str) -> str:
    value = _text(value).strip(" -|:;,.")
    if not value or len(value) < 3 or len(value) > 90:
        return ""
    if SUSPICIOUS_RE.search(value) or "http://" in value.casefold() or "https://" in value.casefold():
        return ""
    if "@" in value or "{{" in value or "}}" in value or "[" in value or "]" in value:
        return ""
    return value


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _remove_company(value: str, company: str) -> str:
    value = _text(value)
    company = _text(company)
    if not value or not company:
        return value
    result = re.sub(re.escape(company), " ", value, flags=re.I)
    return _text(result).strip(" -|:;,.")


def _title_descriptors(page, company: str) -> list[str]:
    raw = _safe_visible_label(getattr(page, "title", ""))
    if not raw:
        return []
    output: list[str] = []
    for part in re.split(r"\s+[|\-\u2013\u2014]\s+|\s*:\s*", raw):
        part = _safe_visible_label(_remove_company(part, company))
        if not part:
            continue
        norm = _norm(part)
        if not norm or norm in NAV_OR_LOW_VALUE or norm in GENERIC_PROCESS_LABELS:
            continue
        if len(norm.split()) < 2:
            continue
        if part not in output:
            output.append(part)
    return output[:5]


def _path_label(url: str) -> str:
    path = unquote(urlparse(url).path or "")
    parts = [part for part in path.split("/") if part]
    if not parts:
        return ""
    value = re.sub(r"[-_]+", " ", parts[-1])
    return _safe_visible_label(value)


def _process_candidates(page, agent_type: str) -> list[tuple[int, int, str]]:
    hints = AGENT_HINTS.get(agent_type, ())
    ranked: list[tuple[int, int, str]] = []
    for index, (target, raw_label) in enumerate(getattr(page, "links", [])[:200]):
        label = _safe_visible_label(raw_label) or _path_label(target)
        if not label:
            continue
        norm = _norm(label)
        if norm in NAV_OR_LOW_VALUE:
            continue
        path_norm = _norm(urlparse(target).path)
        score = 0
        if any(hint in norm for hint in hints):
            score += 6
        if any(hint in path_norm for hint in hints):
            score += 3
        if len(norm.split()) >= 2:
            score += 1
        if norm in GENERIC_PROCESS_LABELS:
            score -= 1
        if score > 0:
            ranked.append((-score, index, label))
    ranked.sort()
    return ranked


def _context_candidates(page, *, evidence_url: str, company: str, process_label: str) -> list[str]:
    evidence_host = (urlparse(evidence_url).hostname or "").lower().strip(".")
    process_norm = _norm(process_label)
    company_norm = _norm(company)
    ranked: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for index, (target, raw_label) in enumerate(getattr(page, "links", [])[:200]):
        label = _safe_visible_label(raw_label) or _path_label(target)
        if not label:
            continue
        norm = _norm(label)
        if not norm or norm in seen or norm in NAV_OR_LOW_VALUE or norm in GENERIC_PROCESS_LABELS:
            continue
        if norm == process_norm or norm == company_norm or ACTION_PREFIX_RE.search(label):
            continue
        target_host = (urlparse(target).hostname or "").lower().strip(".")
        if evidence_host and target_host and not hosts_related(evidence_host, target_host):
            continue
        words = norm.split()
        if len(words) < 2 or len(words) > 8:
            continue
        segments = [part for part in urlparse(target).path.split("/") if part]
        score = 0
        if len(segments) >= 2:
            score += 4
        elif len(segments) == 1:
            score += 2
        if 2 <= len(words) <= 5:
            score += 2
        elif len(words) <= 8:
            score += 1
        if any(ch.isdigit() for ch in label) or any(ch in label for ch in ("®", "™", "/")):
            score += 1
        if score > 0:
            ranked.append((-score, index, label))
            seen.add(norm)
    ranked.sort()
    return [label for _, _, label in ranked[:8]]


def _specific_anchor(page, company: str, agent_type: str, process_label: str, evidence_url: str) -> str:
    process_norm = _norm(process_label)
    if process_label and process_norm not in GENERIC_PROCESS_LABELS and len(process_norm.split()) >= 2:
        return process_label

    # For generic actions such as Get a Quote/Shop/FAQ, prefer one concrete
    # same-site product/service context over a broad industry title.
    contexts = _context_candidates(
        page,
        evidence_url=evidence_url,
        company=company,
        process_label=process_label,
    )
    if contexts:
        return contexts[0]

    for descriptor in _title_descriptors(page, company):
        if _norm(descriptor) != process_norm:
            return descriptor
    for _, _, label in _process_candidates(page, agent_type):
        norm = _norm(label)
        if norm not in GENERIC_PROCESS_LABELS and len(norm.split()) >= 2 and norm != process_norm:
            return label
    return ""


def _build_sentences(agent_type: str, anchor: str, process_label: str, language: str) -> tuple[str, str]:
    quoted_anchor = f'"{anchor}"'
    quoted_process = f'"{process_label}"' if process_label else ""
    if language == "nl":
        if process_label and _norm(process_label) != _norm(anchor):
            observation = f"Ik zag op je site {quoted_anchor} naast de route {quoted_process}."
        else:
            observation = f"Ik zag {quoted_anchor} als concrete route of context op je site."
        values = {
            "front_desk_sales": f"Rond {quoted_anchor} kan een kort voorbeeld eerst de relevante vraag en gegevens opvangen en daarna aansluiten op je bestaande afspraak- of teamroute",
            "quote_intake": f"Rond {quoted_anchor} kan een kort voorbeeld alleen de ontbrekende aanvraaggegevens uitvragen voordat je team de offerte of intake beoordeelt",
            "commerce": f"Rond {quoted_anchor} kan een kort voorbeeld productvragen helpen verduidelijken en daarna aansluiten op je bestaande shop-, winkelwagen- of orderroute",
            "customer_support": f"Rond {quoted_anchor} kan een kort voorbeeld routinevragen beantwoorden uit goedgekeurde informatie en uitzonderingen met context aan je team doorgeven",
            "review_concierge": f"Rond {quoted_anchor} kan een kort voorbeeld na een passende afgeronde klantactie een reviewverzoek starten met maximaal een goedgekeurde follow-up",
        }
    else:
        if process_label and _norm(process_label) != _norm(anchor):
            observation = f"I noticed {quoted_anchor} alongside the {quoted_process} path on your site."
        else:
            observation = f"I noticed {quoted_anchor} as a concrete path or context on your site."
        values = {
            "front_desk_sales": f"Around {quoted_anchor}, a short example could collect the useful question and details first, then continue into your existing booking or team handoff path",
            "quote_intake": f"Around {quoted_anchor}, a short example could ask only for missing request details before your team reviews the quote or intake",
            "commerce": f"Around {quoted_anchor}, a short example could help clarify product questions and then continue into your existing shop, cart or order path",
            "customer_support": f"Around {quoted_anchor}, a short example could answer routine questions from approved information and pass exceptions to your team with the useful context attached",
            "review_concierge": f"Around {quoted_anchor}, a short example could start a review request after the relevant completed customer action, with at most one approved follow-up",
        }
    value = values.get(agent_type, "")
    if not value:
        raise ValueError("agent type is not eligible for website-derived personalization")
    return observation, value


def build_personalization(page, *, company: str, agent_type: str, language: str, evidence_url: str) -> Personalization:
    if agent_type == "lead_reactivation":
        raise ValueError("lead_reactivation requires separately approved first-party personalization context")
    if agent_type not in AGENT_HINTS:
        raise ValueError("unsupported agent type for website-derived personalization")
    candidates = _process_candidates(page, agent_type)
    process_label = candidates[0][2] if candidates else ""
    anchor = _specific_anchor(page, company, agent_type, process_label, evidence_url)
    if not anchor:
        raise ValueError("no sufficiently specific public website/process anchor for personalized copy")
    observation, value = _build_sentences(agent_type, anchor, process_label, language)
    return Personalization(anchor=anchor, process_label=process_label, observation=observation, value=value, evidence_url=evidence_url)


def personalize_from_evidence(*, company: str, agent_type: str, language: str, evidence_url: str, fetcher: Callable[[str], str] | None = None) -> Personalization:
    evidence_url = _text(evidence_url)
    if not evidence_url:
        raise ValueError("evidence_url is required for personalized copy")
    try:
        if fetcher is None:
            client = BoundedHttpClient(
                user_agent=os.getenv("OUTREACH_PERSONALIZATION_USER_AGENT", "WebactueelOutreachPersonalization/1.0 (+https://andrewbaeten.nl)"),
                timeout=float(os.getenv("OUTREACH_PERSONALIZATION_TIMEOUT_SECONDS", "10") or "10"),
                max_bytes=int(os.getenv("OUTREACH_PERSONALIZATION_MAX_BYTES", "524288") or "524288"),
                min_interval=float(os.getenv("OUTREACH_PERSONALIZATION_MIN_INTERVAL_SECONDS", "0.25") or "0.25"),
            )
            html = client.fetch_text(evidence_url)
        else:
            html = fetcher(evidence_url)
        page = parse_page(_sanitize_html(html), evidence_url)
    except (DiscoveryError, OSError, ValueError) as exc:
        raise ValueError(f"personalization evidence fetch failed: {exc}") from exc
    return build_personalization(page, company=company, agent_type=agent_type, language=language, evidence_url=evidence_url)
