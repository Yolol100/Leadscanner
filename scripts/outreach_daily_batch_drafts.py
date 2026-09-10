from __future__ import annotations

import argparse
import hashlib
import imaplib
import json
import os
import re
import ssl
import sys
import time
from dataclasses import dataclass
from email.policy import SMTP
from pathlib import Path
from typing import Mapping, Sequence

from outreach_copy_preflight import initial_copy_errors
from outreach_imap_draft import build_draft_message, detect_drafts_folder
from outreach_mailboxes import enabled_mailboxes, load_mailboxes_from_env
from outreach_sender import build_sheets_service, get_values, rows_from_values
from prospect_contact_enrichment import aligned_domain
from prospect_discovery import SOURCE_HEADERS, host_key, hosts_related, truthy
from prospect_target_policy import canonical_country

QUEUE_SHEET = "OutreachQueue"
LEAD_SHEET = "Leadlijst"
SUPPRESSION_SHEET = "Suppression"
CONTACT_SHEET = "ContactCandidates"
QUALIFICATION_SHEET = "AgentProspectQualifications"
CANDIDATE_SHEET = "ProspectCandidates"
SOURCE_SHEET = "ProspectSources"

COPY_CONTRACT = "evidence_personalized_v13_5"
PREPARE_AUTOMATION = "agent_sales_prepare_v2"
ALLOWED_QUEUE_STATUSES = {"prepared", "manual_review", "approved"}
ALLOWED_DRAFT_COMPLIANCE = {"manual_review", "approved"}
ALLOWED_LEAD_STATUSES = {"gevonden", "found", "prepared"}
TERMINAL_QUEUE_FIELDS = (
    "sent_at", "followup_sent_at", "message_id", "followup_message_id", "reply_at", "bounce_at",
)
ROLE_MISMATCH_LOCAL_PARTS = {
    "hr", "humanresources", "human-resources", "careers", "career", "jobs", "job", "recruiting",
    "recruitment", "recruiter", "privacy", "legal", "billing", "payroll", "press", "media",
    "webmaster", "abuse", "postmaster",
}
LOW_VALUE_ANCHORS = {
    "home", "homepage", "our services", "services", "our products", "products", "what we do", "learn more",
    "read more", "click here", "contact", "contact us", "get in touch", "request a quote", "get a quote",
    "quote", "free quote", "estimate", "pricing", "about", "about us", "company", "welcome", "new website",
    "presenting our new website", "void 0",
}
NAV_TOKENS = {
    "facebook", "linkedin", "instagram", "youtube", "twitter", "x", "phone", "hours", "menu", "search",
    "login", "privacy", "terms", "cookies", "home", "contact",
}
GENERIC_PROCESS_ANCHORS = {
    "book", "book now", "booking", "appointment", "appointments", "schedule", "contact", "contact us",
    "request a quote", "get a quote", "quote", "free quote", "estimate", "pricing", "shop", "shop now",
    "store", "products", "product", "cart", "checkout", "support", "help", "faq", "customer service",
    "returns", "reviews", "testimonials",
}
AGENT_HINTS = {
    "front_desk_sales": ("book", "booking", "appointment", "schedule", "reserve", "consultation", "contact"),
    "quote_intake": ("quote", "estimate", "pricing", "price", "intake"),
    "commerce": ("shop", "store", "product", "collection", "catalog", "cart", "checkout", "buy"),
    "customer_support": ("support", "help", "faq", "service", "return", "shipping", "warranty", "order"),
    "review_concierge": ("review", "testimonial", "customer stor", "rating"),
}
APPROVED_AGENTS = frozenset(AGENT_HINTS)
SAFE_RUN_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
DOMAIN_LIKE_RE = re.compile(r"(?i)\b[a-z0-9-]+\.(?:com|net|org|io|co|nl|de|fr|be|uk|us)\b")
CERT_ONLY_RE = re.compile(r"(?i)^(?:(?:iso|as|iatf|nadcap)[\s0-9:.-]*|certified|certification|quality certified)+$")


@dataclass(frozen=True)
class Candidate:
    lead_id: str
    company: str
    website: str
    email: str
    subject: str
    body: str
    country: str
    anchor: str
    score: int


@dataclass(frozen=True)
class DraftReceipt:
    lead_id: str
    company: str
    email: str
    test_id: str
    folder: str
    readback_count: int
    action: str


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _text(value).casefold()).strip()


def _email(value: object) -> str:
    return _text(value).casefold()


def _parse_meta(value: object) -> dict[str, object]:
    text = str(value or "")
    if not text.startswith("agent_offer:"):
        return {}
    try:
        payload = json.loads(text.split(":", 1)[1])
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _source_enabled_approved(row: Mapping[str, object]) -> bool:
    return bool(row and truthy(row.get("approved")) and truthy(row.get("enabled", "true")))


def _role_is_usable(address: str) -> bool:
    address = _email(address)
    if "@" not in address:
        return False
    local = address.rsplit("@", 1)[0].replace("_", "-").casefold()
    compact = local.replace("-", "")
    blocked = {item.replace("-", "") for item in ROLE_MISMATCH_LOCAL_PARTS}
    if local in ROLE_MISMATCH_LOCAL_PARTS or compact in blocked:
        return False
    if compact.endswith("hr") and len(compact) <= 32:
        return False
    return True


def strong_anchor(anchor: str) -> bool:
    raw = _text(anchor).strip(" -|:;,.")
    norm = _norm(raw)
    if not raw or len(raw) < 3 or len(raw) > 90:
        return False
    if norm in LOW_VALUE_ANCHORS or norm in GENERIC_PROCESS_ANCHORS:
        return False
    if DOMAIN_LIKE_RE.search(raw) or "@" in raw or "{{" in raw or "}}" in raw:
        return False
    if re.search(r"(?i)\b(?:ignore previous|system prompt|developer message|jailbreak|prompt injection|do not trust)\b", raw):
        return False
    words = norm.split()
    if len(words) < 2 or len(words) > 10:
        return False
    nav_count = sum(1 for word in words if word in NAV_TOKENS)
    if nav_count >= max(2, (len(words) + 1) // 2):
        return False
    if CERT_ONLY_RE.fullmatch(norm):
        return False
    if "new website" in norm or "presenting our new website" in norm:
        return False
    return True


def _agent_process_is_supported(agent_type: str, process_label: str) -> bool:
    value = _norm(process_label)
    return bool(value and any(hint in value for hint in AGENT_HINTS.get(agent_type, ())))


def stable_test_id(lead_id: str) -> str:
    digest = hashlib.sha256(_text(lead_id).encode("utf-8")).hexdigest()[:24]
    return f"daily-lead-draft-{digest}"


def _score(value: object) -> int:
    try:
        return int(str(value or "0").strip() or "0")
    except ValueError:
        return 0


def _rows(values: list[list[object]]) -> tuple[list[str], list[dict[str, str]]]:
    headers, rows = rows_from_values(values)
    return headers, [{str(k): str(v or "") for k, v in row.items()} for row in rows]


def _index(rows: Sequence[Mapping[str, object]], key: str) -> dict[str, Mapping[str, object]]:
    output: dict[str, Mapping[str, object]] = {}
    for row in rows:
        value = _text(row.get(key))
        if value:
            output[value] = row
    return output


def _lead_status_by_domain(rows: Sequence[Mapping[str, object]]) -> dict[str, set[str]]:
    output: dict[str, set[str]] = {}
    for row in rows:
        domain = host_key(_text(row.get("Website") or row.get("website")))
        if domain:
            output.setdefault(domain, set()).add(_text(row.get("Status") or row.get("status")).casefold())
    return output


def _suppression_sets(rows: Sequence[Mapping[str, object]]) -> tuple[set[str], set[str]]:
    emails: set[str] = set()
    domains: set[str] = set()
    for row in rows:
        address = _email(row.get("email"))
        domain = _text(row.get("domain")).casefold().strip(".")
        if address:
            emails.add(address)
        if domain:
            domains.add(domain)
    return emails, domains


def candidate_errors(
    queue_row: Mapping[str, object], *, agent_type: str, country: str,
    candidate: Mapping[str, object], qualification: Mapping[str, object], contact: Mapping[str, object],
    source: Mapping[str, object], lead_statuses: set[str], suppressed_emails: set[str], suppressed_domains: set[str],
) -> list[str]:
    errors: list[str] = []
    lead_id = _text(queue_row.get("lead_id"))
    website = _text(queue_row.get("website"))
    website_host = host_key(website)
    recipient = _email(queue_row.get("email"))
    recipient_domain = recipient.rsplit("@", 1)[1] if "@" in recipient else ""
    queue_country = canonical_country(_text(queue_row.get("country")))

    if not lead_id or not website_host:
        errors.append("missing stable lead identity or website")
    if _text(queue_row.get("status")).casefold() not in ALLOWED_QUEUE_STATUSES:
        errors.append("queue status is not draft-eligible")
    if _text(queue_row.get("verification_status")).casefold() != "official_site_ready":
        errors.append("queue verification is not official_site_ready")
    if _text(queue_row.get("opt_out_mode")).casefold() != "reply_optout":
        errors.append("queue opt-out mode is not reply_optout")
    expected_sender = _email(os.getenv("OUTREACH_SENDER_EMAIL", "info@andrewbaeten.nl"))
    if _email(queue_row.get("sender_email")) and _email(queue_row.get("sender_email")) != expected_sender:
        errors.append("queue sender does not match configured mailbox")
    if _text(queue_row.get("compliance_status")).casefold() not in ALLOWED_DRAFT_COMPLIANCE:
        errors.append("draft route requires manual_review or approved compliance state")
    if _text(queue_row.get("stage")) not in {"", "1"}:
        errors.append("only initial stage may be drafted")
    if any(_text(queue_row.get(field)) for field in TERMINAL_QUEUE_FIELDS):
        errors.append("queue row has terminal send/reply/bounce evidence")
    if queue_country != canonical_country(country):
        errors.append("queue country is outside selected campaign jurisdiction")
    if not recipient or "@" not in recipient:
        errors.append("recipient email is invalid")
    elif recipient in suppressed_emails or recipient_domain in suppressed_domains:
        errors.append("recipient or domain is suppressed")
    if recipient and not _role_is_usable(recipient):
        errors.append("recipient mailbox role is not suitable for cold business outreach")
    if recipient_domain and not aligned_domain(website, recipient_domain):
        errors.append("recipient domain is not aligned to official website")

    if not candidate or _text(candidate.get("candidate_id")) != lead_id:
        errors.append("candidate identity is missing")
    else:
        if _text(candidate.get("status")).casefold() != "qualified":
            errors.append("candidate is not qualified")
        if canonical_country(_text(candidate.get("country"))) != queue_country:
            errors.append("candidate country conflicts with queue")
        if host_key(_text(candidate.get("website"))) != website_host:
            errors.append("candidate website conflicts with queue")

    if not qualification or _text(qualification.get("candidate_id")) != lead_id:
        errors.append("qualification evidence is missing")
    else:
        if _text(qualification.get("status")).casefold() != "qualified":
            errors.append("qualification status is not qualified")
        if _text(qualification.get("tier")).upper() != "A":
            errors.append("qualification tier is not A")
        if _text(qualification.get("offer_family")).casefold() != "ai_agent":
            errors.append("qualification offer family is not ai_agent")
        if _text(qualification.get("agent_type")).casefold() != agent_type:
            errors.append("qualification agent does not match campaign")
        if _score(qualification.get("customer_potential")) < 8:
            errors.append("customer potential is below A threshold")

    if not contact or _text(contact.get("candidate_id")) != lead_id:
        errors.append("contact evidence is missing")
    else:
        if _text(contact.get("status")).casefold() != "ready":
            errors.append("contact is not ready")
        if _text(contact.get("domain_alignment")).casefold() != "aligned":
            errors.append("contact domain alignment is not proven")
        if _text(contact.get("mx_status")).casefold() != "present":
            errors.append("contact MX presence is not proven")
        if _email(contact.get("email")) != recipient:
            errors.append("contact email conflicts with queue")
        evidence_host = host_key(_text(contact.get("source_url")))
        if not evidence_host or not hosts_related(website_host, evidence_host):
            errors.append("contact source is not on the official site")

    if not _source_enabled_approved(source):
        errors.append("prospect source is not approved and enabled")
    if not lead_statuses or not lead_statuses.issubset(ALLOWED_LEAD_STATUSES):
        errors.append("lead is not new-only in Leadlijst")

    meta = _parse_meta(queue_row.get("source"))
    if not meta:
        errors.append("agent_offer metadata is missing")
    else:
        if _text(meta.get("automation")) != PREPARE_AUTOMATION:
            errors.append("queue row was not prepared by the current v2 automation")
        if _text(meta.get("copy_contract")) != COPY_CONTRACT:
            errors.append("queue copy contract is stale")
        if _text(meta.get("offer_family")).casefold() != "ai_agent":
            errors.append("queue offer family is not ai_agent")
        if _text(meta.get("agent_type")).casefold() != agent_type:
            errors.append("queue agent does not match campaign")
        if _text(meta.get("campaign_target_agent_type")).casefold() != agent_type:
            errors.append("queue campaign target is not explicit or does not match")
        if _text(meta.get("qualification_tier")).upper() != "A" or _score(meta.get("customer_potential")) < 8:
            errors.append("queue metadata does not prove A-tier qualification")
        if _text(meta.get("value_asset_type")) != "process_flow" or _text(meta.get("value_asset_status")) != "concept_ready":
            errors.append("queue value asset is not concept_ready process_flow")
        anchor = _text(meta.get("personalization_anchor"))
        process_label = _text(meta.get("personalization_process_label"))
        fact = _text(meta.get("fact"))
        value = _text(meta.get("value_asset_summary"))
        evidence_url = _text(meta.get("personalization_evidence_url") or meta.get("evidence_url"))
        if not strong_anchor(anchor):
            errors.append("personalization anchor is weak or generic")
        if anchor and (anchor.casefold() not in fact.casefold() or anchor.casefold() not in value.casefold()):
            errors.append("personalization anchor is not carried by both fact and value")
        if not _agent_process_is_supported(agent_type, process_label):
            errors.append("personalization process label is not agent-relevant")
        evidence_host = host_key(evidence_url)
        if not evidence_host or not hosts_related(website_host, evidence_host):
            errors.append("personalization evidence is not same-site")

    errors.extend(f"copy: {item}" for item in initial_copy_errors(_text(queue_row.get("subject")), str(queue_row.get("body") or "")))
    return errors


def eligible_candidates(
    queue_rows: Sequence[Mapping[str, object]], *, agent_type: str, country: str,
    candidates: Sequence[Mapping[str, object]], qualifications: Sequence[Mapping[str, object]],
    contacts: Sequence[Mapping[str, object]], sources: Sequence[Mapping[str, object]],
    leads: Sequence[Mapping[str, object]], suppressions: Sequence[Mapping[str, object]],
) -> tuple[list[Candidate], dict[str, list[str]]]:
    if agent_type not in APPROVED_AGENTS:
        raise ValueError("agent_type must be one of the five net-new website-driven approved agents")
    campaign_country = canonical_country(country)
    if not campaign_country:
        raise ValueError("country must resolve to a canonical campaign jurisdiction")

    candidate_by_id = _index(candidates, "candidate_id")
    qualification_by_id = _index(qualifications, "candidate_id")
    contact_by_id = _index(contacts, "candidate_id")
    source_by_id = _index(sources, "source_id")
    lead_status_map = _lead_status_by_domain(leads)
    suppressed_emails, suppressed_domains = _suppression_sets(suppressions)

    accepted: list[Candidate] = []
    rejected: dict[str, list[str]] = {}
    seen_domains: set[str] = set()
    seen_emails: set[str] = set()
    seen_anchors: set[str] = set()

    for row in queue_rows:
        lead_id = _text(row.get("lead_id"))
        if not lead_id:
            continue
        candidate = candidate_by_id.get(lead_id, {})
        source = source_by_id.get(_text(candidate.get("source_id")), {}) if candidate else {}
        website = _text(row.get("website"))
        domain = host_key(website)
        errors = candidate_errors(
            row, agent_type=agent_type, country=campaign_country, candidate=candidate,
            qualification=qualification_by_id.get(lead_id, {}), contact=contact_by_id.get(lead_id, {}), source=source,
            lead_statuses=lead_status_map.get(domain, set()), suppressed_emails=suppressed_emails,
            suppressed_domains=suppressed_domains,
        )
        meta = _parse_meta(row.get("source"))
        anchor = _text(meta.get("personalization_anchor"))
        email = _email(row.get("email"))
        anchor_key = _norm(anchor)
        if domain in seen_domains:
            errors.append("duplicate domain within selected batch")
        if email in seen_emails:
            errors.append("duplicate email within selected batch")
        if anchor_key and anchor_key in seen_anchors:
            errors.append("duplicate personalization anchor within selected batch")
        if errors:
            rejected[lead_id] = errors
            continue
        score = max(_score(meta.get("customer_potential")), _score(qualification_by_id.get(lead_id, {}).get("customer_potential")))
        accepted.append(Candidate(
            lead_id=lead_id, company=_text(row.get("company")), website=website, email=email,
            subject=_text(row.get("subject")), body=str(row.get("body") or ""), country=campaign_country,
            anchor=anchor, score=score,
        ))
        seen_domains.add(domain)
        seen_emails.add(email)
        seen_anchors.add(anchor_key)

    accepted.sort(key=lambda item: (-item.score, item.lead_id))
    return accepted, rejected


def _search_ids(imap, test_id: str) -> tuple[str, ...]:
    status, data = imap.search(None, "HEADER", "X-Webactueel-Draft-Test-ID", f'"{test_id}"')
    if status != "OK":
        raise RuntimeError("IMAP draft search failed")
    if not data or not data[0]:
        return ()
    return tuple(part.decode("ascii", errors="replace") if isinstance(part, bytes) else str(part) for part in data[0].split())


def _open_imap(mailbox):
    context = ssl.create_default_context()
    imap = imaplib.IMAP4_SSL(mailbox.imap_host, mailbox.imap_port, ssl_context=context)
    status, _ = imap.login(mailbox.mail_user, mailbox.mail_password)
    if status != "OK":
        raise RuntimeError("IMAP authentication failed")
    status, listed = imap.list()
    if status != "OK":
        raise RuntimeError("IMAP LIST failed")
    folder = detect_drafts_folder(listed or (), explicit_folder=os.getenv("OUTREACH_DRAFT_FOLDER", ""))
    status, _ = imap.select(folder, readonly=True)
    if status != "OK":
        raise RuntimeError("failed to select Drafts folder")
    return imap, folder


def _append_or_readback(imap, folder: str, mailbox, item: Candidate) -> DraftReceipt:
    test_id = stable_test_id(item.lead_id)
    existing = _search_ids(imap, test_id)
    if len(existing) > 1:
        raise RuntimeError(f"duplicate stable draft id already exists for {item.lead_id}")
    if len(existing) == 1:
        return DraftReceipt(item.lead_id, item.company, item.email, test_id, folder, 1, "existing")

    body = item.body
    if canonical_country(item.country) == "US":
        from outreach_queue_imap_draft import inject_private_postal_for_draft
        body = inject_private_postal_for_draft({"country": item.country}, body)
    msg = build_draft_message(
        sender_name=mailbox.sender_name, sender_email=mailbox.sender_email, recipient=item.email,
        subject=item.subject, body=body, test_id=test_id,
    )
    status, _ = imap.append(folder, r"(\Draft)", imaplib.Time2Internaldate(time.time()), msg.as_bytes(policy=SMTP))
    if status != "OK":
        raise RuntimeError(f"IMAP APPEND failed for {item.lead_id}")
    status, _ = imap.select(folder, readonly=True)
    if status != "OK":
        raise RuntimeError("failed to reselect Drafts folder")
    created = _search_ids(imap, test_id)
    if len(created) != 1:
        raise RuntimeError(f"draft readback expected exactly one message for {item.lead_id}; found {len(created)}")
    return DraftReceipt(item.lead_id, item.company, item.email, test_id, folder, 1, "appended")


def _verify_receipts(imap, folder: str, receipts: Sequence[DraftReceipt]) -> None:
    status, _ = imap.select(folder, readonly=True)
    if status != "OK":
        raise RuntimeError("failed to select Drafts folder during final readback")
    for receipt in receipts:
        ids = _search_ids(imap, receipt.test_id)
        if len(ids) != 1:
            raise RuntimeError(f"final readback expected exactly one draft for {receipt.lead_id}; found {len(ids)}")


def _mark_concepts(service, spreadsheet_id: str, selected: Sequence[Candidate]) -> None:
    _headers, leads = _rows(get_values(service, spreadsheet_id, LEAD_SHEET))
    data: list[dict[str, object]] = []
    matched: set[str] = set()
    for item in selected:
        matches = []
        for row_no, row in enumerate(leads, start=2):
            same_email = _email(row.get("E-mail") or row.get("email")) == item.email
            same_domain = host_key(_text(row.get("Website") or row.get("website"))) == host_key(item.website)
            if same_email and same_domain:
                matches.append(row_no)
        if len(matches) != 1:
            raise RuntimeError(f"Leadlijst concept mapping expected one row for {item.lead_id}; found {len(matches)}")
        data.append({"range": f"'{LEAD_SHEET}'!D{matches[0]}", "values": [["concept"]]})
        matched.add(item.lead_id)
    if len(matched) != len(selected):
        raise RuntimeError("Leadlijst mapping did not cover the complete selected batch")
    if data:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"valueInputOption": "RAW", "data": data},
        ).execute()

    _headers, verify_rows = _rows(get_values(service, spreadsheet_id, LEAD_SHEET))
    for item in selected:
        matches = [
            row for row in verify_rows
            if _email(row.get("E-mail") or row.get("email")) == item.email
            and host_key(_text(row.get("Website") or row.get("website"))) == host_key(item.website)
        ]
        if len(matches) != 1 or _text(matches[0].get("Status") or matches[0].get("status")).casefold() != "concept":
            raise RuntimeError(f"Leadlijst concept readback failed for {item.lead_id}")


def _load_state(service, spreadsheet_id: str):
    _, queue = _rows(get_values(service, spreadsheet_id, QUEUE_SHEET))
    _, candidates = _rows(get_values(service, spreadsheet_id, CANDIDATE_SHEET))
    _, qualifications = _rows(get_values(service, spreadsheet_id, QUALIFICATION_SHEET))
    _, contacts = _rows(get_values(service, spreadsheet_id, CONTACT_SHEET))
    source_headers, sources = _rows(get_values(service, spreadsheet_id, SOURCE_SHEET))
    if source_headers != SOURCE_HEADERS:
        raise RuntimeError("ProspectSources headers do not match the active runtime contract")
    _, leads = _rows(get_values(service, spreadsheet_id, LEAD_SHEET))
    _, suppressions = _rows(get_values(service, spreadsheet_id, SUPPRESSION_SHEET))
    return queue, candidates, qualifications, contacts, sources, leads, suppressions


def _write_json(path: str, payload: object) -> None:
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def process(*, target: int, agent_type: str, country: str, run_key: str, count_only: bool = False) -> int:
    if target < 1 or target > 50:
        raise ValueError("target must be between 1 and 50")
    if agent_type not in APPROVED_AGENTS:
        raise ValueError("agent_type must be one of the five net-new website-driven approved agents")
    if not SAFE_RUN_KEY.fullmatch(run_key):
        raise ValueError("run_key contains unsupported characters")
    spreadsheet_id = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id or not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("OUTREACH_SPREADSHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON are required")

    service = build_sheets_service()
    state = _load_state(service, spreadsheet_id)
    eligible, rejected = eligible_candidates(
        state[0], agent_type=agent_type, country=country, candidates=state[1], qualifications=state[2],
        contacts=state[3], sources=state[4], leads=state[5], suppressions=state[6],
    )
    selected = eligible[:target]
    _write_json("daily-draft-selection.json", {
        "run_key": run_key,
        "agent_type": agent_type,
        "country": canonical_country(country),
        "target": target,
        "eligible": len(eligible),
        "selected": [
            {
                "lead_id": item.lead_id,
                "company": item.company,
                "website_host": host_key(item.website),
                "anchor": item.anchor,
                "score": item.score,
                "email_sha256": hashlib.sha256(item.email.encode("utf-8")).hexdigest(),
            }
            for item in selected
        ],
        "rejected_count": len(rejected),
        "send_permission": "none",
        "transport": "IMAP_DRAFT_ONLY",
    })
    if count_only:
        print(f"DAILY_DRAFT_READY={len(eligible)} target={target} agent={agent_type} country={canonical_country(country)}")
        return 0
    if not selected:
        _write_json("daily-draft-receipts.json", [])
        print(f"DAILY_LEAD_DRAFTS=green selected=0 drafts=0 appended=0 existing=0 target={target} no_change=true smtp_send=not_invoked")
        return 0

    if not os.getenv("OUTREACH_MAIL_PASSWORD", "").strip():
        raise RuntimeError("OUTREACH_MAIL_PASSWORD is required for IMAP draft creation")
    if canonical_country(country) == "US" and not os.getenv("OUTREACH_POSTAL_ADDRESS", "").strip():
        raise RuntimeError("OUTREACH_POSTAL_ADDRESS is required for US commercial drafts")

    daily_limit = int(os.getenv("OUTREACH_DAILY_LIMIT", "20") or "20")
    mailboxes = enabled_mailboxes(load_mailboxes_from_env(mode="validate", default_daily_limit=daily_limit))
    mailbox_id = os.getenv("OUTREACH_DRAFT_MAILBOX_ID", "primary").strip() or "primary"
    mailbox = next((item for item in mailboxes if item.mailbox_id == mailbox_id), None)
    if mailbox is None:
        raise RuntimeError(f"configured draft mailbox not found: {mailbox_id}")

    imap = None
    receipts: list[DraftReceipt] = []
    try:
        imap, folder = _open_imap(mailbox)
        for item in selected:
            receipt = _append_or_readback(imap, folder, mailbox, item)
            receipts.append(receipt)
            print(f"DAILY_MYHOST_DRAFT=green lead_id={item.lead_id} action={receipt.action} folder={folder} smtp_send=not_invoked", flush=True)
        _verify_receipts(imap, folder, receipts)
    finally:
        if imap is not None:
            try:
                imap.logout()
            except Exception:
                pass

    _mark_concepts(service, spreadsheet_id, selected)
    _write_json("daily-draft-receipts.json", [
        {
            "lead_id": item.lead_id,
            "company": item.company,
            "test_id": item.test_id,
            "folder": item.folder,
            "readback_count": item.readback_count,
            "action": item.action,
            "email_sha256": hashlib.sha256(item.email.encode("utf-8")).hexdigest(),
        }
        for item in receipts
    ])
    appended = sum(1 for item in receipts if item.action == "appended")
    existing = sum(1 for item in receipts if item.action == "existing")
    print(
        f"DAILY_LEAD_DRAFTS=green selected={len(selected)} drafts={len(receipts)} appended={appended} existing={existing} "
        f"target={target} folder={receipts[0].folder} queue=manual_review send_permission=none smtp_send=not_invoked"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create an idempotent bounded batch of human-ready mijn.host drafts without SMTP send permission.")
    parser.add_argument("--target", type=int, default=50)
    parser.add_argument("--agent-type", required=True)
    parser.add_argument("--country", required=True)
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--count-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        return process(
            target=args.target, agent_type=args.agent_type.strip().casefold(), country=args.country.strip(),
            run_key=args.run_key.strip(), count_only=args.count_only,
        )
    except (RuntimeError, ValueError, OSError, imaplib.IMAP4.error) as exc:
        _write_json("daily-draft-error.json", {
            "status": "blocked", "error": str(exc), "send_permission": "none", "smtp_send": "not_invoked",
        })
        print(f"DAILY_LEAD_DRAFTS=blocked detail={exc} smtp_send=not_invoked", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
