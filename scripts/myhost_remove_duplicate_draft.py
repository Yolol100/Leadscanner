from __future__ import annotations

import argparse
import json
from pathlib import Path

from myhost_draft import (
    LEAD_ID_RE,
    connect_imap,
    fetch_message,
    find_drafts_folder,
    find_message_ids,
    normalize_text,
    select_folder,
)


def remove_growth_draft(lead_id: str) -> dict:
    lead_id = str(lead_id or "").strip()
    if not LEAD_ID_RE.fullmatch(lead_id):
        raise ValueError("lead_id must be a canonical growth-<20 hex> ID")

    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        ids = find_message_ids(client, folder, lead_id)
        if len(ids) != 1:
            raise RuntimeError(f"Expected exactly one existing draft for {lead_id}, found {len(ids)}")

        actual = fetch_message(client, ids[0])
        if normalize_text(actual.get("X-Webactueel-Lead-ID", "")) != lead_id:
            raise RuntimeError("Draft lead-ID readback mismatch before removal")

        select_folder(client, folder, readonly=False)
        status, _ = client.store(ids[0], "+FLAGS", "(\\Deleted)")
        if status != "OK":
            raise RuntimeError(f"Could not mark duplicate draft deleted for {lead_id}")
        if client.expunge()[0] != "OK":
            raise RuntimeError(f"Could not expunge duplicate draft for {lead_id}")

        final_ids = find_message_ids(client, folder, lead_id)
        if final_ids:
            raise RuntimeError(f"Duplicate draft still present after removal for {lead_id}")

        return {
            "lead_id": lead_id,
            "removed_count": 1,
            "final_count": 0,
            "draft_folder": folder,
            "automatic_send": False,
            "smtp_send": "not_available",
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lead-id", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = remove_growth_draft(args.lead_id)
    Path(args.output).write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        "MYHOST_DUPLICATE_REMOVAL=green "
        f"lead_id={result['lead_id']} removed=1 final=0 "
        "automatic_send=false smtp_send=not_available"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
