"""Accept only an opaque authorized GitHub draft trigger, then store a Mijn.Host draft."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from myhost_draft import create_from_queue, create_batch_from_queue

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


def resolve_batch_request(event_name: str, event: dict, inputs: dict) -> list[str]:
    if event_name == "issue_comment":
        issue = event.get("issue") or {}
        comment = event.get("comment") or {}
        if (issue.get("number") != ISSUE_NUMBER or
                str(comment.get("author_association") or "").upper() not in ALLOWED_ASSOCIATIONS):
            raise ValueError("batch_trigger_unauthorized")
        text = str(comment.get("body") or "").strip()
        if not text.startswith("LEADS_DRAFT_BATCH_ONLY:"):
            raise ValueError("batch_trigger_invalid")
        payload = text.split(":", 1)[1].strip()
    elif event_name == "workflow_dispatch":
        payload = str(inputs.get("draft_ids") or "").strip()
    else:
        raise ValueError("batch_trigger_untrusted")
    ids = [part.strip().casefold() for part in payload.split(",")]
    if (not 2 <= len(ids) <= 50 or len(set(ids)) != len(ids) or
            any(not re.fullmatch(r"draft-[0-9a-f]{32}", value) for value in ids)):
        raise ValueError("batch_trigger_ids_invalid")
    return ids


def main() -> int:
    try:
        event_name = os.environ.get("GITHUB_EVENT_NAME", "")
        path = os.environ.get("GITHUB_EVENT_PATH", "")
        event = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
        inputs = {"draft_id": os.environ.get("DRAFT_ID", ""),
                  "draft_ids": os.environ.get("DRAFT_IDS", "")}
        comment_body = str((event.get("comment") or {}).get("body") or "")
        is_batch = (event_name == "issue_comment" and
                    comment_body.startswith("LEADS_DRAFT_BATCH_ONLY:")) or (
                    event_name == "workflow_dispatch" and bool(inputs["draft_ids"]))
        if is_batch:
            draft_ids = resolve_batch_request(event_name, event, inputs)
            result = create_batch_from_queue(draft_ids)
            if result["total"] != result["created"] + result["existing"]:
                raise RuntimeError("batch_count_mismatch")
            print("MYHOST_DRAFT=green stored={} new={} existing={} sent=0".format(
                result["total"], result["created"], result["existing"]))
        else:
            draft_id = resolve_request(event_name, event, inputs)
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
