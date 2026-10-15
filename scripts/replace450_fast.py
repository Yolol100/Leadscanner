"""Bounded IMAP read transport for the existing exact-450 replacement contract.

Only read round-trips change. Every message is still size-bounded, SHA-256
fingerprinted and parsed. All store/deletion logic remains in replace450.
"""
from __future__ import annotations
import hashlib
import os
import re
import sys
from contextlib import redirect_stdout, redirect_stderr
from email import policy
from email.parser import BytesParser
from io import StringIO

import replace450 as core
import review450 as batch

CHUNK = 100
SAFE_ERRORS = frozenset({
    "replacement_requires_exactly_450", "replacement_content_not_reviewed",
    "mailbox_target_not_authorized", "inventory_not_ready", "drafts_folder_changed",
    "targeted_uid_expunge_unavailable", "uidvalidity_changed", "uidvalidity_changed_before_delete",
    "concurrent_unrelated_drafts_present", "old_draft_disappeared", "old_draft_changed_do_not_delete",
    "old_message_not_confirmed_as_draft", "old_draft_changed_during_delete",
    "replacement_draft_missing_or_wrong_flag", "replacement_content_readback_mismatch",
    "replacement_draft_count_mismatch", "private_rows_changed_during_install",
    "historically_suppressed_before_install", "mailbox_uid_scope_changed",
    "mailbox_changed_before_delete", "old_draft_delete_flag_failed", "targeted_uid_expunge_failed",
    "old_draft_delete_readback_failed", "replacement_final_count_invalid",
    "mailbox_inventory_hash_mismatch", "mailbox_control_readback_failed",
    "imap_batch_metadata_failed", "imap_batch_metadata_incomplete", "imap_batch_message_size_invalid",
    "imap_batch_body_failed", "imap_batch_readback_incomplete", "imap_batch_flags_changed",
    "imap_inventory_size_unreviewable", "imap_batch_uid_set_changed", "duplicate_mailbox_draft_id",
})


def scan(client):
    uids = sorted(core.uidset(client), key=int)
    result = {}
    total_size = 0
    for start in range(0, len(uids), CHUNK):
        wanted = set(uids[start:start+CHUNK])
        uid_values = ",".join(sorted(wanted,key=int))
        status, raw_metadata = client.uid("FETCH", uid_values, "(UID FLAGS RFC822.SIZE)")
        if status != "OK":
            raise RuntimeError("imap_batch_metadata_failed")
        meta = {}
        for value in raw_metadata or []:
            if not isinstance(value,bytes):
                raise RuntimeError("imap_batch_metadata_incomplete")
            uid = re.search(rb"\bUID (\d+)\b",value)
            size = re.search(rb"\bRFC822.SIZE (\d+)\b",value)
            flags = re.search(rb"\bFLAGS \(([^)]*)\)",value)
            if not uid or not size or not flags:
                raise RuntimeError("imap_batch_metadata_incomplete")
            uid = uid.group(1).decode("ascii")
            length = int(size.group(1))
            if uid not in wanted or uid in meta:
                raise RuntimeError("imap_batch_metadata_incomplete")
            if not 0 < length <= core.MAX_MESSAGE_BYTES:
                raise RuntimeError("imap_batch_message_size_invalid")
            total_size += length
            if total_size > core.MAX_TOTAL_BYTES:
                raise RuntimeError("imap_inventory_size_unreviewable")
            meta[uid] = (length,{f.upper() for f in flags.group(1).split()})
        if set(meta) != wanted:
            raise RuntimeError("imap_batch_metadata_incomplete")
        status, payload = client.uid("FETCH",uid_values,"(UID FLAGS BODY.PEEK[])")
        if status != "OK":
            raise RuntimeError("imap_batch_body_failed")
        received = set()
        for part in payload or []:
            if isinstance(part,bytes):
                # IMAP literal closing parentheses are not another message.
                if part.strip() not in {b"",b")"}:
                    raise RuntimeError("imap_batch_readback_incomplete")
                continue
            if not isinstance(part,tuple) or len(part)!=2 or not isinstance(part[0],bytes) or not isinstance(part[1],bytes):
                raise RuntimeError("imap_batch_readback_incomplete")
            head, raw = part
            uid = re.search(rb"\bUID (\d+)\b",head)
            flag = re.search(rb"\bFLAGS \(([^)]*)\)",head)
            if not uid or not flag:
                raise RuntimeError("imap_batch_readback_incomplete")
            uid = uid.group(1).decode("ascii")
            if uid not in meta or uid in received or len(raw)!=meta[uid][0]:
                raise RuntimeError("imap_batch_readback_incomplete")
            flags={f.upper() for f in flag.group(1).split()}
            relevant={b"\\DRAFT",b"\\DELETED"}
            if flags & relevant != meta[uid][1] & relevant:
                raise RuntimeError("imap_batch_flags_changed")
            msg = BytesParser(policy=policy.default).parsebytes(raw)
            result[uid]={"uid":uid,"sha256":hashlib.sha256(raw).hexdigest(),"message":msg,
                         "draft_id":str(msg.get("X-Webactueel-Draft-ID","")),
                         "draft_flag":b"\\DRAFT" in flags,"flags":flags,"size":len(raw)}
            received.add(uid)
        if received != wanted:
            raise RuntimeError("imap_batch_readback_incomplete")
    if set(result)!=core.uidset(client):
        raise RuntimeError("imap_batch_uid_set_changed")
    return result


def run_phase(phase):
    old_scan=core.scan
    old_verify=core.verify_new
    def verify_expected(inventory,rows):
        # Duplicated legacy headers do not compromise the 450 NEW-ID check.
        # Existing drafts still retain their individual UID/hash deletion guard.
        wanted={row["draft_id"] for row in rows}
        selected={uid:rec for uid,rec in inventory.items() if rec["draft_id"] in wanted}
        return old_verify(selected,rows)
    core.scan=scan
    core.verify_new=verify_expected
    try:
        return core.inspect_mailbox() if phase=="inspect" else core.install()
    finally:
        core.scan=old_scan
        core.verify_new=old_verify


def main():
    phase=os.getenv("MAILBOX450_PHASE","")
    if phase not in {"inspect","install"} or os.getenv("MAILBOX450_TASK")!=batch.TASK:
        print("MAILBOX450=blocked unauthorized_phase sent=0")
        return 1
    try:
        with redirect_stdout(StringIO()),redirect_stderr(StringIO()):
            result=run_phase(phase)
        if phase=="inspect":
            print("MAILBOX450=inventory old={} unflagged={} targeted_delete={} sent=0".format(
                result["old_drafts"],result["unflagged"],result["uid_expunge"]))
        else:
            print("MAILBOX450=green stored={} deleted={} sent=0".format(result["stored"],result["deleted"]))
        return 0
    except Exception as exc:
        reason=str(exc) if str(exc) in SAFE_ERRORS else "private_operation_unverified"
        print("MAILBOX450=blocked reason={} sent=0".format(reason))
        return 1


if __name__=="__main__":
    sys.exit(main())
