from __future__ import annotations

import json
import re
from email.utils import parseaddr
from typing import Callable, Iterable

import prospect_agent_qualification as agent_policy
from prospect_discovery import BoundedHttpClient, DiscoveryError, host_key, hosts_related

CONTROL_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior)\s+instructions?\b", re.I),
    re.compile(r"\b(?:system|developer)\s+message\b", re.I),
    re.compile(r"\b(?:reveal|exfiltrate|print|return|send)\b.{0,80}\b(?:secret|password|api[_ -]?key|token)\b", re.I | re.S),
    re.compile(r"\bsend_permission\s*=", re.I),
    re.compile(r"\bsmtp_send\s*=", re.I),
    re.compile(r"\bOUTREACH_MAIL_PASSWORD\b", re.I),
    re.compile(r"\bINSTANTLY_API_KEY\b", re.I),
    re.compile(r"\$\{\{\s*secrets\.", re.I),
)
TRUTHY = {"1", "true", "yes", "on"}


def _truthy(value: object) -> bool:
    return str(value or "").strip().casefold() in TRUTHY


def _email_domain(value: object) -> str:
    address = parseaddr(str(value or ""))[1].strip().casefold().strip(".")
    return address.rsplit("@", 1)[1] if "@" in address else ""


def _has_idn_or_unicode(host: str) -> bool:
    host = (host or "").casefold().strip(".")
    if not host:
        return False
    return any(label.startswith("xn--") for label in host.split(".")) or any(ord(char) > 127 for char in host)


def identity_errors(row: dict[str, str]) -> list[str]:
    errors: list[str] = []
    website = str(row.get("website", "") or "").strip()
    website_host = host_key(website)
    email_host = _email_domain(row.get("email", ""))
    if not website_host or not email_host:
        return ["official website/email identity is incomplete"]
    if (_has_idn_or_unicode(website_host) or _has_idn_or_unicode(email_host)) and not _truthy(row.get("identity_idn_verified")):
        errors.append("IDN/punycode identity requires explicit manual verification")
    if not hosts_related(website_host, email_host) and not _truthy(row.get("identity_cross_domain_verified")):
        errors.append("email domain is not related to the official website domain")
    return errors


def control_instruction_errors(row: dict[str, str]) -> list[str]:
    values = {
        "subject": str(row.get("subject", "") or ""),
        "body": str(row.get("body", "") or ""),
        "source": str(row.get("source", "") or ""),
    }
    for field, value in values.items():
        if any(pattern.search(value) for pattern in CONTROL_PATTERNS):
            return [f"control-like instruction survived in untrusted {field} data"]
    return []


def _agent_offer_metadata(row: dict[str, str]) -> dict[str, object] | None:
    source = str(row.get("source", "") or "").strip()
    if not source.startswith("agent_offer:"):
        return None
    try:
        parsed = json.loads(source.split(":", 1)[1])
    except (ValueError, TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def live_evidence_errors(row: dict[str, str], *, fetch: Callable[[str], str] | None = None) -> list[str]:
    metadata = _agent_offer_metadata(row)
    if metadata is None:
        return []
    website = str(row.get("website", "") or "").strip()
    evidence_url = str(metadata.get("evidence_url", "") or "").strip()
    agent_type = str(metadata.get("agent_type", "") or "").strip().casefold()
    if not evidence_url or not agent_type:
        return ["agent-offer row lacks evidence_url or agent_type"]
    website_host = host_key(website)
    evidence_host = host_key(evidence_url)
    if not website_host or not evidence_host or not hosts_related(website_host, evidence_host):
        return ["qualification evidence URL is no longer tied to the official website"]

    if fetch is None:
        client = BoundedHttpClient(timeout=8.0, max_bytes=524_288, min_interval=0.0)
        fetch = client.fetch_text
    try:
        html = fetch(evidence_url)
    except (DiscoveryError, OSError, RuntimeError, ValueError) as exc:
        return [f"current qualification evidence could not be revalidated: {exc}"]

    try:
        page = agent_policy._parse_evidence_page(html, evidence_url)
        context = agent_policy._page_context(page)
        fit = agent_policy.classify_agent_context(context, agent_type)
    except (ValueError, RuntimeError) as exc:
        return [f"current qualification evidence could not be classified: {exc}"]
    if fit.agent_type != agent_type or fit.score <= 0:
        return ["qualification evidence changed and no longer supports the queued offer"]
    return []


def row_guard_errors(row: dict[str, str], *, fetch: Callable[[str], str] | None = None) -> list[str]:
    errors: list[str] = []
    errors.extend(identity_errors(row))
    errors.extend(control_instruction_errors(row))
    errors.extend(live_evidence_errors(row, fetch=fetch))
    return errors


def validate_last_mile_rows(rows: Iterable[dict[str, str]], *, fetch: Callable[[str], str] | None = None) -> None:
    for row in rows:
        errors = row_guard_errors(row, fetch=fetch)
        if errors:
            lead_id = str(row.get("lead_id", "") or "").strip() or "unknown"
            raise RuntimeError(f"last-mile evidence guard blocked {lead_id}: " + "; ".join(errors))
