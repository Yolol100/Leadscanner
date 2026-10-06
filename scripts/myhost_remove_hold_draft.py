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


def remove_hold_draft(lead_id: str, *, expected_snapshot: dict | None = None) -> dict:
    lead_id = str(lead_id or "").strip()
    if not LEAD_ID_RE.fullmatch(lead_id):
        raise ValueError("lead_id must be a canonical growth-<20 hex> ID")

    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        ids = find_message_ids(client, folder, lead_id)
        if not ids:
            return {
                "lead_id": lead_id,
                "removed_count": 0,
                "final_count": 0,
                "draft_folder": folder,
                "automatic_send": False,
                "smtp_send": "not_available",
            }
        if len(ids) != 1:
            raise RuntimeError(
                f"Expected at most one hold draft for {lead_id}, found {len(ids)}"
            )

        actual = fetch_message(client, ids[0])
        if normalize_text(actual.get("X-Webactueel-Lead-ID", "")) != lead_id:
            raise RuntimeError(
                f"Current draft lead identity mismatch for {lead_id}"
            )
        if (
            normalize_text(
                actual.get("X-Webactueel-Review-Required", "")
            )
            != "contact-basis"
        ):
            raise RuntimeError(
                f"Current draft is not review-required for {lead_id}"
            )

        select_folder(client, folder, readonly=False)
        current_ids = find_message_ids(
            client,
            folder,
            lead_id,
            ensure_selected=False,
        )
        if current_ids != ids:
            raise RuntimeError(
                f"Draft changed during hold-removal preflight for {lead_id}"
            )
        actual = fetch_message(client, current_ids[0])
        if normalize_text(actual.get("X-Webactueel-Lead-ID", "")) != lead_id:
            raise RuntimeError(
                f"Current draft lead identity changed for {lead_id}"
            )
        if (
            normalize_text(
                actual.get("X-Webactueel-Review-Required", "")
            )
            != "contact-basis"
        ):
            raise RuntimeError(
                f"Current draft review status changed for {lead_id}"
            )

        if expected_snapshot is not None:
            from myhost_draft import plain_body
            current = {
                "lead_id": lead_id,
                "to": normalize_text(actual.get("To", "")),
                "subject": normalize_text(actual.get("Subject", "")),
                "body": plain_body(actual),
                "review_status": normalize_text(actual.get("X-Webactueel-Review-Required", "")),
                "actual_lead_id": normalize_text(actual.get("X-Webactueel-Lead-ID", "")),
                "count": 1, "duplicate": False,
            }
            if current != expected_snapshot:
                raise RuntimeError(f"Current hold draft changed since exact audit for {lead_id}")

        status, _ = client.store(
            current_ids[0],
            "+FLAGS",
            "(\\Deleted)",
        )
        if status != "OK":
            raise RuntimeError(
                f"Could not mark hold draft deleted for {lead_id}"
            )
        if client.expunge()[0] != "OK":
            raise RuntimeError(
                f"Could not expunge hold draft for {lead_id}"
            )

        final_ids = find_message_ids(client, folder, lead_id)
        if final_ids:
            raise RuntimeError(
                f"Hold draft still present after removal for {lead_id}"
            )

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

    result = remove_hold_draft(args.lead_id)
    Path(args.output).write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        "MYHOST_HOLD_REMOVAL=green "
        f"lead_id={result['lead_id']} removed={result['removed_count']} final=0 "
        "automatic_send=false smtp_send=not_available"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

