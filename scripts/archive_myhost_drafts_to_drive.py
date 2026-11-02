"""One-time private archive of current Mijn.Host Drafts: read IMAP, write Drive.

Never APPEND, STORE, EXPUNGE, SMTP, or publicly disclose mailbox identities.
Run only after explicit owner authorization and a verified private Drive target.
"""
from __future__ import annotations

import io
import json
import os
import re
import zipfile

import draft_management as draft
from drive_existing_private_archive import ExistingPrivateArchive
from myhost_draft import connect_imap, find_drafts_folder


def snapshot_current_drafts(client, folder):
    validity, inventory = draft._scope(client, folder)
    if not inventory:
        raise RuntimeError("draft_archive_empty_inventory")
    records = []
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for uid in sorted(inventory, key=int):
            item = inventory[uid]
            # Preserve every current Drafts-folder message exactly, even if
            # its IMAP Draft flag is missing or its Deleted flag is present.
            # These flags stay private in the manifest and never authorize
            # later replacement or deletion.
            raw = draft._raw_snapshot(client, uid, item["sha256"])
            name = "originals/uid-" + uid + ".eml"
            archive.writestr(name, raw)
            records.append({
                "uid": uid, "sha256": item["sha256"],
                "draft_id": item["draft_id"], "name": name,
                "flags": sorted(flag.decode("ascii") for flag in item["flags"]),
            })
        manifest = {
            "format": "webactueel-mijnhost-mime-archive-v1",
            "status": "complete",
            "folder": folder, "uidvalidity": validity,
            "messages": len(records), "records": records,
            "draft_flagged": sum(item["draft_flag"] for item in inventory.values()),
            "deleted_flagged": sum(b"\\DELETED" in item["flags"]
                                   for item in inventory.values()),
            "modified": 0, "sent": 0,
        }
        archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
    return stream.getvalue(), validity, inventory


def run(*, connector=connect_imap, archive=None):
    draft.imap.target_guard()
    archive = archive or ExistingPrivateArchive(
        os.getenv("OUTREACH_DRIVE_ARCHIVE_FILE_ID", ""),
        os.getenv("OUTREACH_DRIVE_ARCHIVE_FOLDER_ID", ""))
    original = archive.read_bytes()
    with zipfile.ZipFile(io.BytesIO(original)) as src:
        previous = json.loads(src.read("manifest.json"))
    if previous["status"] != "empty-bootstrap":
        return {"state": "archive_already_populated", "modified": 0, "sent": 0}
    client = connector()
    try:
        folder = find_drafts_folder(client)
        payload, validity, before = snapshot_current_drafts(client, folder)
        fresh_validity, after = draft._scope(client, folder)
        if fresh_validity != validity or set(after) != set(before):
            raise RuntimeError("draft_archive_mailbox_changed")
        draft._assert_untouched(before, after)
        archive.replace_empty_with(payload)
        final_validity, final = draft._scope(client, folder)
        if final_validity != validity or set(final) != set(before):
            raise RuntimeError("draft_archive_mailbox_changed_after_store")
        draft._assert_untouched(before, final)
        return {"state": "archived_and_readback_verified",
                "messages": len(before), "modified": 0, "sent": 0}
    finally:
        try:
            client.logout()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        result = run()
        print("PRIVATE_DRAFT_ARCHIVE={} stored={} modified=0 sent=0".format(
            result["state"], result.get("messages", 0)))
    except Exception as exc:
        # Never disclose arbitrary exception text, message bytes, credentials,
        # mailbox addresses, URLs or stack traces to public Actions logs.
        raw = str(exc)
        reason = raw if re.fullmatch(
            r"(?:archive|draft|drive|imap|mailbox|snapshot)_[a-z0-9_]{3,72}",
            raw) else "private_operation_unverified"
        print("PRIVATE_DRAFT_ARCHIVE=blocked reason={} modified=0 sent=0".format(reason))
        raise SystemExit(1) from None
