from __future__ import annotations

import argparse
import json
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
        ids: list[str] = []
        for message_id in (data[0] if data else b"").split():
            msg = fetch_message(client, message_id)
            lead_id = str(msg.get("X-Webactueel-Lead-ID", "")).strip()
            if LEAD_ID_RE.fullmatch(lead_id) and lead_id not in ids:
                ids.append(lead_id)
        ids.sort()
        return {
            "growth_draft_count": len(ids),
            "growth_lead_ids": ids,
            "draft_folder": folder,
            "safety": {
                "read_only": True,
                "draft_created": False,
                "draft_deleted": False,
                "smtp_send": "not_available",
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
        "read_only=true smtp_send=not_available"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
