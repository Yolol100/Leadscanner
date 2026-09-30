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
from myhost_invalid_draft_baselines import (
    load_expected_versions,
    version_matches_message,
)


def remove_growth_draft(lead_id: str, expected_versions: list[dict]) -> dict:
    lead_id = str(lead_id or "").strip()
    if not LEAD_ID_RE.fullmatch(lead_id):
        raise ValueError("lead_id must be a canonical growth-<20 hex> ID")
    if not expected_versions:
        raise ValueError("exact expected draft versions are required before removal")

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
            raise RuntimeError(f"Expected at most one existing draft for {lead_id}, found {len(ids)}")

        actual = fetch_message(client, ids[0])
        if not any(version_matches_message(actual, lead_id, version) for version in expected_versions):
            raise RuntimeError(f"Current exact draft version mismatch before removal for {lead_id}")

        select_folder(client, folder, readonly=False)
        current_ids = find_message_ids(client, folder, lead_id, ensure_selected=False)
        if current_ids != ids:
            raise RuntimeError(f"Draft changed during removal preflight for {lead_id}")
        actual = fetch_message(client, current_ids[0])
        if not any(version_matches_message(actual, lead_id, version) for version in expected_versions):
            raise RuntimeError(f"Current exact draft version mismatch immediately before removal for {lead_id}")

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
    parser.add_argument("--expected-file", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    expected_versions = load_expected_versions(args.expected_file, args.lead_id)
    result = remove_growth_draft(args.lead_id, expected_versions)
    Path(args.output).write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        "MYHOST_DUPLICATE_REMOVAL=green "
        f"lead_id={result['lead_id']} removed={result['removed_count']} final=0 "
        "automatic_send=false smtp_send=not_available"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
