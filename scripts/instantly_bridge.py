from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable

API_BASE = "https://api.instantly.ai/api/v2"
SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,180}$")
CAMPAIGN_STATUS = {
    -99: "account_suspended",
    -2: "bounce_protect",
    -1: "accounts_unhealthy",
    0: "draft",
    1: "active",
    2: "paused",
    3: "completed",
    4: "running_subsequences",
}
SAFE_CAMPAIGN_WRITE_STATUSES = {0, 2}
TERMINAL_FIELDS = (
    "sent_at",
    "followup_sent_at",
    "message_id",
    "followup_message_id",
    "reply_at",
    "bounce_at",
)


class InstantlyError(RuntimeError):
    pass


@dataclass(frozen=True)
class SyncResult:
    target: int
    existing: int
    submitted: int
    final_readback: int
    mode: str
    destination_type: str
    destination_status: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "status": "green",
            "mode": self.mode,
            "destination_type": self.destination_type,
            "destination_status": self.destination_status,
            "target": self.target,
            "existing": self.existing,
            "submitted": self.submitted,
            "final_readback": self.final_readback,
            "send_permission": "none",
            "activation_invoked": False,
        }


class InstantlyClient:
    def __init__(self, api_key: str, *, base_url: str = API_BASE, timeout: float = 30.0):
        api_key = (api_key or "").strip()
        if not api_key:
            raise InstantlyError("INSTANTLY_API_KEY is required")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        if not path.startswith("/"):
            raise ValueError("API path must start with /")
        url = self.base_url + path
        if query:
            clean_query = {key: value for key, value in query.items() if value not in (None, "")}
            if clean_query:
                url += "?" + urllib.parse.urlencode(clean_query)
        payload = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": "webactueel-leadscanner/instantly-bridge",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=payload, method=method.upper(), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise InstantlyError(f"Instantly API HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise InstantlyError("Instantly API connection failed") from exc
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InstantlyError("Instantly API returned invalid JSON") from exc

    def connection_test(self) -> dict[str, int]:
        campaigns = self.request("GET", "/campaigns", query={"limit": 1}) or {}
        lists = self.request("GET", "/lead-lists", query={"limit": 1}) or {}
        return {
            "campaign_probe": len(campaigns.get("items", [])),
            "lead_list_probe": len(lists.get("items", [])),
        }

    def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        return self.request("GET", f"/campaigns/{_require_uuidish(campaign_id, 'campaign_id')}")

    def list_leads_for_contacts(
        self,
        *,
        contacts: list[str],
        campaign_id: str = "",
        list_id: str = "",
    ) -> list[dict[str, Any]]:
        if bool(campaign_id) == bool(list_id):
            raise ValueError("provide exactly one destination")
        if not contacts:
            return []
        body: dict[str, Any] = {
            "contacts": contacts,
            "limit": min(100, max(1, len(contacts))),
        }
        if campaign_id:
            body["campaign"] = _require_uuidish(campaign_id, "campaign_id")
        else:
            body["list_id"] = _require_uuidish(list_id, "list_id")
        response = self.request("POST", "/leads/list", body=body) or {}
        return list(response.get("items", []))

    def add_leads(
        self,
        leads: list[dict[str, Any]],
        *,
        campaign_id: str = "",
        list_id: str = "",
    ) -> Any:
        if bool(campaign_id) == bool(list_id):
            raise ValueError("provide exactly one destination")
        if not leads:
            return None
        if len(leads) > 1000:
            raise ValueError("Instantly bulk add supports at most 1000 leads")
        body: dict[str, Any] = {"leads": leads}
        if campaign_id:
            body["campaign_id"] = _require_uuidish(campaign_id, "campaign_id")
        else:
            body["list_id"] = _require_uuidish(list_id, "list_id")
        return self.request("POST", "/leads/add", body=body)


def _require_uuidish(value: str, field: str) -> str:
    value = (value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{8,80}", value):
        raise ValueError(f"{field} is invalid")
    return value


def _normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def _load_selected_ids(path: str, expected_count: int) -> tuple[str, ...]:
    if expected_count < 1 or expected_count > 100:
        raise ValueError("expected_count must be between 1 and 100")
    if not path:
        raise ValueError("lead-id file is required")
    with open(path, encoding="utf-8") as handle:
        lead_ids = tuple(line.strip() for line in handle if line.strip())
    if len(lead_ids) != expected_count:
        raise ValueError(f"expected {expected_count} lead IDs; found {len(lead_ids)}")
    if len(set(lead_ids)) != len(lead_ids):
        raise ValueError("lead IDs contain duplicates")
    if any(not SAFE_ID.fullmatch(lead_id) for lead_id in lead_ids):
        raise ValueError("lead IDs contain unsupported characters")
    return lead_ids


def _select_rows(values: list[list[str]], lead_ids: Iterable[str]) -> list[dict[str, str]]:
    from outreach_queue_imap_draft import rows_from_values

    rows = rows_from_values(values)
    by_id: dict[str, dict[str, str]] = {}
    for row in rows:
        lead_id = (row.get("lead_id") or "").strip()
        if lead_id:
            if lead_id in by_id:
                raise InstantlyError("OutreachQueue contains duplicate lead_id")
            by_id[lead_id] = row
    selected = []
    for lead_id in lead_ids:
        if lead_id not in by_id:
            raise InstantlyError("selected lead_id is missing from OutreachQueue")
        selected.append(by_id[lead_id])
    emails = [_normalize_email(row.get("email", "")) for row in selected]
    if any("@" not in email for email in emails):
        raise InstantlyError("selected row has invalid email")
    if len(set(emails)) != len(emails):
        raise InstantlyError("selected rows contain duplicate emails")
    return selected


def load_validated_rows(spreadsheet_id: str, lead_ids: tuple[str, ...]) -> list[dict[str, str]]:
    from outreach_queue_imap_draft import (
        QUEUE_SHEET,
        SUPPRESSION_SHEET,
        build_sheets_service,
        get_values,
        suppression_sets,
        validate_queue_row,
    )

    if not (spreadsheet_id or "").strip():
        raise InstantlyError("OUTREACH_SPREADSHEET_ID is required")
    service = build_sheets_service()
    rows = _select_rows(get_values(service, spreadsheet_id, QUEUE_SHEET), lead_ids)
    suppressed_emails, suppressed_domains = suppression_sets(
        get_values(service, spreadsheet_id, SUPPRESSION_SHEET)
    )
    failures: list[str] = []
    for row in rows:
        errors = validate_queue_row(
            row,
            sender_email="",
            suppressed_emails=suppressed_emails,
            suppressed_domains=suppressed_domains,
        )
        if errors:
            failures.append((row.get("lead_id") or "unknown").strip())
    if failures:
        raise InstantlyError("selected rows failed the Leads validation gate")
    return rows


def _first_nonempty(row: dict[str, str], *fields: str) -> str:
    for field in fields:
        value = (row.get(field) or "").strip()
        if value:
            return value
    return ""


def row_to_instantly_lead(row: dict[str, str]) -> dict[str, Any]:
    email = _normalize_email(row.get("email", ""))
    if "@" not in email:
        raise InstantlyError("selected row has invalid email")
    payload: dict[str, Any] = {"email": email}
    optional = {
        "website": _first_nonempty(row, "website", "url", "official_website"),
        "first_name": _first_nonempty(row, "first_name", "contact_first_name"),
        "last_name": _first_nonempty(row, "last_name", "contact_last_name"),
        "company_name": _first_nonempty(row, "company_name", "company", "business_name"),
        "job_title": _first_nonempty(row, "job_title", "contact_role"),
        "phone": _first_nonempty(row, "phone", "telephone"),
    }
    payload.update({key: value for key, value in optional.items() if value})
    custom_variables: dict[str, Any] = {
        "webactueel_lead_id": (row.get("lead_id") or "").strip(),
    }
    offer = _first_nonempty(row, "offer_type", "agent_type")
    if offer:
        custom_variables["webactueel_offer_type"] = offer
    payload["custom_variables"] = custom_variables
    return payload


def _existing_contacts(items: Iterable[dict[str, Any]]) -> set[str]:
    return {
        _normalize_email(str(item.get("email", "")))
        for item in items
        if _normalize_email(str(item.get("email", "")))
    }


def sync_rows(
    client: InstantlyClient,
    rows: list[dict[str, str]],
    *,
    campaign_id: str = "",
    list_id: str = "",
    apply: bool = False,
) -> SyncResult:
    if bool(campaign_id) == bool(list_id):
        raise ValueError("provide exactly one destination")
    destination_status = ""
    if campaign_id:
        campaign = client.get_campaign(campaign_id)
        status = int(campaign.get("status"))
        destination_status = CAMPAIGN_STATUS.get(status, f"unknown_{status}")
        if status not in SAFE_CAMPAIGN_WRITE_STATUSES:
            raise InstantlyError("campaign must be draft or paused before lead synchronization")
    leads = [row_to_instantly_lead(row) for row in rows]
    contacts = [lead["email"] for lead in leads]
    existing_items = client.list_leads_for_contacts(
        contacts=contacts,
        campaign_id=campaign_id,
        list_id=list_id,
    )
    existing = _existing_contacts(existing_items)
    to_add = [lead for lead in leads if lead["email"] not in existing]
    if not apply:
        return SyncResult(
            target=len(leads),
            existing=len(existing & set(contacts)),
            submitted=0,
            final_readback=len(existing & set(contacts)),
            mode="dry_run",
            destination_type="campaign" if campaign_id else "lead_list",
            destination_status=destination_status,
        )
    if to_add:
        client.add_leads(to_add, campaign_id=campaign_id, list_id=list_id)
    readback_items = client.list_leads_for_contacts(
        contacts=contacts,
        campaign_id=campaign_id,
        list_id=list_id,
    )
    readback = _existing_contacts(readback_items)
    final_count = len(readback & set(contacts))
    if final_count != len(contacts):
        raise InstantlyError("Instantly readback did not confirm every selected lead")
    return SyncResult(
        target=len(leads),
        existing=len(existing & set(contacts)),
        submitted=len(to_add),
        final_readback=final_count,
        mode="apply",
        destination_type="campaign" if campaign_id else "lead_list",
        destination_status=destination_status,
    )


def _write_report(path: str, data: dict[str, Any]) -> None:
    if not path:
        return
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe Instantly API v2 bridge for Leadscanner")
    parser.add_argument(
        "--command",
        required=True,
        choices=["connection-test", "campaign-status", "sync-selected-to-list", "sync-selected-to-campaign"],
    )
    parser.add_argument("--lead-id-file", default="")
    parser.add_argument("--expected-count", type=int, default=0)
    parser.add_argument("--list-id", default="")
    parser.add_argument("--campaign-id", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    try:
        client = InstantlyClient(os.getenv("INSTANTLY_API_KEY", ""))
        if args.command == "connection-test":
            probe = client.connection_test()
            result = {
                "status": "green",
                "command": args.command,
                "campaign_probe": probe["campaign_probe"],
                "lead_list_probe": probe["lead_list_probe"],
                "send_permission": "none",
                "activation_invoked": False,
            }
        elif args.command == "campaign-status":
            campaign = client.get_campaign(args.campaign_id)
            status = int(campaign.get("status"))
            result = {
                "status": "green",
                "command": args.command,
                "campaign_status": CAMPAIGN_STATUS.get(status, f"unknown_{status}"),
                "safe_for_staging": status in SAFE_CAMPAIGN_WRITE_STATUSES,
                "send_permission": "none",
                "activation_invoked": False,
            }
        else:
            lead_ids = _load_selected_ids(args.lead_id_file, args.expected_count)
            rows = load_validated_rows(os.getenv("OUTREACH_SPREADSHEET_ID", ""), lead_ids)
            if args.command == "sync-selected-to-list":
                sync = sync_rows(client, rows, list_id=args.list_id, apply=args.apply)
            else:
                sync = sync_rows(client, rows, campaign_id=args.campaign_id, apply=args.apply)
            result = {"command": args.command, **sync.public_dict()}
        _write_report(args.report, result)
        print(
            "INSTANTLY_BRIDGE=green "
            f"command={args.command} mode={result.get('mode', 'read_only')} "
            f"target={result.get('target', 0)} submitted={result.get('submitted', 0)} "
            f"final_readback={result.get('final_readback', 0)} "
            f"destination_status={result.get('destination_status', result.get('campaign_status', ''))} "
            "send_permission=none activation_invoked=false"
        )
        return 0
    except (InstantlyError, ValueError, OSError) as exc:
        result = {
            "status": "blocked",
            "command": args.command,
            "detail": str(exc),
            "send_permission": "none",
            "activation_invoked": False,
        }
        _write_report(args.report, result)
        print(
            "INSTANTLY_BRIDGE=blocked "
            f"command={args.command} detail={exc} "
            "send_permission=none activation_invoked=false"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
