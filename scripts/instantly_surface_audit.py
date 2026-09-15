from __future__ import annotations

import argparse
import json
import re
from typing import Any, Mapping

from instantly_api_v2 import HTTP_METHODS, OPENAPI_URL, load_openapi

SURFACE_RULES: dict[str, tuple[str, ...]] = {
    "campaigns": ("campaign",),
    "leads": ("/leads", "lead"),
    "lead_lists": ("leadlist", "lead-lists"),
    "email_accounts": ("emailaccount", "/accounts"),
    "emails": ("/emails", "email"),
    "analytics": ("analytics",),
    "custom_tags": ("customtag", "custom-tags"),
    "workspace": ("workspace",),
    "workspace_members": ("workspacemember", "workspace/members", "members"),
    "blocklist": ("blocklist",),
    "webhooks": ("webhook",),
    "audit_logs": ("auditlog", "audit-log"),
    "supersearch": ("supersearch",),
    "inbox_placement": ("inboxplacement", "inbox-placement"),
    "website_visitors": ("websitevisitor", "website-visitors"),
    "ai_agents": ("aisalesagent", "aiagent", "ai-agent"),
    "instantly_ai_memory": ("savedmemory", "customerprofile", "businessdetails", "guidance"),
    "instantly_ai_tasks": ("instantlyaitask", "copilottask"),
    "automations": ("automation",),
    "crm_calls": ("/calls", "crmcall"),
    "crm_sms": ("/sms", "crmsms"),
    "crm_tasks": ("/tasks", "crmtask"),
}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9/]+", "", value.lower())


def operation_index(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path, item in (spec.get("paths") or {}).items():
        if not isinstance(item, Mapping):
            continue
        for method, operation in item.items():
            if method.upper() not in HTTP_METHODS or not isinstance(operation, Mapping):
                continue
            rows.append(
                {
                    "method": method.upper(),
                    "path": str(path),
                    "operation_id": str(operation.get("operationId") or ""),
                    "tags": [str(tag) for tag in (operation.get("tags") or [])],
                    "summary": str(operation.get("summary") or ""),
                }
            )
    return rows


def _matches(row: Mapping[str, Any], terms: tuple[str, ...]) -> bool:
    haystack = _norm(
        " ".join(
            [
                str(row.get("path") or ""),
                str(row.get("operation_id") or ""),
                " ".join(str(tag) for tag in (row.get("tags") or [])),
                str(row.get("summary") or ""),
            ]
        )
    )
    return any(_norm(term) in haystack for term in terms)


def audit(spec: Mapping[str, Any]) -> dict[str, Any]:
    rows = operation_index(spec)
    surfaces: dict[str, Any] = {}
    for surface, terms in SURFACE_RULES.items():
        matched = [row for row in rows if _matches(row, terms)]
        methods = sorted({row["method"] for row in matched})
        if not matched:
            control = "not_proven"
        elif any(method != "GET" for method in methods):
            control = "read_write"
        else:
            control = "read_only"
        surfaces[surface] = {
            "control": control,
            "operation_count": len(matched),
            "methods": methods,
            "operations": matched,
        }
    return {
        "status": "green",
        "source": OPENAPI_URL,
        "operation_count": len(rows),
        "surfaces": surfaces,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit which Instantly UI/product surfaces are proven by the current official API v2 schema"
    )
    parser.add_argument("--report", default="")
    parser.add_argument("--require", action="append", default=[])
    args = parser.parse_args()

    spec = load_openapi()
    result = audit(spec)
    missing = [
        name
        for name in args.require
        if result["surfaces"].get(name, {}).get("control") == "not_proven"
    ]
    if missing:
        result["status"] = "blocked"
        result["missing_required_surfaces"] = missing
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 2 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
