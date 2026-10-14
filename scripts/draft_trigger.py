"""Accept only an opaque authorized GitHub draft trigger, then store a Mijn.Host draft."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from myhost_draft import create_from_queue

ISSUE_NUMBER = 1659
DRAFT_RE = re.compile(r"^LEADS_DRAFT_ONLY:\s*(draft-[0-9a-f]{32})\s*$", re.I)
ALLOWED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}


def resolve_request(event_name: str, event: dict, inputs: dict) -> str:
    if event_name == "issue_comment":
        issue = event.get("issue") or {}
        comment = event.get("comment") or {}
        if issue.get("number") != ISSUE_NUMBER:
            raise ValueError("wrong_issue")
        if str(comment.get("author_association") or "").upper() not in ALLOWED_ASSOCIATIONS:
            raise ValueError("unauthorized_commenter")
        match = DRAFT_RE.fullmatch(str(comment.get("body") or "").strip())
        if not match:
            raise ValueError("invalid_comment")
        return match.group(1).casefold()
    if event_name == "workflow_dispatch":
        value = str(inputs.get("draft_id") or "").strip()
        if not re.fullmatch(r"draft-[0-9a-f]{32}", value, re.I):
            raise ValueError("invalid_dispatch_id")
        return value.casefold()
    raise ValueError("untrusted_event")


def main() -> int:
    try:
        event_name = os.environ.get("GITHUB_EVENT_NAME", "")
        path = os.environ.get("GITHUB_EVENT_PATH", "")
        event = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
        draft_id = resolve_request(
            event_name, event, {"draft_id": os.environ.get("DRAFT_ID", "")}
        )
        result = create_from_queue(draft_id)
        if result not in {"created", "existing"}:
            raise RuntimeError("unexpected_result")
        print(f"MYHOST_DRAFT=green stored=1 existing={int(result == 'existing')} sent=0")
        return 0
    except Exception:
        print("MYHOST_DRAFT=red details_suppressed sent=0")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
