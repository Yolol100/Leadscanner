"""Strict, owner-only ChatGPT command transport for existing Leadscanner work.

GitHub issue comments contain only opaque commands. The project controller and
Leads Skill remain authoritative; this is a bounded execution adapter only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

REPO = "Yolol100/Leadscanner"
ISSUE = 1720
OWNER = "Yolol100"
PREFIX = "LEADS_CHAT_V1:"
PREFIX2 = "LEADS_CHAT_V2:"
REVIEW_MODES = frozenset(f"REVIEW_EVIDENCE_{i}" for i in range(1, 6))
REQUIRES_ID = frozenset({"EVIDENCE", "HINTS_10", "HINTS_30", "HINTS_50", "HINTS_100", "VERIFIED_100"}) | REVIEW_MODES
REQUEST_RE = re.compile(r"r-[0-9a-f]{32}\Z")
MAX_COMMENT_PAGES = 20
MODES = frozenset({
    "CHECK", "DRAFTS_AUDIT", "EVIDENCE", "HINTS_10", "HINTS_30",
    "HINTS_50", "HINTS_100", "VERIFIED_100",
}) | REVIEW_MODES



def parse_command(raw: object) -> tuple[str, str | None]:
    """Legacy read-only syntax or idempotent, opaque-ID on-demand request."""
    if not isinstance(raw, str):
        raise ValueError("command_missing")
    if raw.startswith(PREFIX):
        mode = raw[len(PREFIX):]
        if mode not in MODES or raw != PREFIX + mode:
            raise ValueError("command_not_allowlisted")
        if mode in REQUIRES_ID:
            raise ValueError("command_request_id_required")
        return mode, None
    if raw.startswith(PREFIX2):
        parts = raw[len(PREFIX2):].split(":")
        if (len(parts) != 2 or parts[0] not in REQUIRES_ID
                or not REQUEST_RE.fullmatch(parts[1])
                or raw != PREFIX2 + parts[0] + ":" + parts[1]):
            raise ValueError("command_request_id_invalid")
        return parts[0], parts[1]
    raise ValueError("command_missing")


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
    mode, _ = parse_command(comment.get("body"))
    return mode


def list_issue_comments() -> list[dict]:
    """Read existing issue history with stdlib only; fail closed if incomplete."""
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("command_history_token_missing")
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
    endpoint = f"https://api.github.com/repos/{REPO}/issues/{ISSUE}/comments"
    result = []
    try:
        for page in range(1, MAX_COMMENT_PAGES + 1):
            url = endpoint + "?" + urlencode({"per_page": 100, "page": page})
            request = Request(url, headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            })
            with urlopen(request, timeout=20) as response:
                if response.status != 200:
                    raise RuntimeError("command_history_unavailable")
                records = json.load(response)
            if not isinstance(records, list) or len(records) > 100:
                raise RuntimeError("command_history_invalid")
            result.extend(records)
            if len(records) < 100:
                return result
    except Exception:
        raise RuntimeError("command_history_unavailable") from None
    raise RuntimeError("command_history_too_large")


def authorize_once(event: dict, comments: list[dict], *, attempt: int = 1) -> bool:
    """Only earliest owner-comment for an opaque ID may execute private writes."""
    mode = validate(event)
    if mode not in REQUIRES_ID:
        return True
    if attempt != 1:
        return False
    current = event["comment"]
    current_id = current.get("id")
    if not isinstance(current_id, int) or current_id <= 0:
        raise ValueError("command_comment_id_missing")
    _, request_id = parse_command(current.get("body"))
    if not isinstance(comments, list):
        raise RuntimeError("command_history_invalid")
    actual = [row for row in comments if row.get("id") == current_id]
    if (len(actual) != 1 or actual[0].get("body") != current["body"]
            or (actual[0].get("user") or {}).get("login") != OWNER):
        raise RuntimeError("command_history_current_missing")
    for row in comments:
        older = row.get("id")
        if not isinstance(older, int) or older <= 0 or older >= current_id:
            continue
        body = row.get("body")
        if not isinstance(body, str) or not body.startswith(PREFIX2):
            continue
        try:
            _, previous_id = parse_command(body)
        except ValueError:
            continue
        if previous_id == request_id:
            if body == current["body"] and (row.get("user") or {}).get("login") == OWNER:
                return False
            raise RuntimeError("command_request_id_conflict")
    return True


def execute(mode: str) -> None:
    """Execute existing bounded scripts, never a shell or mail sender."""
    if mode not in MODES:
        raise ValueError("mode_not_allowlisted")
    if mode == "CHECK":
        from registry_readonly import load_discovery_suppressions
        # CHECK must cover exactly the same historical, HMAC, LeadHistory
        # and DraftQueue sources as new discovery, not just the baseline.
        entries = load_discovery_suppressions()
        if len(entries) < 2:
            raise RuntimeError("suppression_incomplete")
        print("LEADS_CHAT_PREFLIGHT=green")
        return
    if mode == "DRAFTS_AUDIT":
        # Existing read-only 450 inventory: no APPEND, STORE, EXPUNGE or SMTP.
        args = ["scripts/live_450_draft_inventory.py"]
    elif mode == "EVIDENCE":
        args = ["scripts/fast_website_evidence.py",
                "--source", "Approved", "--batch", "1", "--force"]
    elif mode in REVIEW_MODES:
        batch = mode.rsplit("_", 1)[1]
        args = ["scripts/fast_website_evidence.py",
                "--source", "Review450", "--batch", batch, "--force"]
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
        if mode in REQUIRES_ID:
            raw_attempt = os.getenv("GITHUB_RUN_ATTEMPT", "1")
            if not raw_attempt.isdigit() or int(raw_attempt) < 1:
                raise RuntimeError("command_run_attempt_invalid")
            attempt = int(raw_attempt)
            # A GitHub re-run may repeat an already-committed private write.
            if attempt > 1:
                print("LEADS_CHAT_COMMAND=retry_noop")
                return 0
            if not authorize_once(event, list_issue_comments(), attempt=attempt):
                print("LEADS_CHAT_COMMAND=duplicate_noop")
                return 0
        execute(mode)
        return 0
    except Exception:
        # No secrets, identities, request IDs or tracebacks in public logs.
        print("LEADS_CHAT_COMMAND=blocked details_suppressed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
