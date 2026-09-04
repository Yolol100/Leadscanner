from __future__ import annotations

import os

from outreach_mailboxes import enabled_mailboxes, load_mailboxes_from_env
from outreach_preflight import check_mailbox_auth, validate_mailbox_static


def run_connectivity_check() -> tuple[str, ...]:
    daily_limit = int(os.getenv("OUTREACH_DAILY_LIMIT", "20") or "20")
    mailboxes = load_mailboxes_from_env(mode="live", default_daily_limit=daily_limit)
    active = enabled_mailboxes(mailboxes)
    if not active:
        raise RuntimeError("no enabled mailbox configured")

    errors: list[str] = []
    for mailbox in active:
        errors.extend(validate_mailbox_static(mailbox, "live"))
    if errors:
        raise RuntimeError("mailbox connectivity configuration failed: " + "; ".join(errors))

    checks: list[str] = []
    for mailbox in active:
        checks.extend(check_mailbox_auth(mailbox, "live"))
    return tuple(checks)


def main() -> int:
    checks = run_connectivity_check()
    print("MAILBOX_CONNECTIVITY=green checks=" + ",".join(checks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
