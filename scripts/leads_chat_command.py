"""Strict, owner-only ChatGPT command transport for existing Leadscanner work.

GitHub issue comments contain only opaque commands. The project controller and
Leads Skill remain authoritative; this is a bounded execution adapter only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

REPO = "Yolol100/Leadscanner"
ISSUE = 1720
OWNER = "Yolol100"
PREFIX = "LEADS_CHAT_V1:"
MODES = frozenset({
    "CHECK", "EVIDENCE", "HINTS_10", "HINTS_30",
    "HINTS_50", "HINTS_100", "VERIFIED_100",
})


def validate(event: dict, *, event_name: str = "issue_comment") -> str:
    """Fail closed on a foreign issue, actor, repository, event or command."""
    if not isinstance(event, dict) or event_name != "issue_comment":
        raise ValueError("event_invalid")
    issue = event.get("issue") or {}
    comment = event.get("comment") or {}
    repo = event.get("repository") or {}
    if (event.get("action") != "created"
            or repo.get("full_name") != REPO
            or issue.get("number") != ISSUE
            or issue.get("pull_request")
            or (comment.get("user") or {}).get("login") != OWNER):
        raise ValueError("event_unauthorized")
    raw = comment.get("body")
    if not isinstance(raw, str) or not raw.startswith(PREFIX):
        raise ValueError("command_missing")
    mode = raw[len(PREFIX):]
    if mode not in MODES or raw != PREFIX + mode:
        raise ValueError("command_not_allowlisted")
    return mode


def execute(mode: str) -> None:
    """Execute existing bounded scripts, never a shell or mail sender."""
    if mode not in MODES:
        raise ValueError("mode_not_allowlisted")
    if mode == "CHECK":
        from registry_readonly import load_suppressions
        entries = load_suppressions()
        if len(entries) < 2:
            raise RuntimeError("suppression_incomplete")
        print("LEADS_CHAT_PREFLIGHT=green")
        return
    if mode == "EVIDENCE":
        args = ["scripts/fast_website_evidence.py",
                "--source", "Approved", "--batch", "1", "--force"]
    elif mode.startswith("HINTS_"):
        limit = mode.removeprefix("HINTS_")
        args = ["scripts/new_leads.py", "--region", "Nederland",
                "--keywords", "vakbedrijven", "--limit", limit,
                "--radius-km", "25", "--summary-only", "--private-handoff"]
    elif mode == "VERIFIED_100":
        args = ["scripts/verified_fill.py"]
    else:
        raise ValueError("mode_not_supported")
    subprocess.run([sys.executable, *args], check=True)
    print("LEADS_CHAT_COMMAND=green mode=" + mode)


def main() -> int:
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text("utf-8"))
        mode = validate(event, event_name=os.environ.get("GITHUB_EVENT_NAME", ""))
        execute(mode)
        return 0
    except Exception:
        # No secrets, identity, prospect names, addresses or traceback in logs.
        print("LEADS_CHAT_COMMAND=blocked details_suppressed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
