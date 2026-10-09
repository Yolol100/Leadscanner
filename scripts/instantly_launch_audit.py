"""Read-only private-data-safe go-live inventory for Webactueel Instantly.

Exports no recipient addresses, sender emails, email copy, credentials or full
provider responses. Names and IDs of campaigns are operationally necessary to
distinguish safe targets from unrelated historical campaigns.
"""
from __future__ import annotations

from collections import Counter

from instantly_language_campaigns import read_imported_leads
from instantly_client import InstantlyError
from myhost_instantly_import import blocked_values

TARGETS = {
    "nl": "5c720281-fd07-4c47-8155-c88d7d3c09b8",
    "en": "fd405145-4bf5-40c5-b6ae-2e7f5af6120c",
}
MAX_CAMPAIGNS = 100
MAX_ACCOUNT_RECORDS = 100


def _text(value: object) -> str:
    return str(value or "").strip()


def _list_pages(fetch, *, limit: int) -> list[dict]:
    rows, cursor, seen = [], None, set()
    for _ in range(20):
        response = fetch(cursor)
        if not isinstance(response, dict) or not isinstance(response.get("items"), list):
            raise RuntimeError("inventory_page_shape_invalid")
        items = response["items"]
        if any(not isinstance(item, dict) for item in items):
            raise RuntimeError("inventory_page_invalid_row")
        rows.extend(items)
        if len(rows) > limit:
            raise RuntimeError("inventory_over_limit")
        cursor = _text(response.get("next_starting_after"))
        if not cursor:
            return rows
        if cursor in seen or not items:
            raise RuntimeError("inventory_page_cursor_invalid")
        seen.add(cursor)
    raise RuntimeError("inventory_page_limit_reached")


def _campaign_count(client, campaign_id: str) -> int:
    count, cursor, seen = 0, None, set()
    for _ in range(50):
        raw = client.list_leads(campaign=campaign_id, limit=100, starting_after=cursor)
        if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
            raise RuntimeError("campaign_leads_page_invalid")
        rows = raw["items"]
        if any(not isinstance(x, dict) for x in rows):
            raise RuntimeError("campaign_leads_row_invalid")
        count += len(rows)
        if count > 5000:
            raise RuntimeError("campaign_leads_over_limit")
        cursor = _text(raw.get("next_starting_after"))
        if not cursor:
            return count
        if cursor in seen or not rows:
            raise RuntimeError("campaign_leads_cursor_invalid")
        seen.add(cursor)
    raise RuntimeError("campaign_leads_page_limit")


def _permission_counts(leads: list[dict]) -> dict:
    counts = Counter()
    for row in leads:
        val = row.get("payload")
        if not isinstance(val, dict):
            val = row.get("custom_variables")
        if not isinstance(val, dict):
            counts["missing_metadata"] += 1
            continue
        basis = _text(val.get("leadscanner_contact_basis"))
        ref = _text(val.get("leadscanner_contact_basis_ref"))
        if basis in {"consent_verified", "existing_customer_related_verified"} and len(ref) >= 8:
            counts["documented_eligible"] += 1
        else:
            counts["unverified_or_review_required"] += 1
    return dict(counts)


def audit_launch_inventory(client, *, source: bool = True) -> dict:
    campaigns = _list_pages(lambda cursor: client.list_campaigns(limit=100, starting_after=cursor), limit=MAX_CAMPAIGNS)
    seen_ids = set()
    summarized = []
    for item in campaigns:
        cid = _text(item.get("id"))
        if not cid or cid in seen_ids:
            raise RuntimeError("campaign_inventory_invalid_identity")
        seen_ids.add(cid)
        observed = client.get_campaign(cid)
        if not isinstance(observed, dict) or _text(observed.get("id")) != cid:
            raise RuntimeError("campaign_inventory_readback_mismatch")
        summarized.append({
            "id": cid,
            "name": _text(observed.get("name"))[:160],
            "status": observed.get("status"),
            "sender_count": len(observed.get("email_list") or []),
            "lead_count": _campaign_count(client, cid),
            "target": cid in set(TARGETS.values()),
        })
    accounts = _list_pages(
        lambda cursor: client._request(
            "GET", "/accounts",
            params={"limit":100, **({"starting_after":cursor} if cursor else {})},
            retry_safe=True,
        ),
        limit=MAX_ACCOUNT_RECORDS,
    )
    status = Counter()
    sample_field_names = set()
    account_ids = set()
    for acc in accounts:
        name = _text(acc.get("email")).casefold()
        if not name or name in account_ids:
            raise RuntimeError("account_inventory_missing_or_duplicate")
        account_ids.add(name)
        stat = acc.get("status")
        key = str(stat) if type(stat) is int else "unknown"
        status[key] += 1
        for field in acc:
            if field in {"warmup_status", "warmup_health_score", "health_score",
                         "timestamp_warmup_started", "daily_limit", "daily_campaign_limit",
                         "warmup", "status", "status_message"}:
                sample_field_names.add(field)

    blocklist = {"state":"unavailable_fail_closed"}
    try:
        blocked = blocked_values(client)
        blocklist = {"state":"ok", "entry_count":len(blocked)}
    except InstantlyError as exc:
        err = str(exc)
        status_code = err.removeprefix("instantly_api_error status=")
        blocklist = {
            "state":"unavailable_fail_closed",
            "http_status":int(status_code) if status_code.isdigit() and len(status_code) == 3 else None,
        }

    report = {
        "schema_version":"leadscanner-launch-inventory/1.0",
        "campaign_count":len(summarized),
        "campaigns":summarized,
        "target_ids": TARGETS,
        "other_campaign_count":sum(not row["target"] for row in summarized),
        "account_count":len(accounts),
        "active_account_count":status["1"],
        "account_status_counts":dict(status),
        "account_readiness_fields_available":sorted(sample_field_names),
        "account_health_and_domain_not_yet_verified":True,
        "blocklist":blocklist,
        "source_contact_basis":None,
        "source_lead_count":None,
        "no_automatic_send":True,
        "contains_email_addresses":False,
        "go_live_approved":False,
        "old_campaign_delete_approved":False,
    }
    if source:
        _, leads = read_imported_leads(client)
        report["source_contact_basis"] = _permission_counts(leads)
        report["source_lead_count"] = len(leads)
    return report
