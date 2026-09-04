from __future__ import annotations

import imaplib
import os
import smtplib
import ssl
from dataclasses import dataclass
from typing import Callable

from outreach_mailboxes import MailboxConfig, enabled_mailboxes, load_mailboxes_from_env
from outreach_preflight import check_mailbox_auth, validate_mailbox_static


TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off", ""}


@dataclass(frozen=True)
class ConnectivityReport:
    checks: tuple[str, ...]
    auth_status: str


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be true or false")


def check_mailbox_transport(
    mailbox: MailboxConfig,
    smtp_factory: Callable = smtplib.SMTP,
    smtp_ssl_factory: Callable = smtplib.SMTP_SSL,
    imap_factory: Callable = imaplib.IMAP4_SSL,
) -> list[str]:
    """Prove encrypted SMTP/IMAP reachability without authenticating or sending."""
    context = ssl.create_default_context()

    if mailbox.smtp_port == 465:
        with smtp_ssl_factory(mailbox.smtp_host, mailbox.smtp_port, context=context, timeout=30) as smtp:
            smtp.ehlo()
    else:
        with smtp_factory(mailbox.smtp_host, mailbox.smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            if not smtp.has_extn("starttls"):
                raise RuntimeError(f"SMTP server does not advertise STARTTLS for mailbox {mailbox.mailbox_id}")
            smtp.starttls(context=context)
            smtp.ehlo()

    with imap_factory(mailbox.imap_host, mailbox.imap_port, ssl_context=context):
        pass

    return [f"mailbox:{mailbox.mailbox_id}:smtp-tls", f"mailbox:{mailbox.mailbox_id}:imap-tls"]


def run_connectivity_check(require_auth: bool | None = None) -> ConnectivityReport:
    daily_limit = int(os.getenv("OUTREACH_DAILY_LIMIT", "20") or "20")
    if require_auth is None:
        require_auth = _env_bool("OUTREACH_CONNECTIVITY_REQUIRE_AUTH", True)

    # Validate-mode loading deliberately allows a missing password so host/TLS
    # reachability can still be proven before the user supplies the secret.
    mailboxes = load_mailboxes_from_env(mode="validate", default_daily_limit=daily_limit)
    active = enabled_mailboxes(mailboxes)
    if not active:
        raise RuntimeError("no enabled mailbox configured")

    errors: list[str] = []
    for mailbox in active:
        errors.extend(validate_mailbox_static(mailbox, "validate"))
    if errors:
        raise RuntimeError("mailbox connectivity configuration failed: " + "; ".join(errors))

    checks: list[str] = []
    missing_auth: list[str] = []
    for mailbox in active:
        checks.extend(check_mailbox_transport(mailbox))
        if not mailbox.mail_password:
            missing_auth.append(mailbox.mailbox_id)
            checks.append(f"mailbox:{mailbox.mailbox_id}:auth-blocked-missing-secret")
            continue

        live_errors = validate_mailbox_static(mailbox, "live")
        if live_errors:
            raise RuntimeError("mailbox live-auth configuration failed: " + "; ".join(live_errors))
        checks.extend(check_mailbox_auth(mailbox, "live"))

    if missing_auth and require_auth:
        raise RuntimeError(
            "OUTREACH_MAIL_PASSWORD is required for mailbox authentication; "
            "transport TLS checks completed for: " + ",".join(missing_auth)
        )

    auth_status = "green" if not missing_auth else "blocked_missing_secret"
    return ConnectivityReport(tuple(checks), auth_status)


def main() -> int:
    try:
        report = run_connectivity_check()
    except (RuntimeError, ValueError) as exc:
        print(f"MAILBOX_CONNECTIVITY=blocked detail={exc}")
        return 2

    state = "green" if report.auth_status == "green" else "transport_green_auth_blocked"
    print(
        f"MAILBOX_CONNECTIVITY={state} auth={report.auth_status} "
        "checks=" + ",".join(report.checks)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
