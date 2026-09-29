from __future__ import annotations

import argparse
import json
from collections import Counter
from email.utils import getaddresses
from pathlib import Path

from myhost_draft import LEAD_ID_RE, connect_imap, fetch_message, find_drafts_folder, select_folder


def inventory_growth_drafts() -> dict:
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        select_folder(client, folder, readonly=True)
        status, data = client.search(None, "ALL")
        if status != "OK":
            raise RuntimeError("Could not inventory mijn.host drafts")
        lead_counts: Counter[str] = Counter()
        email_counts: Counter[str] = Counter()
        for message_id in (data[0] if data else b"").split():
            msg = fetch_message(client, message_id)
            lead_id = str(msg.get("X-Webactueel-Lead-ID", "")).strip()
            if LEAD_ID_RE.fullmatch(lead_id):
                lead_counts[lead_id] += 1
                for _, address in getaddresses([str(msg.get("To", ""))]):
                    normalized = address.strip().casefold()
                    if normalized:
                        email_counts[normalized] += 1
        ids = sorted(lead_counts)
        emails = sorted(email_counts)
        duplicate_ids = sorted(value for value, count in lead_counts.items() if count > 1)
        duplicate_emails = sorted(value for value, count in email_counts.items() if count > 1)
        return {
            "growth_draft_count": len(ids),
            "growth_physical_draft_count": sum(lead_counts.values()),
            "growth_lead_ids": ids,
            "growth_emails": emails,
            "duplicate_growth_lead_ids": duplicate_ids,
            "duplicate_growth_emails": duplicate_emails,
            "draft_folder": folder,
            "safety": {
                "read_only": True,
                "draft_created": False,
                "draft_deleted": False,
                "smtp_send": "not_available",
                "duplicates_detected": bool(duplicate_ids or duplicate_emails),
            },
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = inventory_growth_drafts()
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "MYHOST_GROWTH_INVENTORY=green "
        f"growth_drafts={result['growth_draft_count']} "
        f"physical_growth_drafts={result['growth_physical_draft_count']} "
        f"duplicate_lead_ids={len(result['duplicate_growth_lead_ids'])} "
        f"duplicate_emails={len(result['duplicate_growth_emails'])} "
        "read_only=true smtp_send=not_available"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
