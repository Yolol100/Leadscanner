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


def execute_request(request: dict) -> dict:
    action = validate_request(request)
    try:
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
