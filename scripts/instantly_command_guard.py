from __future__ import annotations

import argparse
import json
from typing import Any

from instantly_api_v2 import (
    confirmation_token,
    load_openapi,
    match_operation,
    normalize_path,
    requires_high_impact_confirmation,
)


def needs_exact_confirmation(method: str, path: str, operation_id: str = "") -> bool:
    """Compatibility wrapper around the executor's single high-impact policy."""
    return requires_high_impact_confirmation(method, path, operation_id)


def guard_request(
    request: dict[str, Any],
    *,
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    method = str(request.get("method") or "").upper().strip()
    path = str(request.get("path") or "").strip()
    apply = bool(request.get("apply", False))
    query = request.get("query") if isinstance(request.get("query"), dict) else {}
    body = request.get("body")
    normalized_path = normalize_path(path)

    live_spec = spec if spec is not None else load_openapi()
    operation = match_operation(live_spec, method, normalized_path)
    token = confirmation_token(method, normalized_path, query, body if body is not None else {})
    sensitive = operation.risk in {"destructive", "high_impact"}

    if sensitive and apply and str(request.get("confirmation") or "").strip() != token:
        raise ValueError("exact confirmation token is required by the Webactueel high-impact guard")

    return {
        "status": "green",
        "high_impact_guard": sensitive,
        "confirmation_token": token,
        "apply": apply,
        "method": method,
        "path": normalized_path,
        "operation_id": operation.operation_id,
        "template_path": operation.template_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed guard for sensitive Instantly writes")
    parser.add_argument("--request-json", required=True)
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    try:
        with open(args.request_json, encoding="utf-8") as handle:
            request = json.load(handle)
        if not isinstance(request, dict):
            raise ValueError("request JSON must be an object")
        result = guard_request(request)
        if args.report:
            with open(args.report, "w", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2, sort_keys=True)
                handle.write("\n")
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        blocked = {"status": "blocked", "detail": str(exc)}
        if args.report:
            with open(args.report, "w", encoding="utf-8") as handle:
                json.dump(blocked, handle, indent=2, sort_keys=True)
                handle.write("\n")
        print(json.dumps(blocked, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())