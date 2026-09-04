from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

import dns.resolver

from outreach_mailbox_connectivity import check_mailbox_transport
from outreach_mailboxes import MailboxConfig, enabled_mailboxes, load_mailboxes_from_env
from outreach_preflight import check_dns_authentication, check_mailbox_auth, validate_mailbox_static
from outreach_reporting import replace_sheet_rows
from outreach_sender import build_sheets_service, domain_of

SENDER_READINESS_SHEET = "SenderReadiness"
SENDER_READINESS_HEADERS = [
    "generated_at", "mailbox_id", "sender_email", "domain", "spf", "dkim", "dmarc",
    "mx", "smtp_tls", "imap_tls", "auth", "ptr", "fcrdns", "dnsbl", "state", "note",
]
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off", ""}


@dataclass(frozen=True)
class PtrReport:
    ptr: str
    fcrdns: str
    detail: str


def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be true or false")


def split_csv(value: str) -> list[str]:
    output: list[str] = []
    for item in (value or "").replace("\n", ",").split(","):
        item = item.strip().strip(".").lower()
        if item and item not in output:
            output.append(item)
    return output[:20]


def check_mx(domain: str, resolver: Callable[[str, str], Iterable] = dns.resolver.resolve) -> str:
    try:
        return "green" if list(resolver(domain, "MX")) else "blocked"
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return "blocked"
    except Exception:
        return "unknown"


def check_ptr_fcrdns(outbound_ip: str, *, reverse_lookup: Callable = socket.gethostbyaddr, forward_lookup: Callable = socket.getaddrinfo) -> PtrReport:
    outbound_ip = (outbound_ip or "").strip()
    if not outbound_ip:
        return PtrReport("not_configured", "not_configured", "OUTREACH_OUTBOUND_IP not configured")
    try:
        parsed = ipaddress.ip_address(outbound_ip)
    except ValueError:
        return PtrReport("blocked", "blocked", "OUTREACH_OUTBOUND_IP is not a valid IP address")
    if not parsed.is_global:
        return PtrReport("blocked", "blocked", "OUTREACH_OUTBOUND_IP must be a public global IP")
    try:
        hostname = str(reverse_lookup(outbound_ip)[0]).rstrip(".").lower()
    except Exception as exc:
        return PtrReport("blocked", "blocked", f"PTR lookup failed: {type(exc).__name__}")
    try:
        addresses = {row[4][0] for row in forward_lookup(hostname, None, type=socket.SOCK_STREAM)}
    except Exception as exc:
        return PtrReport("green", "blocked", f"forward lookup for PTR hostname failed: {type(exc).__name__}")
    return PtrReport("green", "green" if outbound_ip in addresses else "blocked", hostname)


def check_dnsbl(outbound_ip: str, zones: list[str], resolver: Callable[[str, str], Iterable] = dns.resolver.resolve) -> tuple[str, str]:
    outbound_ip = (outbound_ip or "").strip()
    if not zones:
        return "not_configured", "no DNSBL zones configured"
    try:
        parsed = ipaddress.ip_address(outbound_ip)
    except ValueError:
        return "unknown", "OUTREACH_OUTBOUND_IP required for DNSBL checks"
    if parsed.version != 4 or not parsed.is_global:
        return "unknown", "DNSBL checks currently support public IPv4 only"
    reversed_ip = ".".join(reversed(outbound_ip.split(".")))
    listed: list[str] = []
    unknown: list[str] = []
    for zone in zones:
        query = f"{reversed_ip}.{zone}"
        try:
            answers = list(resolver(query, "A"))
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            continue
        except Exception:
            unknown.append(zone)
            continue
        if answers:
            listed.append(zone)
    if listed:
        return "listed", "listed by: " + ",".join(listed)
    if unknown:
        return "unknown", "lookup unavailable for: " + ",".join(unknown)
    return "clear", "not listed in configured zones"


def _dns_auth_state(mailbox: MailboxConfig) -> tuple[dict[str, str], list[str]]:
    domain = domain_of(mailbox.sender_email)
    errors, checks = check_dns_authentication(domain, mailbox.dkim_selector, mailbox.required_spf_token)
    states = {
        "spf": "green" if "spf" in checks else "blocked",
        "dkim": "green" if "dkim" in checks else ("unknown" if not mailbox.dkim_selector else "blocked"),
        "dmarc": "green" if "dmarc" in checks else "blocked",
    }
    return states, errors


def build_readiness_row(mailbox: MailboxConfig, *, outbound_ip: str = "", dnsbl_zones: list[str] | None = None, generated_at: str | None = None) -> dict[str, str]:
    generated_at = generated_at or utc_iso()
    dnsbl_zones = dnsbl_zones or []
    notes: list[str] = []
    static_errors = validate_mailbox_static(mailbox, "validate")
    if static_errors:
        notes.extend(static_errors)
    dns_states, dns_errors = _dns_auth_state(mailbox)
    notes.extend(dns_errors)
    mx = check_mx(domain_of(mailbox.sender_email))
    if mx != "green":
        notes.append("MX could not be proven green")
    smtp_tls = "blocked"
    imap_tls = "blocked"
    try:
        transport_checks = check_mailbox_transport(mailbox)
    except Exception as exc:
        notes.append(f"TLS transport check failed: {type(exc).__name__}: {exc}")
    else:
        smtp_tls = "green" if any(item.endswith(":smtp-tls") for item in transport_checks) else "blocked"
        imap_tls = "green" if any(item.endswith(":imap-tls") for item in transport_checks) else "blocked"
    if mailbox.mail_password:
        try:
            check_mailbox_auth(mailbox, "live")
        except Exception as exc:
            auth = "blocked"
            notes.append(f"mailbox auth failed: {type(exc).__name__}: {exc}")
        else:
            auth = "green"
    else:
        auth = "blocked_missing_secret"
        notes.append("mailbox authentication not proven because password secret is absent")
    ptr_report = check_ptr_fcrdns(outbound_ip)
    dnsbl, dnsbl_detail = check_dnsbl(outbound_ip, dnsbl_zones)
    notes.append(f"PTR/FCrDNS: {ptr_report.detail}")
    notes.append(f"DNSBL: {dnsbl_detail}")
    hard_blockers = [
        dns_states["spf"] == "blocked", dns_states["dkim"] == "blocked", dns_states["dmarc"] == "blocked",
        mx == "blocked", smtp_tls == "blocked", imap_tls == "blocked", auth == "blocked",
        ptr_report.ptr == "blocked", ptr_report.fcrdns == "blocked", dnsbl == "listed", bool(static_errors),
    ]
    if any(hard_blockers):
        state = "blocked"
    elif auth != "green" or ptr_report.ptr != "green" or ptr_report.fcrdns != "green" or dnsbl in {"unknown", "not_configured"} or mx == "unknown":
        state = "review"
    else:
        state = "green"
    return {
        "generated_at": generated_at, "mailbox_id": mailbox.mailbox_id, "sender_email": mailbox.sender_email,
        "domain": domain_of(mailbox.sender_email), "spf": dns_states["spf"], "dkim": dns_states["dkim"],
        "dmarc": dns_states["dmarc"], "mx": mx, "smtp_tls": smtp_tls, "imap_tls": imap_tls,
        "auth": auth, "ptr": ptr_report.ptr, "fcrdns": ptr_report.fcrdns, "dnsbl": dnsbl,
        "state": state, "note": "; ".join(notes)[:1000],
    }


def readiness_gate_error(rows: list[dict[str, str]], *, fail_on_blocked: bool, require_green: bool) -> str:
    blocked = sum(1 for row in rows if row.get("state") == "blocked")
    review = sum(1 for row in rows if row.get("state") == "review")
    if require_green and (blocked or review):
        return f"sender readiness must be green: blocked={blocked} review={review}"
    if blocked and fail_on_blocked:
        return f"{blocked} sender mailbox(es) have blocked readiness"
    return ""


def run() -> list[dict[str, str]]:
    spreadsheet_id = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        raise RuntimeError("OUTREACH_SPREADSHEET_ID is required")
    if not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is required to write SenderReadiness")
    daily_limit = int(os.getenv("OUTREACH_DAILY_LIMIT", "20") or "20")
    mailboxes = enabled_mailboxes(load_mailboxes_from_env(mode="validate", default_daily_limit=daily_limit))
    if not mailboxes:
        raise RuntimeError("no enabled mailbox configured")
    outbound_ip = os.getenv("OUTREACH_OUTBOUND_IP", "").strip()
    dnsbl_zones = split_csv(os.getenv("OUTREACH_DNSBL_ZONES", ""))
    generated_at = utc_iso()
    rows = [build_readiness_row(mailbox, outbound_ip=outbound_ip, dnsbl_zones=dnsbl_zones, generated_at=generated_at) for mailbox in mailboxes]
    service = build_sheets_service()
    replace_sheet_rows(service, spreadsheet_id, SENDER_READINESS_SHEET, SENDER_READINESS_HEADERS, rows)
    blocked = sum(1 for row in rows if row["state"] == "blocked")
    review = sum(1 for row in rows if row["state"] == "review")
    print(f"SENDER_READINESS=complete mailboxes={len(rows)} blocked={blocked} review={review}")
    error = readiness_gate_error(
        rows,
        fail_on_blocked=env_bool("OUTREACH_READINESS_FAIL_ON_BLOCKED", True),
        require_green=env_bool("OUTREACH_READINESS_REQUIRE_GREEN", False),
    )
    if error:
        raise RuntimeError(error)
    return rows


def main() -> int:
    try:
        run()
    except (RuntimeError, ValueError) as exc:
        print(f"SENDER_READINESS=blocked detail={exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
