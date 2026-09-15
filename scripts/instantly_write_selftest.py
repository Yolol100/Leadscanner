from __future__ import annotations

import argparse
import json
import uuid
from typing import Any

from instantly_bridge import InstantlyClient, InstantlyError


class SelfTestError(RuntimeError):
    pass


def _not_found(exc: Exception) -> bool:
    return "HTTP 404" in str(exc)


def _safe_delete(client: InstantlyClient, path: str) -> bool:
    try:
        client.request("DELETE", path)
        return True
    except InstantlyError as exc:
        return _not_found(exc)


def run_write_selftest(client: InstantlyClient) -> dict[str, Any]:
    marker = uuid.uuid4().hex[:12]
    list_id = ""
    lead_id = ""
    list_created = False
    lead_created = False
    readback_verified = False
    lead_cleanup = False
    list_cleanup = False

    try:
        created_list = client.request(
            "POST",
            "/lead-lists",
            body={
                "name": f"Webactueel Bridge Self Test {marker}",
                "has_enrichment_task": False,
            },
        ) or {}
        list_id = str(created_list.get("id") or "").strip()
        if not list_id:
            raise SelfTestError("lead list creation returned no id")
        list_created = True

        add_result = client.request(
            "POST",
            "/leads/add",
            body={
                "list_id": list_id,
                "verify_leads_on_import": False,
                "leads": [
                    {
                        "first_name": "Webactueel",
                        "last_name": f"BridgeTest-{marker}",
                        "custom_variables": {"webactueel_test_marker": marker},
                    }
                ],
            },
        ) or {}
        if int(add_result.get("leads_uploaded", 0)) != 1:
            raise SelfTestError("Instantly did not confirm exactly one uploaded test lead")
        created_leads = add_result.get("created_leads") or []
        if len(created_leads) != 1:
            raise SelfTestError("Instantly did not return exactly one created test lead")
        lead_id = str(created_leads[0].get("id") or "").strip()
        if not lead_id:
            raise SelfTestError("created test lead returned no id")
        lead_created = True

        readback = client.request("GET", f"/leads/{lead_id}") or {}
        if str(readback.get("first_name") or "") != "Webactueel":
            raise SelfTestError("test lead readback did not match first_name")
        if str(readback.get("last_name") or "") != f"BridgeTest-{marker}":
            raise SelfTestError("test lead readback did not match last_name")
        custom = readback.get("custom_variables") or {}
        if str(custom.get("webactueel_test_marker") or "") != marker:
            raise SelfTestError("test lead readback did not match marker")
        readback_verified = True

    finally:
        if lead_id:
            lead_cleanup = _safe_delete(client, f"/leads/{lead_id}")
        if list_id:
            list_cleanup = _safe_delete(client, f"/lead-lists/{list_id}")

        if lead_id:
            try:
                client.request("GET", f"/leads/{lead_id}")
            except InstantlyError as exc:
                if _not_found(exc):
                    lead_cleanup = True
        if list_id:
            try:
                client.request("GET", f"/lead-lists/{list_id}")
            except InstantlyError as exc:
                if _not_found(exc):
                    list_cleanup = True

    if not all((list_created, lead_created, readback_verified, lead_cleanup, list_cleanup)):
        raise SelfTestError("write self-test or cleanup was not fully verified")

    return {
        "status": "green",
        "command": "write-self-test",
        "mode": "isolated_write_test",
        "list_created": True,
        "lead_created": True,
        "readback_verified": True,
        "lead_cleanup": True,
        "list_cleanup": True,
        "email_used": False,
        "send_permission": "none",
        "activation_invoked": False,
    }


def _write_report(path: str, data: dict[str, Any]) -> None:
    if not path:
        return
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated Instantly write/readback/cleanup self-test")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    import os

    try:
        result = run_write_selftest(InstantlyClient(os.getenv("INSTANTLY_API_KEY", "")))
        _write_report(args.report, result)
        print(
            "INSTANTLY_WRITE_SELFTEST=green "
            "list_created=true lead_created=true readback_verified=true "
            "lead_cleanup=true list_cleanup=true email_used=false "
            "send_permission=none activation_invoked=false"
        )
        return 0
    except (InstantlyError, SelfTestError, ValueError, OSError) as exc:
        result = {
            "status": "blocked",
            "command": "write-self-test",
            "detail": str(exc),
            "email_used": False,
            "send_permission": "none",
            "activation_invoked": False,
        }
        _write_report(args.report, result)
        print(
            "INSTANTLY_WRITE_SELFTEST=blocked "
            f"detail={exc} email_used=false send_permission=none activation_invoked=false"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
