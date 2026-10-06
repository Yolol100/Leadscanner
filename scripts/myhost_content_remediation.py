from __future__ import annotations

import argparse
import json
import re
import unicodedata
from copy import deepcopy
from email.utils import getaddresses
from pathlib import Path

import requests

from extract_public_contacts import (
    EMAIL_RE,
    _visible_text,
    detect_language,
    discover_contact_links,
    extract_emails,
    fetch_html,
    inspect_candidate,
    normalize_domain,
    valid_email,
)
from myhost_draft import (
    connect_imap,
    create_drafts,
    fetch_message,
    find_drafts_folder,
    find_message_ids,
    normalize_text,
    plain_body,
)
from myhost_remove_duplicate_draft import remove_growth_draft
from prepare_growth_batch import (
    build_template,
    clean_company,
    observation_is_low_signal,
    short_company_name,
    stable_lead_id,
    subject_for_company,
    subject_label_for_company,
)

LEAD_RE = re.compile(r"^growth-[0-9a-f]{20}$")
BATCH_RE = re.compile(r"^batch-[0-9]{3,6}$")
MAX_BATCH = 100


def _single_recipient(msg) -> str:
    addresses = [
        address.strip()
        for _, address in getaddresses([str(msg.get("To", ""))])
        if address.strip()
    ]
    if len(addresses) != 1:
        raise RuntimeError("Current draft must have exactly one recipient")
    return addresses[0]


def _as_list(value, label: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def validate_request(request: dict) -> dict:
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    allowed = {
        "batch_id",
        "source_archive_artifact_id",
        "source_artifact_ids",
        "audited_lead_ids",
        "rewrites",
        "replacements",
        "holds",
        "refresh_verified_source_rows",
        "research_unresolved",
        "audit_only",
    }
    unknown = set(request) - allowed
    if unknown:
        raise ValueError(f"unsupported request fields: {sorted(unknown)}")

    batch_id = str(request.get("batch_id") or "").strip()
    if not BATCH_RE.fullmatch(batch_id):
        raise ValueError("batch_id must match batch-NNN")
    archive_id = int(request.get("source_archive_artifact_id") or 0)
    if archive_id <= 0:
        raise ValueError("source_archive_artifact_id must be positive")

    source_artifact_ids = [
        int(x)
        for x in _as_list(
            request.get("source_artifact_ids"), "source_artifact_ids"
        )
    ]
    if not 1 <= len(source_artifact_ids) <= 20 or any(
        x <= 0 for x in source_artifact_ids
    ):
        raise ValueError("source_artifact_ids must contain 1-20 positive IDs")
    if len(set(source_artifact_ids)) != len(source_artifact_ids):
        raise ValueError("source_artifact_ids must be unique")

    audited = [
        str(x).strip()
        for x in _as_list(request.get("audited_lead_ids"), "audited_lead_ids")
    ]
    if not 1 <= len(audited) <= MAX_BATCH or len(set(audited)) != len(audited):
        raise ValueError(
            f"audited_lead_ids must contain 1-{MAX_BATCH} unique lead IDs"
        )
    if any(not LEAD_RE.fullmatch(x) for x in audited):
        raise ValueError("audited_lead_ids contains an invalid lead ID")

    rewrites = request.get("rewrites") or {}
    replacements = request.get("replacements") or {}
    refresh_verified = request.get(
        "refresh_verified_source_rows", False
    )
    if not isinstance(refresh_verified, bool):
        raise ValueError(
            "refresh_verified_source_rows must be boolean"
        )
    research_unresolved = request.get(
        "research_unresolved", False
    )
    if not isinstance(research_unresolved, bool):
        raise ValueError(
            "research_unresolved must be boolean"
        )
    audit_only = request.get("audit_only", False)
    if not isinstance(audit_only, bool):
        raise ValueError("audit_only must be boolean")
    holds = [
        str(x).strip()
        for x in _as_list(request.get("holds") or [], "holds")
    ]
    if not isinstance(rewrites, dict) or not isinstance(replacements, dict):
        raise ValueError("rewrites and replacements must be objects")
    if len(set(holds)) != len(holds) or any(
        not LEAD_RE.fullmatch(x) for x in holds
    ):
        raise ValueError("holds contains invalid or duplicate lead IDs")

    audited_set = set(audited)
    for label, values in (
        ("rewrites", rewrites),
        ("replacements", replacements),
    ):
        if any(
            not LEAD_RE.fullmatch(str(lead_id))
            for lead_id in values
        ):
            raise ValueError(f"{label} contains an invalid lead ID")
        if not set(values) <= audited_set:
            raise ValueError(
                f"{label} contains a lead outside audited_lead_ids"
            )
    if not set(holds) <= audited_set:
        raise ValueError("holds contains a lead outside audited_lead_ids")
    if (
        set(rewrites) & set(replacements)
        or set(rewrites) & set(holds)
        or set(replacements) & set(holds)
    ):
        raise ValueError(
            "rewrites, replacements and holds must not overlap"
        )

    for label, changes in (
        ("rewrites", rewrites),
        ("replacements", replacements),
    ):
        for lead_id, change in changes.items():
            if not isinstance(change, dict):
                raise ValueError(
                    f"{lead_id}: {label} entry must be an object"
                )
            observation = str(
                change.get("observation") or ""
            ).strip()
            source_url = str(
                change.get("source_url") or ""
            ).strip()
            terms = change.get("evidence_terms") or []
            if not observation or not source_url.startswith(
                ("http://", "https://")
            ):
                raise ValueError(
                    f"{lead_id}: observation/source_url missing"
                )
            if (
                not isinstance(terms, list)
                or not 1 <= len(terms) <= 8
                or any(not str(term).strip() for term in terms)
            ):
                raise ValueError(
                    f"{lead_id}: evidence_terms must contain 1-8 terms"
                )
            email_source_url = str(
                change.get("email_source_url") or ""
            ).strip()
            if email_source_url and not email_source_url.startswith(
                ("http://", "https://")
            ):
                raise ValueError(
                    f"{lead_id}: email_source_url must be http(s)"
                )
            language = str(
                change.get("language") or ""
            ).strip().casefold()
            if language and language not in {"nl", "en"}:
                raise ValueError(
                    f"{lead_id}: language must be nl or en"
                )
            if label == "replacements":
                email = str(
                    change.get("email") or ""
                ).strip().casefold()
                if not valid_email(email):
                    raise ValueError(
                        f"{lead_id}: invalid replacement email"
                    )
    return request


def load_source_rows(
    source_root: Path, artifact_ids: list[int]
) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for artifact_id in artifact_ids:
        path = (
            source_root
            / "rewrite"
            / str(artifact_id)
            / "growth-batch.json"
        )
        if not path.is_file():
            raise RuntimeError(
                f"source growth-batch missing for artifact {artifact_id}"
            )
        payload = json.loads(
            path.read_text(encoding="utf-8")
        )
        for row in payload.get("rows") or []:
            if row.get("status") != "review_draft":
                continue
            lead_id = str(
                row.get("lead_id") or ""
            ).strip()
            if not LEAD_RE.fullmatch(lead_id):
                raise RuntimeError(
                    f"source artifact {artifact_id} has invalid lead ID"
                )
            if lead_id in rows:
                raise RuntimeError(
                    f"duplicate source lead ID: {lead_id}"
                )
            rows[lead_id] = row
    return rows


def _normalize_for_match(value: str) -> str:
    text = unicodedata.normalize(
        "NFKD", str(value or "")
    )
    text = "".join(
        ch for ch in text
        if not unicodedata.combining(ch)
    )
    return re.sub(
        r"\s+", " ", text
    ).strip().casefold()


_REFRESH_STOPWORDS = {
    "aan", "and", "bij", "de", "een", "en", "for", "het",
    "in", "is", "met", "of", "on", "op", "the", "to", "van",
    "voor", "with", "your", "jullie", "zijn",
}


def _derive_refresh_evidence_terms(
    source_row: dict,
) -> list[str]:
    observation = _normalize_for_match(
        source_row.get("verified_observation")
    )
    company = _normalize_for_match(
        source_row.get("company")
    )
    observation_tokens = re.findall(
        r"[a-z0-9]+", observation
    )
    company_tokens = set(
        re.findall(r"[a-z0-9]+", company)
    )

    candidates: list[str] = []
    for token in observation_tokens:
        if (
            len(token) < 4
            or token in _REFRESH_STOPWORDS
            or token in company_tokens
            or token in candidates
        ):
            continue
        candidates.append(token)

    if not candidates:
        for token in observation_tokens:
            if (
                len(token) >= 4
                and token not in _REFRESH_STOPWORDS
                and token not in candidates
            ):
                candidates.append(token)

    if not candidates:
        raise RuntimeError(
            f"{source_row.get('lead_id')}: verified observation "
            "has no usable current-site evidence term"
        )
    return candidates[:2]


def _refresh_change_from_source(
    source_row: dict,
) -> dict:
    if (
        str(
            source_row.get(
                "verified_observation_source_type"
            )
            or ""
        ).strip()
        != "official_site"
    ):
        raise RuntimeError(
            f"{source_row.get('lead_id')}: refresh requires "
            "official_site observation provenance"
        )
    observation = str(
        source_row.get("verified_observation") or ""
    ).strip()
    source_url = str(
        source_row.get(
            "verified_observation_source_url"
        )
        or ""
    ).strip()
    if (
        not observation
        or not source_url.startswith(
            ("http://", "https://")
        )
    ):
        raise RuntimeError(
            f"{source_row.get('lead_id')}: refresh source "
            "observation/provenance is incomplete"
        )
    if observation_is_low_signal(
        str(source_row.get("company") or ""),
        observation,
    ):
        raise RuntimeError(
            f"{source_row.get('lead_id')}: stored official-site "
            "observation is low-signal and needs fresh research"
        )
    return {
        "observation": observation,
        "source_url": source_url,
        "evidence_terms": (
            _derive_refresh_evidence_terms(
                source_row
            )
        ),
    }


def validate_online_evidence(
    source_row: dict,
    change: dict,
    *,
    require_email: bool,
) -> dict:
    source_url = str(
        change["source_url"]
    ).strip()
    source_domain = normalize_domain(source_url)
    provider_type = str(
        (change or {}).get(
            "email_source_type"
        )
        or ""
    ).strip()
    provider_ref = str(
        (change or {}).get(
            "email_source_ref"
        )
        or ""
    ).strip()
    if (
        provider_type
        in {
            "overture",
            "google_maps",
            "google_maps_targeted_fallback",
        }
        and provider_ref
    ):
        return {
            "email": expected_email,
            "source_url": None,
            "source_ref": provider_ref,
            "source_type": provider_type,
        }

    expected_domain = normalize_domain(
        source_row.get("official_domain_hint")
        or source_row.get("website")
    )
    if (
        not source_domain
        or not expected_domain
        or source_domain != expected_domain
    ):
        raise RuntimeError(
            f"{source_row['lead_id']}: official source domain mismatch: "
            f"{source_domain} != {expected_domain}"
        )

    session = requests.Session()
    html, final_url, status = fetch_html(
        session, source_url
    )
    if (
        not html
        or not final_url
        or not (status and 200 <= status < 400)
    ):
        raise RuntimeError(
            f"{source_row['lead_id']}: official source could not be read"
        )
    if normalize_domain(final_url) != expected_domain:
        raise RuntimeError(
            f"{source_row['lead_id']}: official source redirected off-domain"
        )

    page = _normalize_for_match(
        _visible_text(html)
    )
    source_language = str(
        source_row.get("language") or "nl"
    ).strip().casefold()
    if source_language not in {"nl", "en"}:
        source_language = "nl"
    detected_language, language_source = detect_language(
        html,
        default=source_language,
    )
    expected_email_term = (
        str(change.get("email") or "").strip().casefold()
        if require_email
        else ""
    )
    missing = [
        term
        for term in change.get("evidence_terms") or []
        if str(term).strip().casefold() != expected_email_term
        and _normalize_for_match(term) not in page
    ]
    if missing:
        raise RuntimeError(
            f"{source_row['lead_id']}: official source is missing "
            f"evidence term {missing[0]!r}"
        )

    email_found = None
    email_source_final = None
    if require_email:
        expected_email = str(
            change.get("email") or ""
        ).strip().casefold()
        email_source_url = str(
            change.get("email_source_url")
            or source_url
        ).strip()
        if (
            normalize_domain(email_source_url)
            != expected_domain
        ):
            raise RuntimeError(
                f"{source_row['lead_id']}: replacement email source domain mismatch"
            )
        email_html = html
        email_status = status
        email_source_final = final_url
        if email_source_url != source_url:
            (
                email_html,
                email_source_final,
                email_status,
            ) = fetch_html(
                session, email_source_url
            )
            if (
                not email_html
                or not email_source_final
                or not (
                    email_status
                    and 200 <= email_status < 400
                )
                or normalize_domain(
                    email_source_final
                )
                != expected_domain
            ):
                raise RuntimeError(
                    f"{source_row['lead_id']}: replacement email source could not be read"
                )
        emails = _emails_in_source(email_html)
        if expected_email not in emails:
            raise RuntimeError(
                f"{source_row['lead_id']}: replacement email is not "
                "present in official source data"
            )
        email_found = expected_email

    return {
        "source_url": final_url,
        "email_source_url": email_source_final,
        "http_status": status,
        "evidence_terms": len(
            change.get("evidence_terms") or []
        ),
        "replacement_email_verified": bool(
            email_found
        ),
        "language": detected_language,
        "language_source": language_source,
    }



def _emails_in_source(html: str) -> set[str]:
    emails = {
        email.casefold()
        for email in extract_emails(html)
    }
    emails.update(
        {
            match.casefold().strip(".,;:()[]<>")
            for match in EMAIL_RE.findall(html or "")
            if valid_email(match)
        }
    )
    return emails


def verify_existing_email(
    source_row: dict,
    change: dict | None = None,
) -> dict:
    lead_id = str(source_row.get("lead_id") or "").strip()
    expected_email = str(
        source_row.get("email") or ""
    ).strip().casefold()
    if not valid_email(expected_email):
        raise RuntimeError(
            f"{lead_id}: current source email is invalid"
        )

    expected_domain = normalize_domain(
        source_row.get("official_domain_hint")
        or source_row.get("website")
    )
    if not expected_domain:
        raise RuntimeError(
            f"{lead_id}: official domain is missing for current email verification"
        )

    seed_urls: list[str] = []
    researched_email_source = str(
        (change or {}).get("email_source_url") or ""
    ).strip()
    for value in (
        [researched_email_source]
        + list(source_row.get("email_source_urls") or [])
        + [
            source_row.get(
                "verified_observation_source_url"
            ),
            source_row.get("website"),
        ]
    ):
        url = str(value or "").strip()
        if (
            url.startswith(("http://", "https://"))
            and normalize_domain(url) == expected_domain
            and url not in seed_urls
        ):
            seed_urls.append(url)

    if not seed_urls:
        raise RuntimeError(
            f"{lead_id}: no first-party URL is available for current email verification"
        )

    session = requests.Session()
    checked_urls: set[str] = set()
    pending_urls = list(seed_urls)
    checked_pages = 0
    while pending_urls and checked_pages < 3:
        source_url = pending_urls.pop(0)
        if source_url in checked_urls:
            continue
        html, final_url, status = fetch_html(
            session, source_url
        )
        checked_urls.add(source_url)
        if (
            not html
            or not final_url
            or not (status and 200 <= status < 400)
            or normalize_domain(final_url)
            != expected_domain
        ):
            continue

        checked_pages += 1
        checked_urls.add(final_url)
        if expected_email in _emails_in_source(html):
            return {
                "email": expected_email,
                "source_url": final_url,
                "http_status": status,
                "source_type": "official_site",
            }

        for link in discover_contact_links(
            html,
            final_url,
            expected_domain,
        ):
            if (
                link not in checked_urls
                and link not in pending_urls
            ):
                pending_urls.append(link)

    raise RuntimeError(
        f"{lead_id}: current email is not verified on the current official site"
    )


def _research_unresolved_source(
    source_row: dict,
) -> dict:
    lead_id = str(
        source_row.get("lead_id") or ""
    ).strip()
    current_email = str(
        source_row.get("email") or ""
    ).strip().casefold()
    source_types = list(
        source_row.get("email_source_types")
        or []
    )
    source_refs = list(
        source_row.get("email_source_refs")
        or []
    )
    fallback_candidates = []
    fallback_type = (
        str(source_types[0] or "").strip()
        if source_types
        else ""
    )
    fallback_ref = (
        str(source_refs[0] or "").strip()
        if source_refs
        else ""
    )
    if (
        valid_email(current_email)
        and fallback_type
        in {
            "overture",
            "google_maps",
            "google_maps_targeted_fallback",
        }
        and fallback_ref
    ):
        fallback_candidates.append(
            {
                "email": current_email,
                "source": fallback_type,
            }
        )

    result = inspect_candidate(
        {
            "website_hint": (
                source_row.get("website")
                or source_row.get(
                    "official_domain_hint"
                )
            ),
            "name_hint": source_row.get(
                "company"
            ),
            "category_hint": source_row.get(
                "category_hint"
            ),
            "discovery_email_candidates": (
                fallback_candidates
            ),
            "overture_id": (
                fallback_ref
                if fallback_type == "overture"
                else None
            ),
            "maps_link_hint": (
                fallback_ref
                if fallback_type.startswith(
                    "google_maps"
                )
                else None
            ),
        }
    )
    if result.get("excluded_competitor"):
        return {
            "status": "hold",
            "reason": (
                "current official site matches "
                "excluded competitor scope"
            ),
        }

    observation = str(
        result.get("verified_observation")
        or ""
    ).strip()
    observation_url = str(
        result.get(
            "verified_observation_source_url"
        )
        or ""
    ).strip()
    if (
        not observation
        or not observation_url.startswith(
            ("http://", "https://")
        )
        or result.get(
            "verified_observation_source_type"
        )
        != "official_site"
    ):
        return {
            "status": "hold",
            "reason": (
                "no current first-party fact "
                "could be verified"
            ),
        }
    if observation_is_low_signal(
        str(source_row.get("company") or ""),
        observation,
    ):
        return {
            "status": "hold",
            "reason": (
                "current first-party observation "
                "is low-signal"
            ),
        }

    emails = [
        str(email or "").strip().casefold()
        for email in (
            result.get(
                "public_business_emails"
            )
            or []
        )
    ]
    source_urls = [
        str(url or "").strip()
        for url in (
            result.get("email_source_urls")
            or []
        )
    ]
    source_types = [
        str(value or "").strip()
        for value in (
            result.get("email_source_types")
            or []
        )
    ]
    source_refs = [
        str(value or "").strip()
        for value in (
            result.get("email_source_refs")
            or []
        )
    ]
    verified_email_rows = []
    for index, email in enumerate(emails):
        source_type = (
            source_types[index]
            if index < len(source_types)
            else ""
        )
        source_url = (
            source_urls[index]
            if index < len(source_urls)
            else ""
        )
        source_ref = (
            source_refs[index]
            if index < len(source_refs)
            else ""
        )
        if (
            source_type == "official_site"
            and source_url.startswith(
                ("http://", "https://")
            )
            and valid_email(email)
        ):
            verified_email_rows.append(
                (
                    email,
                    source_type,
                    source_url,
                )
            )
        elif (
            source_type
            in {
                "overture",
                "google_maps",
                "google_maps_targeted_fallback",
            }
            and source_ref
            and valid_email(email)
        ):
            verified_email_rows.append(
                (
                    email,
                    source_type,
                    source_ref,
                )
            )
    if not verified_email_rows:
        return {
            "status": "hold",
            "reason": (
                "no verified public business "
                "email could be resolved"
            ),
        }

    terms = _derive_refresh_evidence_terms(
        {
            **source_row,
            "verified_observation": (
                observation
            ),
        }
    )
    language = str(
        result.get("language") or ""
    ).strip().casefold()
    if language not in {"nl", "en"}:
        language = str(
            source_row.get("language")
            or "nl"
        ).strip().casefold()
    if language not in {"nl", "en"}:
        language = "nl"

    for (
        email,
        email_source_type,
        email_source_ref,
    ) in verified_email_rows:
        if email == current_email:
            change = {
                "observation": observation,
                "source_url": observation_url,
                "evidence_terms": terms,
                "language": language,
                "email_source_type": (
                    email_source_type
                ),
                "email_source_ref": (
                    email_source_ref
                ),
            }
            if (
                email_source_type
                == "official_site"
            ):
                change["email_source_url"] = (
                    email_source_ref
                )
            return {
                "status": "rewrite",
                "change": change,
            }

    (
        replacement_email,
        email_source_type,
        email_source_ref,
    ) = verified_email_rows[0]
    change = {
        "email": replacement_email,
        "observation": observation,
        "source_url": observation_url,
        "evidence_terms": terms,
        "language": language,
        "email_source_type": (
            email_source_type
        ),
        "email_source_ref": (
            email_source_ref
        ),
    }
    if email_source_type == "official_site":
        change["email_source_url"] = (
            email_source_ref
        )
    return {
        "status": "replacement",
        "change": change,
    }


def build_corrected_row(
    source_row: dict,
    change: dict,
    *,
    price_min: int,
    price_max: int,
    replacement: bool,
) -> dict:
    row = deepcopy(source_row)
    requested_language = str(
        change.get("language") or ""
    ).strip().casefold()
    language = requested_language or str(
        row.get("language") or "nl"
    ).casefold()
    if language not in {"nl", "en"}:
        raise RuntimeError(
            f"{row.get('lead_id')}: unsupported language"
        )
    if requested_language:
        row["language"] = language
        row["language_source"] = "official_site_manual_override"
    company = clean_company(
        row.get("company"), language
    )
    observation = str(
        change.get("observation") or ""
    ).strip()
    source_url = str(
        change.get("source_url") or ""
    ).strip()

    if not replacement:
        email_source_url = str(
            change.get("email_source_url") or ""
        ).strip()
        email_source_type = str(
            change.get("email_source_type")
            or ""
        ).strip()
        email_source_ref = str(
            change.get("email_source_ref")
            or ""
        ).strip()
        if email_source_url:
            row["email_source_urls"] = [
                email_source_url
            ]
            row["email_source_types"] = [
                "official_site"
            ]
            row["email_source_refs"] = [
                email_source_url
            ]
        elif (
            email_source_type
            in {
                "overture",
                "google_maps",
                "google_maps_targeted_fallback",
            }
            and email_source_ref
        ):
            row["email_source_urls"] = []
            row["email_source_types"] = [
                email_source_type
            ]
            row["email_source_refs"] = [
                email_source_ref
            ]

    if replacement:
        email = str(
            change.get("email") or ""
        ).strip().casefold()
        if not valid_email(email):
            raise RuntimeError(
                f"{row.get('lead_id')}: invalid replacement email"
            )
        row["email"] = email
        row["lead_id"] = stable_lead_id(
            email, str(row.get("website") or "")
        )
        email_source_url = str(
            change.get("email_source_url")
            or source_url
        ).strip()
        row["email_source_urls"] = [
            email_source_url
        ]
        row["email_source_types"] = [
            "official_site"
        ]
        row["email_source_refs"] = [
            email_source_url
        ]

    row["verified_observation"] = observation
    row["verified_observation_source_url"] = (
        source_url
    )
    row["verified_observation_source_type"] = (
        "official_site"
    )
    row["copy_company_label"] = (
        short_company_name(company)
    )
    row["copy_subject_label"] = (
        subject_label_for_company(
            company, language
        )
    )
    row["subject"] = subject_for_company(
        company, language
    )
    row["body"] = build_template(
        company,
        language,
        observation,
        price_min=price_min,
        price_max=price_max,
        category_hint=(
            str(
                row.get("category_hint") or ""
            ).strip()
            or None
        ),
    )
    row["status"] = "review_draft"
    row["contact_basis_status"] = (
        "review_required"
    )
    return row


def current_version(msg) -> dict:
    return {
        "to": _single_recipient(msg),
        "subject": normalize_text(
            msg.get("Subject", "")
        ),
        "body": plain_body(msg),
        "review_status": normalize_text(
            msg.get(
                "X-Webactueel-Review-Required",
                "",
            )
        ),
    }


def _message_matches_row(msg, row: dict) -> bool:
    return (
        _single_recipient(msg).casefold()
        == str(
            row.get("email") or ""
        ).strip().casefold()
        and normalize_text(
            msg.get("Subject", "")
        )
        == normalize_text(
            row.get("subject")
        )
        and normalize_text(
            msg.get(
                "X-Webactueel-Review-Required",
                "",
            )
        )
        == "contact-basis"
        and plain_body(msg)
        == normalize_text(row.get("body"))
    )


def run(
    request: dict,
    source_root: Path,
    config_path: Path,
) -> dict:
    request = validate_request(request)
    source_rows = load_source_rows(
        source_root,
        [
            int(x)
            for x in request[
                "source_artifact_ids"
            ]
        ],
    )
    audited = list(
        request["audited_lead_ids"]
    )
    missing_source = [
        lead_id
        for lead_id in audited
        if lead_id not in source_rows
    ]
    if missing_source:
        raise RuntimeError(
            "audited lead missing from source archive: "
            f"{missing_source[0]}"
        )

    rewrites = dict(
        request.get("rewrites") or {}
    )
    replacements = dict(
        request.get("replacements") or {}
    )
    holds = set(
        request.get("holds") or []
    )
    audit_only = bool(
        request.get("audit_only", False)
    )
    needs_research: list[dict] = []
    auto_researched_count = 0
    auto_research_hold_count = 0
    auto_research_outcomes: list[dict] = []
    if request.get(
        "research_unresolved", False
    ):
        for lead_id in audited:
            if (
                lead_id in rewrites
                or lead_id in replacements
                or lead_id in holds
            ):
                continue
            outcome = (
                _research_unresolved_source(
                    source_rows[lead_id]
                )
            )
            auto_researched_count += 1
            status = str(
                outcome.get("status") or ""
            )
            if status == "rewrite":
                rewrites[lead_id] = dict(
                    outcome["change"]
                )
            elif status == "replacement":
                replacements[lead_id] = dict(
                    outcome["change"]
                )
            else:
                holds.add(lead_id)
                auto_research_hold_count += 1
            auto_research_outcomes.append(
                {
                    "lead_id": lead_id,
                    **outcome,
                }
            )

    auto_refreshed_count = 0
    refresh_failures: list[str] = []
    if request.get(
        "refresh_verified_source_rows", False
    ):
        for lead_id in audited:
            if (
                lead_id in rewrites
                or lead_id in replacements
                or lead_id in holds
            ):
                continue
            try:
                rewrites[lead_id] = (
                    _refresh_change_from_source(
                        source_rows[lead_id]
                    )
                )
                auto_refreshed_count += 1
            except Exception as exc:
                refresh_failures.append(
                    f"{lead_id}: {exc}"
                )
        if refresh_failures:
            if audit_only:
                for failure in refresh_failures:
                    lead_id, _, reason = failure.partition(": ")
                    needs_research.append(
                        {
                            "lead_id": lead_id,
                            "stage": "refresh_source",
                            "reason": reason,
                        }
                    )
            else:
                raise RuntimeError(
                    "verified-source refresh preflight failed for "
                    f"{len(refresh_failures)} lead(s): "
                    + " | ".join(refresh_failures)
                )

    online_evidence = {}
    evidence_failures: list[str] = []
    failed_evidence_leads: set[str] = set()
    for lead_id, change in rewrites.items():
        try:
            online_evidence[lead_id] = (
                validate_online_evidence(
                    source_rows[lead_id],
                    change,
                    require_email=False,
                )
            )
        except Exception as exc:
            failed_evidence_leads.add(lead_id)
            evidence_failures.append(
                f"{lead_id}: {exc}"
            )
    for lead_id, change in replacements.items():
        try:
            online_evidence[lead_id] = (
                validate_online_evidence(
                    source_rows[lead_id],
                    change,
                    require_email=True,
                )
            )
        except Exception as exc:
            failed_evidence_leads.add(lead_id)
            evidence_failures.append(
                f"{lead_id}: {exc}"
            )
    if evidence_failures:
        if audit_only:
            for failure in evidence_failures:
                lead_id, _, reason = failure.partition(": ")
                needs_research.append(
                    {
                        "lead_id": lead_id,
                        "stage": "official_evidence",
                        "reason": reason,
                    }
                )
            for lead_id in failed_evidence_leads:
                rewrites.pop(lead_id, None)
                replacements.pop(lead_id, None)
        else:
            raise RuntimeError(
                "official evidence preflight failed for "
                f"{len(evidence_failures)} lead(s): "
                + " | ".join(evidence_failures)
            )

    existing_email_evidence = {}
    email_failures: list[str] = []
    failed_email_leads: set[str] = set()
    for lead_id in list(rewrites):
        try:
            existing_email_evidence[lead_id] = (
                verify_existing_email(
                    source_rows[lead_id],
                    rewrites[lead_id],
                )
            )
        except Exception as exc:
            failed_email_leads.add(lead_id)
            email_failures.append(
                f"{lead_id}: {exc}"
            )
    if email_failures:
        if audit_only:
            for failure in email_failures:
                lead_id, _, reason = failure.partition(": ")
                needs_research.append(
                    {
                        "lead_id": lead_id,
                        "stage": "current_email",
                        "reason": reason,
                    }
                )
            for lead_id in failed_email_leads:
                rewrites.pop(lead_id, None)
                online_evidence.pop(
                    lead_id, None
                )
        else:
            raise RuntimeError(
                "current email verification failed for "
                f"{len(email_failures)} lead(s): "
                + " | ".join(email_failures)
            )

    for lead_id, change in rewrites.items():
        if (
            lead_id in online_evidence
            and not str(
                change.get("language") or ""
            ).strip()
        ):
            change["language"] = (
                online_evidence[lead_id][
                    "language"
                ]
            )
    for lead_id, change in replacements.items():
        if (
            lead_id in online_evidence
            and not str(
                change.get("language") or ""
            ).strip()
        ):
            change["language"] = (
                online_evidence[lead_id][
                    "language"
                ]
            )

    config = json.loads(
        config_path.read_text(
            encoding="utf-8"
        )
    )
    price = config["monthly_price_eur"]
    price_min = int(price["min"])
    price_max = int(price["max"])

    rewrite_rows: dict[str, dict] = {}
    replacement_rows: dict[str, dict] = {}
    template_failures: list[str] = []

    for lead_id, change in rewrites.items():
        try:
            rewrite_rows[lead_id] = build_corrected_row(
                source_rows[lead_id],
                change,
                price_min=price_min,
                price_max=price_max,
                replacement=False,
            )
        except Exception as exc:
            if not audit_only:
                raise
            template_failures.append(
                f"{lead_id}: {exc}"
            )

    for lead_id, change in replacements.items():
        try:
            replacement_rows[lead_id] = build_corrected_row(
                source_rows[lead_id],
                change,
                price_min=price_min,
                price_max=price_max,
                replacement=True,
            )
        except Exception as exc:
            if not audit_only:
                raise
            template_failures.append(
                f"{lead_id}: {exc}"
            )

    if template_failures:
        for failure in template_failures:
            lead_id, _, reason = failure.partition(": ")
            needs_research.append(
                {
                    "lead_id": lead_id,
                    "stage": "canonical_template",
                    "reason": reason,
                }
            )
    replacement_new_ids = [
        row["lead_id"]
        for row in replacement_rows.values()
    ]
    if len(
        set(replacement_new_ids)
    ) != len(replacement_new_ids):
        raise RuntimeError(
            "replacement lead IDs collide"
        )
    if set(replacement_new_ids) & set(audited):
        raise RuntimeError(
            "replacement lead ID collides with audited source lead"
        )

    if audit_only:
        ready_ids = (
            set(rewrite_rows)
            | set(replacement_rows)
        )
        research_ids = {
            str(item.get("lead_id") or "")
            for item in needs_research
        }
        assessed_ids = (
            ready_ids
            | research_ids
            | holds
        )
        unassessed = [
            lead_id
            for lead_id in audited
            if lead_id not in assessed_ids
        ]
        return {
            "schema_version": (
                "webactueel-growth-content-remediation/1.1"
            ),
            "batch_id": request["batch_id"],
            "audited_count": len(audited),
            "audit_only": True,
            "read_only": True,
            "online_evidence_count": len(
                online_evidence
            ),
            "current_email_verified_count": (
                len(existing_email_evidence)
                + len(replacement_rows)
            ),
            "refresh_verified_source_rows": bool(
                request.get(
                    "refresh_verified_source_rows",
                    False,
                )
            ),
            "auto_researched_count": (
                auto_researched_count
            ),
            "auto_research_hold_count": (
                auto_research_hold_count
            ),
            "auto_research_outcomes": (
                auto_research_outcomes
            ),
        "auto_researched_count": (
            auto_researched_count
        ),
        "auto_research_hold_count": (
            auto_research_hold_count
        ),
        "auto_research_outcomes": (
            auto_research_outcomes
        ),
            "auto_refreshed_count": (
                auto_refreshed_count
            ),
            "rewrite_count": len(rewrite_rows),
            "replacement_count": len(
                replacement_rows
            ),
            "canonical_ready_count": len(
                ready_ids
            ),
            "needs_research_count": len(
                research_ids
            ),
            "needs_research": needs_research,
            "hold_count": len(holds),
            "hold_lead_ids": sorted(holds),
            "unassessed_count": len(
                unassessed
            ),
            "unassessed_lead_ids": unassessed,
            "final_exact_changed_count": 0,
            "holds_readback_count": 0,
            "automatic_send": False,
            "send_capability": "unavailable",
            "readback": "not_applicable",
        }

    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        captured_versions: dict[str, dict] = {}
        already_replaced: set[str] = set()
        for lead_id in audited:
            ids = find_message_ids(
                client, folder, lead_id
            )
            if len(ids) == 1:
                msg = fetch_message(
                    client, ids[0]
                )
                if (
                    normalize_text(
                        msg.get(
                            "X-Webactueel-Lead-ID",
                            "",
                        )
                    )
                    != lead_id
                ):
                    raise RuntimeError(
                        f"{lead_id}: current draft identity mismatch"
                    )
                if (
                    normalize_text(
                        msg.get(
                            "X-Webactueel-Review-Required",
                            "",
                        )
                    )
                    != "contact-basis"
                ):
                    raise RuntimeError(
                        f"{lead_id}: current draft is not review_required"
                    )
                expected_email = str(
                    source_rows[lead_id].get(
                        "email"
                    )
                    or ""
                ).strip().casefold()
                if (
                    _single_recipient(
                        msg
                    ).casefold()
                    != expected_email
                ):
                    raise RuntimeError(
                        f"{lead_id}: current recipient differs from source identity"
                    )
                if lead_id in replacements:
                    captured_versions[
                        lead_id
                    ] = current_version(msg)
                continue

            if (
                lead_id in replacements
                and not ids
            ):
                new_row = replacement_rows[
                    lead_id
                ]
                new_ids = find_message_ids(
                    client,
                    folder,
                    new_row["lead_id"],
                )
                if (
                    len(new_ids) == 1
                    and _message_matches_row(
                        fetch_message(
                            client, new_ids[0]
                        ),
                        new_row,
                    )
                ):
                    already_replaced.add(
                        lead_id
                    )
                    continue
            raise RuntimeError(
                f"{lead_id}: expected exactly one current review draft, "
                f"found {len(ids)}"
            )
    finally:
        try:
            client.logout()
        except Exception:
            pass

    rewrite_result = {
        "eligible_count": 0,
        "replaced_count": 0,
        "existing_count": 0,
        "created_count": 0,
    }
    if rewrite_rows:
        rewrite_result = create_drafts(
            {"rows": list(rewrite_rows.values())},
            rewrite_existing_only=True,
        )
        if (
            rewrite_result.get(
                "created_count"
            )
            != 0
        ):
            raise RuntimeError(
                "same-ID remediation unexpectedly created a draft"
            )

    pending_replacement_rows = [
        row
        for old_id, row in replacement_rows.items()
        if old_id not in already_replaced
    ]
    replacement_result = {
        "eligible_count": 0,
        "replaced_count": 0,
        "existing_count": 0,
        "created_count": 0,
    }
    if pending_replacement_rows:
        replacement_result = create_drafts(
            {"rows": pending_replacement_rows},
            rewrite_existing_only=False,
        )
        if (
            replacement_result.get(
                "review_required_count"
            )
            != len(
                pending_replacement_rows
            )
        ):
            raise RuntimeError(
                "replacement draft review-required count mismatch"
            )

    removed_old = 0
    for old_id in replacements:
        if old_id in already_replaced:
            continue
        result = remove_growth_draft(
            old_id,
            [captured_versions[old_id]],
        )
        removed_old += int(
            result.get("removed_count") or 0
        )
        if result.get("final_count") != 0:
            raise RuntimeError(
                f"{old_id}: stale draft removal readback failed"
            )

    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        final_exact = 0
        unchanged_ok = 0
        holds_ok = 0
        for lead_id in audited:
            if lead_id in replacement_rows:
                new_row = replacement_rows[
                    lead_id
                ]
                old_ids = find_message_ids(
                    client, folder, lead_id
                )
                new_ids = find_message_ids(
                    client,
                    folder,
                    new_row["lead_id"],
                )
                if (
                    old_ids
                    or len(new_ids) != 1
                    or not _message_matches_row(
                        fetch_message(
                            client,
                            new_ids[0],
                        ),
                        new_row,
                    )
                ):
                    raise RuntimeError(
                        f"{lead_id}: final replacement readback mismatch"
                    )
                final_exact += 1
            elif lead_id in rewrite_rows:
                ids = find_message_ids(
                    client, folder, lead_id
                )
                if (
                    len(ids) != 1
                    or not _message_matches_row(
                        fetch_message(
                            client, ids[0]
                        ),
                        rewrite_rows[
                            lead_id
                        ],
                    )
                ):
                    raise RuntimeError(
                        f"{lead_id}: final rewrite readback mismatch"
                    )
                final_exact += 1
            else:
                ids = find_message_ids(
                    client, folder, lead_id
                )
                if len(ids) != 1:
                    raise RuntimeError(
                        f"{lead_id}: unchanged/hold draft missing after remediation"
                    )
                msg = fetch_message(
                    client, ids[0]
                )
                if (
                    normalize_text(
                        msg.get(
                            "X-Webactueel-Review-Required",
                            "",
                        )
                    )
                    != "contact-basis"
                ):
                    raise RuntimeError(
                        f"{lead_id}: unchanged/hold review status changed"
                    )
                if lead_id in holds:
                    holds_ok += 1
                else:
                    unchanged_ok += 1
    finally:
        try:
            client.logout()
        except Exception:
            pass

    return {
        "schema_version": (
            "webactueel-growth-content-remediation/1.0"
        ),
        "batch_id": request["batch_id"],
        "audited_count": len(audited),
        "audit_only": False,
        "read_only": False,
        "online_evidence_count": len(
            online_evidence
        ),
        "current_email_verified_count": (
            len(existing_email_evidence)
            + len(replacement_rows)
        ),
        "refresh_verified_source_rows": bool(
            request.get(
                "refresh_verified_source_rows",
                False,
            )
        ),
        "auto_refreshed_count": (
            auto_refreshed_count
        ),
        "rewrite_count": len(rewrite_rows),
        "replacement_count": len(
            replacement_rows
        ),
        "already_replaced_count": len(
            already_replaced
        ),
        "removed_old_count": removed_old,
        "hold_count": len(holds),
        "unchanged_verified_count": (
            unchanged_ok
        ),
        "final_exact_changed_count": (
            final_exact
        ),
        "holds_readback_count": holds_ok,
        "created_replacement_count": int(
            replacement_result.get(
                "created_count"
            )
            or 0
        ),
        "replaced_same_id_count": int(
            rewrite_result.get(
                "replaced_count"
            )
            or 0
        ),
        "existing_same_id_count": int(
            rewrite_result.get(
                "existing_count"
            )
            or 0
        ),
        "automatic_send": False,
        "send_capability": "unavailable",
        "readback": "exact",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--request", required=True
    )
    parser.add_argument(
        "--source-root", required=True
    )
    parser.add_argument(
        "--config", required=True
    )
    parser.add_argument(
        "--report", required=True
    )
    args = parser.parse_args()

    request = json.loads(
        Path(args.request).read_text(
            encoding="utf-8"
        )
    )
    result = run(
        request,
        Path(args.source_root),
        Path(args.config),
    )
    report = Path(args.report)
    report.parent.mkdir(
        parents=True, exist_ok=True
    )
    report.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        "CONTENT_REMEDIATION=green "
        f"batch={result['batch_id']} "
        f"audited={result['audited_count']} "
        f"rewrites={result['rewrite_count']} "
        f"replacements={result['replacement_count']} "
        f"holds={result['hold_count']} "
        f"exact={result['final_exact_changed_count']} "
        f"audit_only={str(bool(result.get('audit_only'))).lower()} "
        "automatic_send=false "
        "send_capability=unavailable"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
