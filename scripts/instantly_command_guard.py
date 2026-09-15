from __future__ import annotations

import argparse
import json
from typing import Any

from instantly_api_v2 import confirmation_token, normalize_path


def needs_exact_confirmation(method: str, path: str, operation_id: str = "") -> bool:
    method = (method or "").upper().strip()
    path = normalize_path(path)
    operation = (operation_id or "").lower()
    if method in {"GET"}:
        return False
    if method == "DELETE":
        return True

    # Changes to AI agents can immediately alter prospecting, approvals, replies,
    # credit usage or deliverability behavior when an agent is active.
    if path.startswith("/api/v2/ai-agents/"):
        return True

    # Adding/moving leads can start live outreach when the destination campaign
    # is active, so the generic admin route must never treat these as routine.
    lead_markers = (
        "/api/v2/leads/add",
        "/api/v2/leads/move",
        "/api/v2/leads/update-interest-status",
        "/api/v2/leads/bulk-assign",
        "/api/v2/leads/subsequence/",
    )
    if any(path.startswith(marker) for marker in lead_markers):
        return True
    if path == "/api/v2/leads" and method == "POST":
        return True

    # Editing or controlling a campaign can affect already queued sends.
    campaign_markers = (
        "activatecampaign",
        "pausecampaign",
        "patchcampaign",
        "addvariables",
        "sharecampaign",
        "createfromexport",
        "resumesubsequence",
        "pausesubsequence",
        "patchcampaignsubsequence",
    )
    if any(marker in operation for marker in campaign_markers):
        return True

    # Webhooks can send workspace event data to an external destination.
    if path.startswith("/api/v2/webhooks") and method != "GET":
        return True

    # Access-control and workspace membership changes are administrative writes.
    if path.startswith("/api/v2/workspace-members") or path.startswith(
        "/api/v2/workspace-group-members"
    ):
        return True

    return False


def guard_request(request: dict[str, Any], *, operation_id: str = "") -> dict[str, Any]:
    method = str(request.get("method") or "").upper().strip()
    path = str(request.get("path") or "").strip()
    apply = bool(request.get("apply", False))
    query = request.get("query") if isinstance(request.get("query"), dict) else {}
    body = request.get("body")
    normalized_path = normalize_path(path)
    token = confirmation_token(method, normalized_path, query, body if body is not None else {})
    sensitive = needs_exact_confirmation(method, normalized_path, operation_id)

    if sensitive and apply and str(request.get("confirmation") or "").strip() != token:
        raise ValueError("exact confirmation token is required by the Webactueel high-impact guard")

    return {
        "status": "green",
        "high_impact_guard": sensitive,
        "confirmation_token": token,
        "apply": apply,
        "method": method,
        "path": normalized_path,
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
