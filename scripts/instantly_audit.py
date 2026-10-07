#!/usr/bin/env python3
"""Deterministic static audit for the repository-native Instantly control plane."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _read(root: Path, relative: str) -> str:
    return (root / relative).read_text(encoding="utf-8")


def evaluate(root: str | Path = ".") -> dict:
    root = Path(root)
    workflow_files = sorted((root / ".github" / "workflows").glob("*.yml"))
    workflow = _read(root, ".github/workflows/leads-cold.yml")
    client = _read(root, "scripts/instantly_client.py")
    control = _read(root, "scripts/instantly_control.py")
    service = _read(root, "scripts/instantly_service.py")
    sync = _read(root, "scripts/instantly_sync.py")
    webhook = _read(root, "scripts/instantly_webhook.py")
    config = json.loads(_read(root, "config/instantly-control.json"))

    checks = [
        {
            "name": "single_active_workflow",
            "ok": [path.name for path in workflow_files] == ["leads-cold.yml"],
        },
        {
            "name": "approval_and_live_dedupe_boundary",
            "ok": (
                all(token in service for token in (
                    "resolve_exact_approval",
                    "revalidate_approved",
                    "approved_lead_no_longer_eligible",
                    "check_registry_access",
                    "update_registry",
                ))
                and "match_candidate" in client
                and "Phase 21 - Revalidate approved leads against live registry" in workflow
                and "approval_revalidation.py" in workflow
                and "approved-current-batch.json" in workflow
                and "fresh_registry_rows = fetch_live_registry" in service
                and "approved_lead_no_longer_eligible_after_registry_preflight" in service
            ),
        },
        {
            "name": "allowlisted_immutable_commands",
            "ok": all(token in control for token in (
                "ALL_ACTIONS = READ_ACTIONS | WRITE_ACTIONS",
                "unsupported_instantly_action",
                "write_commands_cannot_run_on_workflow_rerun",
                "exact_confirmation_required",
            )) and "arbitrary_http" not in control.casefold(),
        },
        {
            "name": "safe_read_retry_without_write_retry",
            "ok": (
                "retry_safe: bool = False" in client
                and 'retry_safe=True' in client
                and 'return self._request("POST", "/leads", json=payload)' in client
                and "body={response.text" not in client
            ),
        },
        {
            "name": "activation_preflight",
            "ok": (
                "/sending-status" in control
                and "activation_requires_all_sender_accounts_active" in control
                and "activation_requires_verified_leads_only" in control
                and "activation_sending_status_all_accounts_unhealthy" in control
                and 'lead.get("verification_status") != 1' in control
            ),
        },
        {
            "name": "async_mutation_readback",
            "ok": (
                "_wait_background_job" in control
                and "_wait_interest_status" in control
                and "interest_lead_email_required" in control
                and "interest_value_required" in control
                and "completion_state" in control
                and "warmup_{verb}_readback_mismatch" in control
                and "account_{verb}_readback_mismatch" in control
            ),
        },
        {
            "name": "stale_event_and_registry_race_protection",
            "ok": (
                "stale_event_ignored" in webhook
                and "webhook_timestamp_invalid" in webhook
                and "registry_event_fresh_read_failed" in webhook
                and "fresh_values" in webhook
                and "TERMINAL_STATUSES" in webhook
            ),
        },
        {
            "name": "secret_and_artifact_hygiene",
            "ok": (
                "command_secret_material_forbidden" in control
                and "_redact_sensitive" in control
                and "[REDACTED]" in control
                and "instantly_api_error status=" in client
                and "response.text" not in client
                and "GITHUB_REPOSITORY_PRIVATE" not in control
                and "GITHUB_REPOSITORY_PRIVATE" not in workflow
                and "reply_body_required" in control
                and "forward_body_or_original_required" in control
                and "test_body_required" in control
            ),
        },
        {
            "name": "workflow_reliability_and_sync_safety",
            "ok": (
                "cancel-in-progress: false" in workflow
                and "immutable_instantly_command_modified_or_deleted" in workflow
                and workflow.count("group: leadscanner-instantly-registry") == 2
                and '"automatic_send": False' in sync
                and '"instantly_mutation": False' in sync
                and '"creates_registry_identity": False' in sync
                and config.get("require_exact_confirmation") is True
            ),
        },
    ]
    passed = sum(1 for check in checks if check["ok"])
    return {
        "schema_version": "leadscanner-instantly-static-audit/1.0",
        "status": "green" if passed == len(checks) else "red",
        "static_score": f"{passed}/{len(checks)}",
        "checks": checks,
        "runtime_point_requires_ci_and_live_smoke": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = evaluate(args.root)
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
