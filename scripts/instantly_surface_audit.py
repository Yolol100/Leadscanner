from __future__ import annotations

import argparse
import json
import re
from typing import Any, Mapping

from instantly_api_v2 import HTTP_METHODS, OPENAPI_URL, load_openapi

# Surface rules are intentionally narrow. The purpose of this audit is to prove
# a visible Instantly surface is controllable, not to inflate coverage through
# fuzzy substring matches.
SURFACE_RULES: dict[str, dict[str, tuple[str, ...]]] = {
    "campaigns": {"tags": ("Campaign", "CampaignSubsequence")},
    "leads": {"tags": ("Lead",)},
    "lead_labels": {"tags": ("LeadLabel",)},
    "lead_lists": {"tags": ("LeadList",)},
    "email_accounts": {"tags": ("Account",)},
    "emails_unibox": {"tags": ("Email",)},
    "analytics_reports": {
        "tags": ("Analytics", "InboxPlacementAnalytics"),
        "path_contains": ("/analytics", "warmup-analytics"),
    },
    "custom_tags": {"tags": ("CustomTag", "CustomTagMapping")},
    "workspace": {"tags": ("Workspace",)},
    "workspace_billing": {"tags": ("WorkspaceBilling",)},
    "workspace_members": {"tags": ("WorkspaceMember", "WorkspaceGroupMember")},
    "blocklist": {"tags": ("BlockListEntry",)},
    "webhooks": {"tags": ("Webhook", "WebhookEvent")},
    "audit_logs": {"tags": ("AuditLog",)},
    "api_keys": {"tags": ("APIKey",)},
    "supersearch": {"tags": ("SuperSearchEnrichment", "CompanyList")},
    "supersearch_saved_searches": {
        "path_contains": ("/supersearch-enrichment/saved-searches",),
    },
    "inbox_placement": {
        "tags": (
            "InboxPlacementTest",
            "InboxPlacementAnalytics",
            "InboxPlacementBlacklistAndSpamAssassinReport",
        )
    },
    "website_visitors": {
        "tags": ("WebsiteVisitor", "WebsiteVisitors"),
        "path_contains": ("/website-visitors", "/website-visitor"),
    },
    "ai_agents": {
        "tags": (
            "AISalesAgent",
            "AIInboxManager",
            "AILeadFinderAgent",
            "AIDeliverabilityAgent",
            "EngageItem",
        )
    },
    "ai_sales_agent": {"tags": ("AISalesAgent",)},
    "ai_sales_guidance": {
        "path_contains": ("/ai-agents/sales/", "/guidance-rules"),
        "require_all_path_terms": ("/ai-agents/sales/", "/guidance-rules"),
    },
    "ai_inbox_manager": {"tags": ("AIInboxManager",)},
    "ai_inbox_guidance": {
        "path_contains": ("/ai-agents/inbox-manager/", "/guidances"),
        "require_all_path_terms": ("/ai-agents/inbox-manager/", "/guidances"),
    },
    "ai_lead_finder": {"tags": ("AILeadFinderAgent",)},
    "ai_deliverability_agent": {"tags": ("AIDeliverabilityAgent",)},
    "instantly_ai_business_details": {
        "path_contains": ("/business-details", "/business-info"),
        "operation_contains": ("businessdetails", "businessinfo"),
    },
    "instantly_ai_customer_profiles": {
        "path_contains": ("/customer-profiles", "/customer-profile"),
        "operation_contains": ("customerprofile",),
    },
    "instantly_ai_saved_memories": {
        "path_contains": ("/saved-memories", "/saved-memory"),
        "operation_contains": ("savedmemory",),
    },
    "instantly_ai_tasks": {
        "path_contains": ("/instantly-ai/tasks", "/copilot/tasks", "/ai-tasks"),
        "operation_contains": ("copilottask", "instantlyaitask"),
    },
    "instantly_ai_chats": {
        "path_contains": ("/instantly-ai/chats", "/copilot/chats", "/ai-chats"),
        "operation_contains": ("copilotchat", "instantlyaichat"),
    },
    "automations": {"tags": ("Automation",), "path_contains": ("/automations",)},
    "crm_opportunities": {"tags": ("Opportunity",), "path_contains": ("/opportunities",)},
    "crm_calls": {"tags": ("CRMCall", "Call"), "path_contains": ("/calls",)},
    "crm_sms": {"tags": ("CRMSMS", "SMS"), "path_contains": ("/sms",)},
    "crm_tasks": {"tags": ("CRMTask",), "path_contains": ("/crm/tasks",)},
    "preferences": {"tags": ("Preference", "Preferences"), "path_contains": ("/preferences",)},
}

READISH_POST_PREFIXES = (
    "get",
    "list",
    "count",
    "preview",
    "search",
    "test",
    "check",
    "suggest",
    "download",
    "signal",
    "facet",
)


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


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


def _matches(row: Mapping[str, Any], rule: Mapping[str, tuple[str, ...]]) -> bool:
    path = str(row.get("path") or "").lower()
    operation = _norm(str(row.get("operation_id") or ""))
    tags = {str(tag) for tag in (row.get("tags") or [])}

    required_path_terms = tuple(term.lower() for term in rule.get("require_all_path_terms", ()))
    if required_path_terms:
        return all(term in path for term in required_path_terms)

    if tags.intersection(rule.get("tags", ())):
        return True
    if any(term.lower() in path for term in rule.get("path_contains", ())):
        return True
    if any(_norm(term) in operation for term in rule.get("operation_contains", ())):
        return True
    return False


def _mutates(row: Mapping[str, Any]) -> bool:
    method = str(row.get("method") or "").upper()
    if method == "GET":
        return False
    if method in {"PATCH", "PUT", "DELETE"}:
        return True
    operation = str(row.get("operation_id") or "").lower()
    if method == "POST" and operation.startswith(READISH_POST_PREFIXES):
        return False
    return method == "POST"


def audit(spec: Mapping[str, Any]) -> dict[str, Any]:
    rows = operation_index(spec)
    surfaces: dict[str, Any] = {}
    for surface, rule in SURFACE_RULES.items():
        matched = [row for row in rows if _matches(row, rule)]
        methods = sorted({row["method"] for row in matched})
        mutating = [row for row in matched if _mutates(row)]
        if not matched:
            control = "not_proven"
        elif mutating:
            control = "read_write"
        else:
            control = "read_only"
        surfaces[surface] = {
            "control": control,
            "operation_count": len(matched),
            "methods": methods,
            "write_operation_count": len(mutating),
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
