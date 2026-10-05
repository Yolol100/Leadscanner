from __future__ import annotations

import argparse
import json
from pathlib import Path

ALLOWED_ACTIONS = {
    "list_folders",
    "list_messages",
    "search",
    "read",
    "read_attachment",
    "read_attachment_chunk",
    "read_body_chunk",
    "thread",
    "create_folder",
    "rename_folder",
    "delete_folder",
    "mark_read",
    "mark_unread",
    "flag",
    "unflag",
    "copy",
    "move",
    "archive",
    "trash",
    "junk",
    "delete",
    "create_draft",
    "replace_draft",
    "send",
    "reply",
    "reply_all",
    "forward",
    "send_draft",
    "audit_growth_skips",
}
SEND_ACTIONS = {"send", "reply", "reply_all", "forward", "send_draft"}
DESTRUCTIVE_ACTIONS = {"delete", "delete_folder", "replace_draft"}
MAX_REQUEST_BYTES = 262_144
MAX_ERROR_CHARS = 1_000


def load_request(path: Path) -> dict:
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("mailbox request is empty or exceeds 256 KiB")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("mailbox request must be a JSON object")
    return data


def validate_request(request: dict) -> str:
    action = str(request.get("action") or "").strip()
    if action not in ALLOWED_ACTIONS:
        raise ValueError("mailbox action is not allowed")
    if action in SEND_ACTIONS and request.get("confirm_send") is not True:
        raise ValueError("send-like mailbox actions require confirm_send=true")
    if action in DESTRUCTIVE_ACTIONS and request.get("confirm") is not True:
        raise ValueError("destructive mailbox actions require confirm=true")
    return action


def audit_growth_skips() -> dict:
    from myhost_naturalize_drafts import (
        _bulk_fetch_messages,
        _bulk_index_growth_headers,
        connect_imap,
        find_drafts_folder,
        plain_body,
        rewrite_row_from_message,
        select_folder,
        single_recipient,
    )

    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        select_folder(client, folder, readonly=True)
        status, data = client.search(
            None,
            "HEADER",
            "X-Webactueel-Review-Required",
            '"contact-basis"',
        )
        if status != "OK":
            raise RuntimeError("Could not inventory mijn.host Growth review drafts")

        indexed = _bulk_index_growth_headers(
            client,
            list((data[0] if data else b"").split()),
        )
        by_lead: dict[str, list[bytes]] = {}
        for lead_id, message_id in indexed:
            by_lead.setdefault(lead_id, []).append(message_id)
        duplicates = [lead_id for lead_id, ids in by_lead.items() if len(ids) != 1]
        if duplicates:
            raise RuntimeError(f"Duplicate Growth draft detected for {duplicates[0]}")

        indexed.sort(key=lambda item: item[0])
        message_ids = [message_id for _, message_id in indexed]
        originals = _bulk_fetch_messages(client, message_ids) if message_ids else {}

        skipped: list[dict] = []
        for lead_id, message_id in indexed:
            msg = originals[message_id]
            try:
                rewrite_row_from_message(msg)
            except ValueError as exc:
                if str(exc) != "unsupported existing Dutch verified opening":
                    raise
                skipped.append(
                    {
                        "lead_id": lead_id,
                        "to": single_recipient(msg),
                        "subject": str(msg.get("Subject", "")).strip(),
                        "body_text": plain_body(msg),
                        "review_required": str(
                            msg.get("X-Webactueel-Review-Required", "")
                        ).strip(),
                    }
                )

        return {
            "draft_folder": folder,
            "review_growth_total": len(indexed),
            "skipped_count": len(skipped),
            "skipped": skipped,
            "read_only": True,
            "smtp_send": "not_available",
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


def execute_request(request: dict) -> dict:
    action = validate_request(request)
    try:
        if action == "audit_growth_skips":
            result = audit_growth_skips()
        else:
            import myhost_mailbox
            result = myhost_mailbox.execute(request)
        if not isinstance(result, dict):
            raise RuntimeError("mailbox engine returned an invalid result")
        return {"ok": True, "action": action, "result": result}
    except Exception as exc:
        message = str(exc).replace("\r", " ").replace("\n", " ")[:MAX_ERROR_CHARS]
        return {
            "ok": False,
            "action": action,
            "error": {
                "type": exc.__class__.__name__,
                "message": message,
            },
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    request = load_request(Path(args.request))
    action = validate_request(request)
    result = execute_request(request)
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        "MAILBOX_BRIDGE_EXECUTION=green "
        f"action={action} ok={'true' if result.get('ok') else 'false'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
