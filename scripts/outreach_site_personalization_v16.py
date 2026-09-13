from __future__ import annotations

import os
import re
from typing import Callable

import outreach_site_personalization as legacy
from prospect_discovery import BoundedHttpClient, DiscoveryError, parse_page


PHONE_LIKE_RE = re.compile(r"^\+?[\d\s()./\-]{7,}$")
LOW_VALUE_ANCHORS = {
    "skip to content", "skip content", "skip to main content", "skip to main",
    "ons team", "ons team bekijken", "team", "our team", "meet the team",
    "over ons", "about us", "wie wij zijn", "read more", "learn more",
    "meer informatie", "lees meer", "home", "contact", "menu", "search",
}


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _anchor_ok(value: str) -> bool:
    value = _text(value).strip(" -|:;,.")
    if not value:
        return False
    norm = legacy._norm(value)
    if not norm or norm in LOW_VALUE_ANCHORS or norm in legacy.NAV_OR_LOW_VALUE or norm in legacy.CONTEXT_LOW_VALUE_LABELS:
        return False
    if norm.startswith("skip to ") or norm.startswith("skip "):
        return False
    digits = sum(ch.isdigit() for ch in value)
    letters = sum(ch.isalpha() for ch in value)
    if PHONE_LIKE_RE.fullmatch(value) or (digits >= 6 and letters <= 2):
        return False
    if "@" in value or "http://" in value.casefold() or "https://" in value.casefold():
        return False
    return 2 <= len(norm.split()) <= 10


def _specific_anchor(page, company: str, agent_type: str, process_label: str, evidence_url: str) -> str:
    process_norm = legacy._norm(process_label)
    if process_label and process_norm not in legacy.GENERIC_PROCESS_LABELS and _anchor_ok(process_label):
        return process_label

    if process_label:
        for candidate in legacy._context_candidates(
            page,
            evidence_url=evidence_url,
            company=company,
            process_label=process_label,
        ):
            if _anchor_ok(candidate):
                return candidate

    for descriptor in legacy._title_descriptors(page, company):
        if legacy._norm(descriptor) != process_norm and _anchor_ok(descriptor):
            return descriptor

    for _, _, label in legacy._process_candidates(page, agent_type):
        norm = legacy._norm(label)
        if norm != process_norm and norm not in legacy.GENERIC_PROCESS_LABELS and _anchor_ok(label):
            return label
    return ""


def _build_sentences(agent_type: str, anchor: str, process_label: str, language: str) -> tuple[str, str]:
    quoted_anchor = f'"{anchor}"'
    quoted_process = f'"{process_label}"' if process_label else ""
    if language == "nl":
        if process_label and legacy._norm(process_label) != legacy._norm(anchor):
            observation = f"Ik zag op jullie site {quoted_anchor} naast de route {quoted_process}."
        else:
            observation = f"Ik zag op jullie site de route {quoted_anchor}."
        values = {
            "front_desk_sales": "een kort voorbeeld kan daar eerst de vraag en relevante gegevens opvangen en daarna aansluiten op jullie bestaande afspraak- of teamroute",
            "quote_intake": "een kort voorbeeld kan daar eerst ontbrekende aanvraaggegevens uitvragen voordat jullie team de offerte of intake beoordeelt",
            "commerce": "een kort voorbeeld kan productvragen daar verduidelijken en daarna aansluiten op jullie bestaande shop-, winkelwagen- of orderroute",
            "customer_support": "een kort voorbeeld kan daar routinevragen beantwoorden uit goedgekeurde informatie en uitzonderingen met context aan jullie team doorgeven",
            "review_concierge": "een kort voorbeeld kan na een passende afgeronde klantactie een reviewverzoek starten met maximaal één goedgekeurde follow-up",
        }
    else:
        if process_label and legacy._norm(process_label) != legacy._norm(anchor):
            observation = f"I noticed {quoted_anchor} alongside the {quoted_process} path on your site."
        else:
            observation = f"I noticed the {quoted_anchor} path on your site."
        values = {
            "front_desk_sales": "a short example could collect the question and useful details first, then continue into your existing booking or team handoff path",
            "quote_intake": "a short example could ask for missing request details first, before your team reviews the quote or intake",
            "commerce": "a short example could clarify product questions there and then continue into your existing shop, cart or order path",
            "customer_support": "a short example could answer routine questions from approved information and pass exceptions to your team with the useful context attached",
            "review_concierge": "a short example could start a review request after the relevant completed customer action, with at most one approved follow-up",
        }
    value = values.get(agent_type, "")
    if not value:
        raise ValueError("agent type is not eligible for website-derived personalization")
    return observation, value


def build_personalization(page, *, company: str, agent_type: str, language: str, evidence_url: str) -> legacy.Personalization:
    if agent_type == "lead_reactivation":
        raise ValueError("lead_reactivation requires separately approved first-party personalization context")
    if agent_type not in legacy.AGENT_HINTS:
        raise ValueError("unsupported agent type for website-derived personalization")
    candidates = legacy._process_candidates(page, agent_type)
    process_label = candidates[0][2] if candidates else ""
    anchor = _specific_anchor(page, company, agent_type, process_label, evidence_url)
    if not anchor:
        raise ValueError("no sufficiently specific public website/process anchor for personalized copy")
    observation, value = _build_sentences(agent_type, anchor, process_label, language)
    return legacy.Personalization(
        anchor=anchor,
        process_label=process_label,
        observation=observation,
        value=value,
        evidence_url=evidence_url,
    )


def personalize_from_evidence(*, company: str, agent_type: str, language: str, evidence_url: str, fetcher: Callable[[str], str] | None = None) -> legacy.Personalization:
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
        page = parse_page(legacy._sanitize_html(html), evidence_url)
    except (DiscoveryError, OSError, ValueError) as exc:
        raise ValueError(f"personalization evidence fetch failed: {exc}") from exc
    return build_personalization(
        page,
        company=company,
        agent_type=agent_type,
        language=language,
        evidence_url=evidence_url,
    )
