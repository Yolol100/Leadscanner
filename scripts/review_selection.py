#!/usr/bin/env python3
"""Phases 16-18: human review queue and exact approval-token filtering."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
from pathlib import Path

MAX_APPROVALS = 100
TOKEN_RE = re.compile(r"^(growth-[0-9a-f]{20})@([0-9a-f]{16})$")


def _text(value: object) -> str:
    return str(value or "").strip()


def review_token(row: dict) -> str:
    lead_id = _text(row.get("lead_id"))
    if not re.fullmatch(r"growth-[0-9a-f]{20}", lead_id):
        raise ValueError("invalid_lead_id_for_review_token")
    canonical = "\0".join([
        lead_id,
        _text(row.get("company")),
        _text(row.get("official_domain")).casefold(),
        _text(row.get("email")).casefold(),
        _text(row.get("subject")),
        _text(row.get("body")),
        _text(row.get("verified_observation")),
        _text(row.get("verified_observation_source_url")),
        _text(row.get("signal_type")),
        _text(row.get("value_first_action")),
    ])
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{lead_id}@{digest}"


def build_review_queue(batch: dict) -> dict:
    rows = batch.get("rows") or []
    if not isinstance(rows, list):
        raise ValueError("rows_must_be_list")
    if len(rows) > MAX_APPROVALS:
        raise ValueError("review_queue_limit_exceeded")

    items: list[dict] = []
    seen_tokens: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("review_row_must_be_object")
        if row.get("status") != "review_draft":
            raise ValueError("review_queue_requires_review_draft")
        if row.get("contact_basis_status") != "review_required":
            raise ValueError("review_queue_requires_review_required")
        if row.get("automatic_send") is not False:
            raise ValueError("automatic_send_must_be_false")

        token = review_token(row)
        if token in seen_tokens:
            raise ValueError("duplicate_review_token")
        seen_tokens.add(token)
        items.append({
            "approval_token": token,
            "lead_id": _text(row.get("lead_id")),
            "company": _text(row.get("company")),
            "website": _text(row.get("website")),
            "official_domain": _text(row.get("official_domain")),
            "email": _text(row.get("email")),
            "signal_type": _text(row.get("signal_type")),
            "verified_observation": _text(row.get("verified_observation")),
            "verified_observation_source_url": _text(row.get("verified_observation_source_url")),
            "value_first_action": _text(row.get("value_first_action")),
            "subject": _text(row.get("subject")),
            "body": _text(row.get("body")),
        })

    return {
        "schema_version": "leadscanner-review-queue/1.0",
        "review_candidate_count": len(items),
        "items": items,
        "instructions": {
            "draft_input": "approved_review_tokens",
            "approval_rule": "Only exact approval tokens from this preview are accepted.",
            "stale_copy_policy": "reject",
            "automatic_send": False,
        },
    }


def render_markdown(queue: dict) -> str:
    lines = [
        "# Leadscanner review queue",
        "",
        f"Review candidates: **{int(queue.get('review_candidate_count') or 0)}**",
        "",
        "Copy only the approval tokens for leads you want stored as review drafts.",
        "A token is bound to the exact reviewed subject/body/evidence; changed copy produces a different token.",
        "",
    ]
    for index, item in enumerate(queue.get("items") or [], start=1):
        lines.extend([
            f"## {index}. {_text(item.get('company'))}",
            "",
            f"- Approval token: `{_text(item.get('approval_token'))}`",
            f"- Domain: {_text(item.get('official_domain'))}",
            f"- Email: {_text(item.get('email'))}",
            f"- Signal: {_text(item.get('signal_type'))}",
            f"- Evidence: {_text(item.get('verified_observation'))}",
            f"- Evidence URL: {_text(item.get('verified_observation_source_url'))}",
            f"- Proposed value: {_text(item.get('value_first_action'))}",
            f"- Subject: {_text(item.get('subject'))}",
            "",
            "### Body",
            "",
        ])
        body = _text(item.get("body"))
        if body:
            lines.extend([f"> {line}" if line else ">" for line in body.splitlines()])
        else:
            lines.append("> ")
        lines.extend(["", "---", ""])
    return "\n".join(lines).rstrip() + "\n"


def render_csv(queue: dict) -> str:
    output = io.StringIO()
    fields = [
        "approval_token", "lead_id", "company", "official_domain", "email",
        "signal_type", "verified_observation", "verified_observation_source_url",
        "value_first_action", "subject", "body",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for item in queue.get("items") or []:
        writer.writerow(item)
    return output.getvalue()


def parse_approval_tokens(raw: str) -> list[str]:
    tokens = [part.strip().casefold() for part in re.split(r"[,;\n\r\t ]+", raw or "") if part.strip()]
    if not tokens:
        raise ValueError("at_least_one_approval_token_required")
    if len(tokens) > MAX_APPROVALS:
        raise ValueError("approval_limit_exceeded")
    if len(tokens) != len(set(tokens)):
        raise ValueError("duplicate_approval_token_input")
    for token in tokens:
        if not TOKEN_RE.fullmatch(token):
            raise ValueError(f"invalid_approval_token:{token}")
    return tokens


def select_approved(batch: dict, raw_tokens: str) -> dict:
    queue = build_review_queue(batch)
    approved_tokens = parse_approval_tokens(raw_tokens)
    by_token = {item["approval_token"]: item for item in queue["items"]}
    unknown = [token for token in approved_tokens if token not in by_token]
    if unknown:
        raise ValueError("unknown_or_stale_approval_token:" + ",".join(unknown))

    approved_set = set(approved_tokens)
    selected_rows = [
        row for row in (batch.get("rows") or [])
        if review_token(row) in approved_set
    ]
    if len(selected_rows) != len(approved_tokens):
        raise ValueError("approval_selection_count_mismatch")

    return {
        "schema_version": "leadscanner-approved-review-draft-batch/1.0",
        "draft_candidate_count": len(selected_rows),
        "review_draft_count": len(selected_rows),
        "rows": selected_rows,
        "approval": {
            "requested_count": len(approved_tokens),
            "approved_count": len(selected_rows),
            "rejected_by_operator_count": len(queue["items"]) - len(selected_rows),
            "stale_copy_policy": "reject",
            "automatic_send": False,
        },
        "safety": {
            "automatic_send": False,
            "smtp_available": False,
            "human_review_required": True,
            "changed_existing_draft_policy": "reject",
            "approval_token_required": True,
        },
    }


def _read(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("input_must_be_object")
    return data


def _write_json(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    queue_cmd = sub.add_parser("queue")
    queue_cmd.add_argument("--batch", required=True)
    queue_cmd.add_argument("--json-output", required=True)
    queue_cmd.add_argument("--markdown-output", required=True)
    queue_cmd.add_argument("--csv-output", required=True)

    select_cmd = sub.add_parser("select")
    select_cmd.add_argument("--batch", required=True)
    select_cmd.add_argument("--approved-tokens-env", default="INPUT_APPROVED_REVIEW_TOKENS")
    select_cmd.add_argument("--output", required=True)

    args = parser.parse_args()
    batch = _read(args.batch)
    if args.command == "queue":
        queue = build_review_queue(batch)
        _write_json(args.json_output, queue)
        Path(args.markdown_output).write_text(render_markdown(queue), encoding="utf-8")
        Path(args.csv_output).write_text(render_csv(queue), encoding="utf-8")
        print(
            "REVIEW_QUEUE=green "
            f"candidates={queue['review_candidate_count']} automatic_send=false"
        )
    else:
        raw = os.getenv(args.approved_tokens_env, "")
        selected = select_approved(batch, raw)
        _write_json(args.output, selected)
        print(
            "REVIEW_APPROVAL=green "
            f"approved={selected['approval']['approved_count']} "
            f"operator_rejected={selected['approval']['rejected_by_operator_count']} "
            "stale_copy_policy=reject automatic_send=false"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
