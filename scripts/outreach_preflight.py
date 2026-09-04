from __future__ import annotations

import imaplib
import os
import smtplib
import ssl
from dataclasses import dataclass
from typing import Callable, Iterable

import dns.resolver

from outreach_mailboxes import MailboxConfig, enabled_mailboxes, load_mailboxes_from_env
from outreach_sender import (
    LOG_HEADERS,
    LOG_SHEET,
    QUEUE_HEADERS,
    QUEUE_SHEET,
    SUPPRESSION_HEADERS,
    SUPPRESSION_SHEET,
    Settings,
    build_sheets_service,
    domain_of,
    ensure_expected_headers,
    get_values,
    rows_from_values,
)


@dataclass(frozen=True)
class PreflightReport:
    checks: tuple[str, ...]
    warnings: tuple[str, ...]


def _txt_values(name: str, resolver: Callable[[str, str], Iterable] = dns.resolver.resolve) -> list[str]:
    values: list[str] = []
    for record in resolver(name, "TXT"):
        if hasattr(record, "strings"):
            chunks = []
            for item in record.strings:
                chunks.append(item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item))
            values.append("".join(chunks))
        else:
            values.append(str(record).strip('"').replace('" "', ""))
    return values


def validate_static(settings: Settings) -> list[str]:
    errors: list[str] = []
    if not settings.spreadsheet_id:
        errors.append("OUTREACH_SPREADSHEET_ID is required")
    if settings.mode not in {"validate", "verify", "live"}:
        errors.append("OUTREACH_MODE must be validate, verify, or live")
    return errors


def validate_mailbox_static(mailbox: MailboxConfig, mode: str) -> list[str]:
    errors: list[str] = []
    if "@" not in mailbox.sender_email:
        errors.append("sender_email must be a valid email address")
    if "@" not in mailbox.mail_user:
        errors.append("mail_user must be a valid email address")
    if mailbox.sender_email and mailbox.mail_user and domain_of(mailbox.sender_email) != domain_of(mailbox.mail_user):
        errors.append("sender_email and mail_user must use the same domain")
    if not mailbox.sender_name.strip():
        errors.append("sender_name is required")
    if not mailbox.smtp_host.strip():
        errors.append("smtp_host is required")
    if mailbox.smtp_port not in {465, 587}:
        errors.append("smtp_port must be 465 or 587")
    if not mailbox.imap_host.strip():
        errors.append("imap_host is required")
    if mailbox.imap_port != 993:
        errors.append("imap_port must be 993")
    if mode == "live" and mailbox.enabled and not mailbox.mail_password:
        errors.append("password is required in live mode")
    if mode == "live" and mailbox.enabled and not mailbox.dkim_selector:
        errors.append("dkim_selector is required in live mode")
    if mailbox.required_spf_token and any(ch.isspace() for ch in mailbox.required_spf_token):
        errors.append("required_spf_token must be one SPF token without whitespace")
    return [f"mailbox {mailbox.mailbox_id}: {error}" for error in errors]


def check_dns_authentication(
    sender_domain: str,
    dkim_selector: str,
    required_spf_token: str,
    resolver: Callable[[str, str], Iterable] = dns.resolver.resolve,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    checks: list[str] = []

    try:
        root_txt = _txt_values(sender_domain, resolver)
    except Exception as exc:
        return [f"SPF DNS lookup failed for {sender_domain}: {type(exc).__name__}: {exc}"], checks
    spf = [value for value in root_txt if value.lower().startswith("v=spf1")]
    if len(spf) != 1:
        errors.append(f"expected exactly one SPF record for {sender_domain}; found {len(spf)}")
    else:
        if required_spf_token and required_spf_token.lower() not in spf[0].lower().split():
            errors.append(f"SPF record is missing required token {required_spf_token}")
        else:
            checks.append("spf")

    try:
        dmarc_txt = _txt_values(f"_dmarc.{sender_domain}", resolver)
    except Exception as exc:
        errors.append(f"DMARC DNS lookup failed for {sender_domain}: {type(exc).__name__}: {exc}")
    else:
        dmarc = [value for value in dmarc_txt if value.lower().startswith("v=dmarc1")]
        if len(dmarc) != 1:
            errors.append(f"expected exactly one DMARC record for {sender_domain}; found {len(dmarc)}")
        else:
            checks.append("dmarc")

    if dkim_selector:
        name = f"{dkim_selector}._domainkey.{sender_domain}"
        try:
            dkim_txt = _txt_values(name, resolver)
        except Exception as exc:
            errors.append(f"DKIM DNS lookup failed for {name}: {type(exc).__name__}: {exc}")
        else:
            dkim = [value for value in dkim_txt if "p=" in value.lower() or value.lower().startswith("v=dkim1")]
            if not dkim:
                errors.append(f"no DKIM public key found at {name}")
            else:
                checks.append("dkim")

    return errors, checks


def check_sheet_contract(service, spreadsheet_id: str) -> list[str]:
    checks: list[str] = []
    for name, expected in (
        (QUEUE_SHEET, QUEUE_HEADERS),
        (SUPPRESSION_SHEET, SUPPRESSION_HEADERS),
        (LOG_SHEET, LOG_HEADERS),
    ):
        headers, _ = rows_from_values(get_values(service, spreadsheet_id, name))
        ensure_expected_headers(headers, expected, name)
        checks.append(f"sheet:{name}")
    return checks


def check_mailbox_auth(
    mailbox: MailboxConfig,
    mode: str,
    smtp_factory: Callable = smtplib.SMTP,
    smtp_ssl_factory: Callable = smtplib.SMTP_SSL,
    imap_factory: Callable = imaplib.IMAP4_SSL,
) -> list[str]:
    if mode != "live" or not mailbox.enabled:
        return []
    context = ssl.create_default_context()
    if mailbox.smtp_port == 465:
        with smtp_ssl_factory(mailbox.smtp_host, mailbox.smtp_port, context=context, timeout=30) as smtp:
            smtp.login(mailbox.mail_user, mailbox.mail_password)
    else:
        with smtp_factory(mailbox.smtp_host, mailbox.smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            if not smtp.has_extn("starttls"):
                raise RuntimeError(f"SMTP server does not advertise STARTTLS for mailbox {mailbox.mailbox_id}")
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(mailbox.mail_user, mailbox.mail_password)

    with imap_factory(mailbox.imap_host, mailbox.imap_port, ssl_context=context) as imap:
        imap.login(mailbox.mail_user, mailbox.mail_password)
        status, _ = imap.noop()
        if status != "OK":
            raise RuntimeError(f"IMAP NOOP failed for mailbox {mailbox.mailbox_id}")
    return [f"mailbox:{mailbox.mailbox_id}:smtp-auth", f"mailbox:{mailbox.mailbox_id}:imap-auth"]


def run_preflight() -> PreflightReport:
    settings = Settings.from_env()
    errors = validate_static(settings)
    try:
        mailboxes = load_mailboxes_from_env(mode=settings.mode, default_daily_limit=settings.daily_send_limit)
    except ValueError as exc:
        errors.append(str(exc))
        mailboxes = []
    for mailbox in mailboxes:
        errors.extend(validate_mailbox_static(mailbox, settings.mode))
    if errors:
        raise RuntimeError("preflight configuration failed: " + "; ".join(errors))

    active = enabled_mailboxes(mailboxes)
    checks: list[str] = ["config", f"mailbox-pool:{len(active)}"]
    warnings: list[str] = []
    seen_dns: set[tuple[str, str, str]] = set()

    for mailbox in active:
        sender_domain = domain_of(mailbox.sender_email)
        dns_key = (sender_domain, mailbox.dkim_selector, mailbox.required_spf_token)
        if dns_key in seen_dns:
            checks.append(f"mailbox:{mailbox.mailbox_id}:dns-shared")
            continue
        seen_dns.add(dns_key)
        dns_errors, dns_checks = check_dns_authentication(
            sender_domain,
            mailbox.dkim_selector,
            mailbox.required_spf_token,
        )
        if dns_errors:
            prefixed = [f"mailbox {mailbox.mailbox_id}: {error}" for error in dns_errors]
            raise RuntimeError("preflight DNS authentication failed: " + "; ".join(prefixed))
        checks.extend(f"mailbox:{mailbox.mailbox_id}:{check}" for check in dns_checks)
        if not mailbox.dkim_selector:
            warnings.append(f"mailbox {mailbox.mailbox_id}: DKIM selector not supplied; live mode will fail closed")

    if not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is required for Sheet preflight")
    service = build_sheets_service()
    checks.extend(check_sheet_contract(service, settings.spreadsheet_id))
    for mailbox in active:
        checks.extend(check_mailbox_auth(mailbox, settings.mode))

    return PreflightReport(tuple(checks), tuple(warnings))


def main() -> int:
    report = run_preflight()
    print("SENDER_PREFLIGHT=green checks=" + ",".join(report.checks))
    for warning in report.warnings:
        print("warning=" + warning)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
