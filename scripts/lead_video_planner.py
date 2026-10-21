"""Private, pure helpers for bounded lead-to-video routing and factual drafts.

No network, recipients, Sheets, IMAP, scheduling or output to public CI logs.
The invoking controller must verify private historical/HMAC suppressions first.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
import re
import ipaddress
import unicodedata

MAX_CANDIDATES = 100
MAX_VIDEO = 5
MAX_PREVIEW_PAGES = 3
MAX_EVIDENCE_AGE_DAYS = 30
MAX_AHREFS_AGE_DAYS = 90
OPT_OUT = "Liever geen e-mails meer? Antwoord met 'nee', dan laat ik het hierbij."
FORBIDDEN_SUBJECT = re.compile(r"\b(gratis|korting|aanbieding|omzet|garantie|seo|ai|deal|webactueel)\b", re.I)
EVIDENCE_STOPWORDS = frozenset({"ik", "zag", "dat", "klanten", "jullie", "bij", "een", "en", "van", "het", "de", "dit", "die", "zijn", "kan", "kunnen", "kunt", "voor", "met", "ook", "wordt", "wij", "via", "onze", "jouw", "uw", "in", "is", "om", "maar", "als", "welke", "hebben", "maken"})


def _host(url: str) -> str:
    """Validate a public-looking HTTP URL (no network access is attempted)."""
    if not isinstance(url, str):
        raise ValueError("url_missing")
    try:
        part = urlsplit(url)
        host = (part.hostname or "").lower().removeprefix("www.")
        if (part.scheme not in {"https", "http"} or not host or
                host in {"localhost", "localhost.localdomain"} or
                "." not in host or part.username or part.password or
                part.fragment or any(c.isspace() for c in url)):
            raise ValueError("url_not_public_http")
        try:
            ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            pass
        else:
            raise ValueError("ip_address_not_allowed")
        if part.port is not None and part.port not in {80, 443}:
            raise ValueError("nonstandard_port_not_allowed")
        if host.startswith(".") or host.endswith(".") or ".." in host:
            raise ValueError("domain_invalid")
        return host
    except (ValueError, AttributeError):
        raise ValueError("url_not_public_http") from None


def _source_on_site(site: str, source: str) -> bool:
    parent = _host(site)
    host = _host(source)
    return host == parent or host.endswith("." + parent)


def _date(when: str, *, max_age_days: int = MAX_EVIDENCE_AGE_DAYS) -> None:
    """Dated evidence must be timezone-aware and recent enough for outreach."""
    try:
        value = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if (value.tzinfo is None or value > now or
                now - value > timedelta(days=max_age_days)):
            raise ValueError("evidence_date_invalid")
    except (TypeError, ValueError):
        raise ValueError("evidence_date_invalid") from None


def _single_line(value: str, limit: int, field: str) -> str:
    if (not isinstance(value, str) or not value.strip() or
            len(value) > limit or "\n" in value or "\r" in value or
            "{" in value or "}" in value or "[" in value or "]" in value or
            any(unicodedata.category(ch) in {"Cc", "Cf", "Zl", "Zp"} for ch in value)):
        raise ValueError(field + "_invalid")
    return value.strip()


def _evidence_overlap(excerpt: str, observation: str) -> bool:
    """Catch obvious ungrounded opening claims; semantic human review still required."""
    normal = lambda value: {w for w in re.findall(r"[a-z\u00e0-\u00ff]{4,}", value.casefold())
                            if w not in EVIDENCE_STOPWORDS}
    common = normal(excerpt) & normal(observation)
    return len(common) >= 2


def _business_email(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 254 or value.count("@") != 1:
        return False
    local, domain = value.casefold().split("@")
    return bool(re.fullmatch(r"[a-z0-9._%+\-]{1,64}", local) and
                not local.startswith(".") and not local.endswith(".") and
                ".." not in local and re.fullmatch(
                    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain))


def route_verified_leads(leads: list[dict], *, requested: int,
                         suppression_complete: bool) -> dict[str, list[dict]]:
    """Split verified leads; lightweight evidence only, NEVER score mail leads.

    Caller supplies pre-reviewed video flags with a specific public source.
    A known suppressed/previously contacted lead is skipped, not emailed.
    Any unknown global registry state aborts the entire operation.
    """
    if suppression_complete is not True:
        raise RuntimeError("full_historical_suppression_unavailable")
    if (type(requested) is not int or not 1 <= requested <= MAX_CANDIDATES or
            not isinstance(leads, list) or len(leads) > requested):
        raise ValueError("requested_count_invalid")
    video_opportunities, eligible, skipped = [], [], []
    hosts, emails = set(), set()
    for row in leads:
        if not isinstance(row, dict):
            raise ValueError("lead_record_invalid")
        if row.get("suppressed") is True or row.get("prior_contact") is True:
            skipped.append(row)
            continue
        if (row.get("status") != "verified_website_and_email" or
                row.get("suppressed") is not False or
                row.get("prior_contact") is not False or
                row.get("email_first_party_verified") is not True or
                row.get("approved_source_verified") is not True):
            skipped.append(row)
            continue
        host = _host(row.get("website"))
        email = str(row.get("email", "")).lower()
        official = row.get("official_contact_url", "")
        if (host in hosts or email in emails or not _business_email(email) or
                not row.get("company") or not official or
                not _source_on_site(row["website"], official)):

            raise RuntimeError("private_verified_batch_duplicate_or_invalid")
        hosts.add(host)
        emails.add(email)
        eligible.append(row)
        proof = row.get("video_opportunity")
        if proof is not None:
            if (not isinstance(proof, dict) or proof.get("verified") is not True or
                    proof.get("business_impact_reviewed") is not True or
                    proof.get("evidence_type") not in {"official_site_observation",
                                                     "measured_performance",
                                                     "confirmed_cro_friction"}):
                raise ValueError("video_opportunity_unverified")
            if not _source_on_site(row["website"], proof.get("source_url", "")):
                raise ValueError("video_opportunity_not_first_party")
            _date(proof.get("checked_at"))
            _single_line(proof.get("observed", ""), 350, "video_observation")
            # The caller may give a QUALITATIVE opportunity band based on
            # a first-party observation, never a numerical lead/SEO score.
            # Missing band preserves behavior of earlier verified records.
            strength = proof.get("priority_band", "possible")
            if not isinstance(strength, str) or strength not in {"strong", "possible", "weak"}:
                raise ValueError("video_priority_band_invalid")
            if strength in {"strong", "possible"}:
                video_opportunities.append((strength, row))
    # Choose the most compelling verified opportunities, not merely the
    # first five discovered. Ties preserve input order, for reproducibility.
    video_opportunities.sort(key=lambda item: 0 if item[0] == "strong" else 1)
    video = [row for _, row in video_opportunities[:MAX_VIDEO]]
    selected = {id(row) for row in video}
    # Ordinary leads retain their discovery order, even when later video
    # candidates have higher qualitative priority than earlier candidates.
    ordinary = [row for row in eligible if id(row) not in selected]
    return {"video": video, "email": ordinary, "skipped": skipped}


def render_short_email(*, website: str, source_url: str, checked_at: str,
                       source_excerpt: str, observation: str, question: str,
                       subject: str, inspected_pages: list[str],
                       relevance_reviewed: bool, feature_already_available: bool | None,
                       verified_official_source: bool) -> dict[str, str]:
    """Create the exact owner-approved two-paragraph Dutch email, privately.

    This function DOES NOT establish that an observed feature truly exists.
    Reviewer supplies and confirms source excerpts plus absence of an already
    offered improvement. Existing mail sender/IMAP transport is untouched.
    """
    if verified_official_source is not True or relevance_reviewed is not True:
        raise ValueError("first_party_review_required")
    if feature_already_available is not False:
        raise ValueError("proposed_feature_present_or_unknown")
    if (not isinstance(inspected_pages, list) or
            not 1 <= len(inspected_pages) <= MAX_PREVIEW_PAGES or
            len(set(inspected_pages)) != len(inspected_pages)):
        raise ValueError("bounded_pages_invalid")
    if not all(_source_on_site(website, page) for page in inspected_pages):
        raise ValueError("untrusted_evidence_page")
    if source_url not in inspected_pages:
        raise ValueError("observation_source_not_inspected")
    _date(checked_at)
    source_excerpt = _single_line(source_excerpt, 400, "source_excerpt")
    observation = _single_line(observation, 220, "observation")
    question = _single_line(question, 230, "question")
    subject = _single_line(subject, 72, "subject")
    if not _evidence_overlap(source_excerpt, observation):
        raise ValueError("observation_not_grounded_in_excerpt")
    if re.search(r"\b(geen|niet|ontbreekt|kapot|fout|broken)\b", observation, re.I):
        raise ValueError("negative_observation_needs_manual_evidence")
    if FORBIDDEN_SUBJECT.search(subject):
        raise ValueError("commercial_subject_disallowed")
    if (not observation.startswith("Ik zag dat ") or
            not observation.endswith(".") or "?" in observation or
            not question.startswith("Zou het handig zijn als ") or
            not question.endswith("?") or question.count("?") != 1):
        raise ValueError("fixed_email_form_required")
    body = ("Goedendag,\n\n" + observation + "\n\n" + question + "\n\n" +
            OPT_OUT + "\n\nGroet,\nAndrew")
    if len(body.split()) > 110:
        raise ValueError("email_too_long")
    if any(word in body.casefold() for word in ("webactueel", "ik heb een video", "gratis analyse")):
        raise ValueError("unwanted_email_promotion")
    return {"subject": subject, "body": body}


def prepare_video_storyboard(*, website: str, findings: list[dict],
                             ahrefs: dict | None, competitor: dict | None) -> dict:
    """Private screen sequence/script from verified issues, never guesses.

    A missing Ahrefs data source yields a *not checked* scene, not a number.
    Human still reviews recording and actual source pages.
    """
    if not isinstance(findings, list) or not 2 <= len(findings) <= 5:
        raise ValueError("video_findings_out_of_range")
    scenes = []
    for item in findings:
        if not isinstance(item, dict) or item.get("verified") is not True:
            raise ValueError("video_finding_unverified")
        page = item.get("source_url", "")
        if not _source_on_site(website, page):
            raise ValueError("video_source_wrong_site")
        _date(item.get("checked_at"))
        observed = _single_line(item.get("observed", ""), 360, "observed")
        change = _single_line(item.get("change", ""), 360, "change")
        scenes.append({"screen": page,
                       "say": f"Op deze pagina zie je {observed}. Een mogelijke verbetering is {change}."})
    if ahrefs is not None:
        if not isinstance(ahrefs, dict) or not _source_on_site(website, ahrefs.get("target_url", "")):
            raise ValueError("ahrefs_wrong_domain")
        if not _source_on_site(website, ahrefs.get("ranking_url", "")):
            raise ValueError("ahrefs_ranking_page_wrong_domain")
        if not isinstance(ahrefs, dict) or ahrefs.get("country") != "NL":
            raise ValueError("ahrefs_country_invalid")
        _date(ahrefs.get("checked_at"), max_age_days=MAX_AHREFS_AGE_DAYS)
        keyword = _single_line(ahrefs.get("keyword", ""), 120, "keyword")
        position = ahrefs.get("position")
        if type(position) is not int or position < 1:
            raise ValueError("ahrefs_position_invalid")
        scenes.append({"screen": "Ahrefs Site Explorer > Organic keywords > Netherlands",
                       "say": (f"Volgens Ahrefs staat de pagina op de meetdatum voor '{keyword}' "
                               f"op positie {position}. Dit is een externe schatting, geen eigen "
                               "Search Console-meting en geen garantie op verbetering.")})
    else:
        scenes.append({"screen": "Ahrefs: niet onderzocht",
                       "say": "Een betrouwbare zoekwoordpositie kon ik nog niet controleren."})
    if competitor is not None:
        if (not isinstance(competitor, dict) or competitor.get("verified") is not True or
                competitor.get("same_service_and_region") is not True):
            raise ValueError("competitor_not_verified")
        target = competitor.get("source_url", "")
        if _host(target) == _host(website):
            raise ValueError("competitor_not_independent")
        _date(competitor.get("checked_at"))
        claim = _single_line(competitor.get("observed", ""), 260, "competitor_observation")
        scenes.append({"screen": target,
                       "say": (f"Bij deze vergelijkbare aanbieder zie je {claim}. "
                               "Dit is een bruikbaar idee, maar verklaart niet automatisch "
                               "een eventueel verschil in Google-posities.")})
    scenes.append({"screen": "Voor/na-concept (niet de live website)",
                   "say": "Deze verbeteringen zijn voorstellen. Resultaten kunnen pas na uitvoering en meting worden beoordeeld."})
    return {"scenes": scenes, "kind": "screen_script_outline",
            "status": "owner_review_required"}