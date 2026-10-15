"""User-requested one-time Drafts replacement. Never send, move, or archive mail.

Inventory stores only UIDs and hashes, not old message contents. Replacement
requires a reviewed private content hash, exactly 450 verified rows, a fresh
suppression check, exact IMAP readback and unchanged old messages. Deletion uses
UID EXPUNGE for the authorized old UID set only; global EXPUNGE is forbidden.
"""
from __future__ import annotations
import hashlib
import os
import re
import sys
from contextlib import redirect_stdout, redirect_stderr
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from io import StringIO

import review450 as batch

CONTROL = "Mailbox450Control"
CONTROL_ID = 683104996
PLAN = "Mailbox450Plan"
PLAN_ID = 683104997
PLAN_COLS = ["uid", "sha256", "draft_id", "draft_flag"]
HOST = "mail.andrewbaeten.nl"
USER = "info@andrewbaeten.nl"
MAX_MESSAGES = 5000
MAX_MESSAGE_BYTES = 2_000_000
MAX_TOTAL_BYTES = 64_000_000


def target_guard():
    if (os.getenv("OUTREACH_IMAP_HOST", HOST).strip().casefold() != HOST or
            os.getenv("OUTREACH_MAIL_USER", USER).strip().casefold() != USER or
            os.getenv("OUTREACH_SENDER_EMAIL", USER).strip().casefold() != USER):
        raise RuntimeError("mailbox_target_not_authorized")


def read_control(conn):
    values = batch.read(conn, batch.SID, CONTROL + "!A1:B30")
    if not values or values[0] != ["key", "value"]:
        raise RuntimeError("mailbox_control_headers_invalid")
    data = {}
    for row in values[1:]:
        if len(row) != 2 or row[0] in data:
            raise RuntimeError("mailbox_control_invalid")
        data[row[0]] = row[1]
    if data.get("task") != batch.TASK:
        raise RuntimeError("mailbox_control_wrong_task")
    return data


def write_control(conn, data, extra_requests=None):
    vals = [["key", "value"]] + [[k, str(v)] for k, v in data.items()]
    if len(vals) > 30:
        raise RuntimeError("mailbox_control_capacity")
    batch.post(conn, (extra_requests or []) + [batch.table_request(CONTROL_ID, vals, 2)])
    if batch.read(conn, batch.SID, CONTROL + "!A1:B30") != vals:
        raise RuntimeError("mailbox_control_readback_failed")


def uidplus(client):
    status, values = client.capability()
    if status != "OK":
        raise RuntimeError("imap_capability_unavailable")
    caps = b" ".join(v for v in values if isinstance(v, bytes)).upper().split()
    return b"UIDPLUS" in caps or b"IMAP4REV2" in caps


def select(client, folder, *, readonly=True):
    from myhost_draft import _mailbox_arg
    if client.select(_mailbox_arg(folder), readonly=readonly)[0] != "OK":
        raise RuntimeError("imap_drafts_select_failed")
    _, value = client.response("UIDVALIDITY")
    raw = value[0] if isinstance(value, (tuple, list)) and value else b""
    text = raw.decode("ascii") if isinstance(raw, bytes) else str(raw)
    if not re.fullmatch(r"[1-9][0-9]*", text):
        raise RuntimeError("imap_uidvalidity_missing")
    return text


def uidset(client):
    status, data = client.uid("SEARCH", None, "ALL")
    if status != "OK" or not isinstance(data, list):
        raise RuntimeError("imap_uid_search_failed")
    value = data[0] if data else b""
    if not isinstance(value, bytes):
        raise RuntimeError("imap_uid_search_shape")
    ids = [v.decode("ascii") for v in value.split()]
    if len(ids) > MAX_MESSAGES or len(ids) != len(set(ids)) or any(not re.fullmatch(r"[1-9][0-9]*", v) for v in ids):
        raise RuntimeError("imap_uid_list_invalid")
    return set(ids)


def metadata(client, uid):
    status, payload = client.uid("FETCH", uid, "(UID FLAGS RFC822.SIZE)")
    if status != "OK":
        raise RuntimeError("imap_metadata_failed")
    data = b" ".join(x for x in payload or [] if isinstance(x, bytes))
    mid = re.search(rb"\bUID (\d+)\b", data)
    size = re.search(rb"\bRFC822.SIZE (\d+)\b", data)
    flag = re.search(rb"\bFLAGS \(([^)]*)\)", data)
    if not mid or mid.group(1).decode() != uid or not size or not flag:
        raise RuntimeError("imap_metadata_incomplete")
    length = int(size.group(1))
    if not 0 < length <= MAX_MESSAGE_BYTES:
        raise RuntimeError("imap_message_size_unreviewable")
    return length, {x.upper() for x in flag.group(1).split()}


def fetch_message(client, uid):
    length, flags = metadata(client, uid)
    status, parts = client.uid("FETCH", uid, "(UID FLAGS BODY.PEEK[])")
    if status != "OK":
        raise RuntimeError("imap_message_read_failed")
    found = [(a,b) for a,b in (p for p in parts or [] if isinstance(p,tuple) and len(p)==2) if isinstance(b,bytes)]
    if len(found) != 1:
        raise RuntimeError("imap_message_shape_invalid")
    meta, raw = found[0]
    match = re.search(rb"\bUID (\d+)\b", meta)
    if not match or match.group(1).decode()!=uid or len(raw)!=length:
        raise RuntimeError("imap_message_readback_incomplete")
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    return {"uid":uid,"sha256":hashlib.sha256(raw).hexdigest(),"message":msg,
            "draft_id":str(msg.get("X-Webactueel-Draft-ID", "")),
            "draft_flag":b"\\DRAFT" in flags,"flags":flags,"size":length}


def scan(client):
    result = {}
    total = 0
    for uid in sorted(uidset(client),key=int):
        length,_ = metadata(client,uid)
        total += length
        if total > MAX_TOTAL_BYTES:
            raise RuntimeError("imap_inventory_size_unreviewable")
        result[uid] = fetch_message(client,uid)
    return result


def plan_values(inventory):
    return [PLAN_COLS] + [[u, r["sha256"], r["draft_id"], "yes" if r["draft_flag"] else "no"]
                          for u,r in sorted(inventory.items(),key=lambda x:int(x[0]))]


def read_plan(conn, control):
    vals = batch.read(conn,batch.SID,PLAN + "!A1:D5001")
    if not vals or vals[0]!=PLAN_COLS or batch.digest(vals)!=control.get("plan_sha256"):
        raise RuntimeError("mailbox_inventory_hash_mismatch")
    rows = {}
    for r in vals[1:]:
        if len(r)!=4 or not re.fullmatch(r"[1-9][0-9]*",r[0]) or not re.fullmatch(r"[0-9a-f]{64}",r[1]) or r[0] in rows or r[3] not in {"yes","no"}:
            raise RuntimeError("mailbox_inventory_row_invalid")
        rows[r[0]]={"sha256":r[1],"draft_id":r[2],"draft_flag":r[3]=="yes"}
    return rows


def inspect_mailbox():
    from private_candidate_handoff import authorized_writer
    from myhost_draft import connect_imap, find_drafts_folder
    target_guard()
    conn = authorized_writer()
    control = read_control(conn)
    if control.get("phase") not in {"awaiting_readonly_inventory", "inventory_ready"}:
        raise RuntimeError("cannot_resnapshot_during_replacement")
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        validity = select(client,folder)
        supported = uidplus(client)
        inventory = scan(client)
        if uidset(client)!=set(inventory):
            raise RuntimeError("mailbox_changed_during_inventory")
        vals = plan_values(inventory)
        data = {"task":batch.TASK,"phase":"inventory_ready","folder":folder,"uidvalidity":validity,
                "old_count":str(len(inventory)),"nondraft_count":str(sum(not r["draft_flag"] for r in inventory.values())),
                "uid_expunge_supported":str(supported).lower(),"plan_sha256":batch.digest(vals),
                "approved_content_sha256":"not_approved_yet","review_status":"not_reviewed",
                "inventory_at":batch.now(),"run_id":os.getenv("GITHUB_RUN_ID", ""),"stored":"0","deleted":"0","sent":"0"}
        write_control(conn,data,[batch.table_request(PLAN_ID,vals,4)])
        if batch.read(conn,batch.SID,PLAN+"!A1:D5001")!=vals:
            raise RuntimeError("mailbox_plan_readback_failed")
        return {"old_drafts":len(inventory),"unflagged":sum(not r["draft_flag"] for r in inventory.values()),"uid_expunge":supported}
    finally:
        try:
            client.logout()
        except Exception:
            pass


def validate_batch(rows, control, state):
    if len(rows)!=batch.TARGET:
        raise RuntimeError("replacement_requires_exactly_450")
    for row in rows:
        batch.validate(row)
    batch.unique(rows)
    vals = [batch.COLS] + [[r[k] for k in batch.COLS] for r in rows]
    content_hash = batch.digest(vals)
    if (control.get("approved_content_sha256") != content_hash or
            control.get("review_status") != "source_and_copy_reviewed" or
            state.get("status")!="ready_for_review" or state.get("content_sha256")!=content_hash):
        raise RuntimeError("replacement_content_not_reviewed")
    return content_hash


def verify_new(inventory, rows):
    from myhost_draft import build_message, _matches
    matches = {}
    for record in inventory.values():
        draft_id=record["draft_id"]
        if draft_id in matches:
            raise RuntimeError("duplicate_mailbox_draft_id")
        if draft_id:
            matches[draft_id]=record
    uids = set()
    for row in rows:
        actual=matches.get(row["draft_id"])
        if not actual or not actual["draft_flag"] or b"\\DELETED" in actual["flags"]:
            raise RuntimeError("replacement_draft_missing_or_wrong_flag")
        expected=build_message(row)
        if not _matches(expected,actual["message"]) or parseaddr(actual["message"].get("From",""))[1].casefold()!=USER:
            raise RuntimeError("replacement_content_readback_mismatch")
        if batch.FORBIDDEN.casefold() in str(actual["message"]).casefold():
            raise RuntimeError("removed_sentence_in_mailbox")
        uids.add(actual["uid"])
    if len(uids)!=batch.TARGET:
        raise RuntimeError("replacement_draft_count_mismatch")
    return uids


def check_old(current, plan, *, allow_missing=False):
    for uid,expected in plan.items():
        actual=current.get(uid)
        if not actual:
            if allow_missing:
                continue
            raise RuntimeError("old_draft_disappeared")
        if actual["sha256"]!=expected["sha256"] or actual["draft_flag"]!=expected["draft_flag"]:
            raise RuntimeError("old_draft_changed_do_not_delete")
        if not actual["draft_flag"]:
            raise RuntimeError("old_message_not_confirmed_as_draft")


def replace(client, folder, validity, plan, rows, *, recheck, progress):
    from myhost_draft import save_draft
    if len(rows)!=batch.TARGET or any(not r["draft_flag"] for r in plan.values()):
        raise RuntimeError("replacement_precondition_failed")
    if not uidplus(client):
        raise RuntimeError("targeted_uid_expunge_unavailable")
    if select(client,folder)!=validity:
        raise RuntimeError("uidvalidity_changed")
    current=scan(client)
    wanted={r["draft_id"] for r in rows}
    extras={u for u,r in current.items() if u not in plan and r["draft_id"] not in wanted}
    if extras:
        raise RuntimeError("concurrent_unrelated_drafts_present")
    check_old(current,plan,allow_missing=True)
    old_still_present=set(current)&set(plan)
    # Missing old UIDs can only be accepted on an idempotent deletion retry once
    # all replacements are already demonstrably present.
    if old_still_present!=set(plan):
        verify_new(current,rows)
    recheck()
    for start in range(0,len(rows),100):
        for row in rows[start:start+100]:
            save_draft(client,folder,row,selected=True)
        progress("storing",min(start+100,len(rows)),0)
    current=scan(client)
    new_uids=verify_new(current,rows)
    check_old(current,plan,allow_missing=old_still_present!=set(plan))
    old_uids=set(current)&set(plan)
    if set(current)!=new_uids|old_uids or new_uids&old_uids:
        raise RuntimeError("mailbox_uid_scope_changed")
    recheck()
    if select(client,folder,readonly=False)!=validity:
        raise RuntimeError("uidvalidity_changed_before_delete")
    # Fresh full content readback under the writable selection. Never delete a
    # concurrently changed message, a sent message, or an unrelated UID.
    final_scan=scan(client)
    if set(final_scan)!=set(current):
        raise RuntimeError("mailbox_changed_before_delete")
    verify_new(final_scan,rows)
    check_old(final_scan,plan,allow_missing=old_still_present!=set(plan))
    progress("deleting_old_drafts",len(rows),0)
    deleted=0
    ordered=sorted(old_uids,key=int)
    for start in range(0,len(ordered),100):
        block=ordered[start:start+100]
        for uid in block:
            actual=fetch_message(client,uid)
            if actual["sha256"]!=plan[uid]["sha256"] or not actual["draft_flag"]:
                raise RuntimeError("old_draft_changed_during_delete")
        values=",".join(block)
        if client.uid("STORE",values,"+FLAGS.SILENT", "(\\Deleted)")[0]!="OK":
            raise RuntimeError("old_draft_delete_flag_failed")
        # RFC 4315: only these explicit UIDs are permanently removed.
        if client.uid("EXPUNGE",values)[0]!="OK":
            raise RuntimeError("targeted_uid_expunge_failed")
        if set(block)&uidset(client):
            raise RuntimeError("old_draft_delete_readback_failed")
        deleted+=len(block)
        progress("deleting_old_drafts",len(rows),deleted)
    result=scan(client)
    if set(result)!=verify_new(result,rows) or set(result)&set(plan):
        raise RuntimeError("replacement_final_count_invalid")
    progress("completed",len(rows),len(plan))
    return {"stored":len(rows),"deleted":len(plan),"sent":0}


def install():
    from private_candidate_handoff import authorized_writer
    from registry_readonly import load_suppressions
    from dedupe_preflight import match_candidate
    from myhost_draft import connect_imap, find_drafts_folder
    target_guard()
    conn=authorized_writer()
    control=read_control(conn)
    if control.get("phase") not in {"inventory_ready","storing","deleting_old_drafts","completed"}:
        raise RuntimeError("inventory_not_ready")
    rows=batch.load_rows(conn)
    state=dict(batch.read(conn,batch.SID,batch.STATE+"!A2:B11"))
    approved=validate_batch(rows,control,state)
    plan=read_plan(conn,control)
    def recheck():
        fresh=batch.load_rows(conn)
        info=read_control(conn)
        state_now=dict(batch.read(conn,batch.SID,batch.STATE+"!A2:B11"))
        if validate_batch(fresh,info,state_now)!=approved:
            raise RuntimeError("private_rows_changed_during_install")
        registry=load_suppressions(session=conn)
        if any(match_candidate(row,registry) for row in fresh):
            raise RuntimeError("historically_suppressed_before_install")
    def progress(phase,stored,deleted):
        control.update(phase=phase,stored=str(stored),deleted=str(deleted),updated_at=batch.now(),
                       run_id=os.getenv("GITHUB_RUN_ID", ""),sent="0")
        write_control(conn,control)
    recheck()
    client=connect_imap()
    try:
        folder=find_drafts_folder(client)
        if folder!=control.get("folder"):
            raise RuntimeError("drafts_folder_changed")
        return replace(client,folder,control["uidvalidity"],plan,rows,recheck=recheck,progress=progress)
    finally:
        # LOGOUT only. CLOSE may implicitly expunge; never use it here.
        try:
            client.logout()
        except Exception:
            pass


def main():
    phase=os.getenv("MAILBOX450_PHASE", "")
    if phase not in {"inspect","install"} or os.getenv("MAILBOX450_TASK")!=batch.TASK:
        print("MAILBOX450=blocked unauthorized_phase sent=0")
        return 1
    try:
        with redirect_stdout(StringIO()),redirect_stderr(StringIO()):
            result=inspect_mailbox() if phase=="inspect" else install()
        if phase=="inspect":
            print("MAILBOX450=inventory old={} unflagged={} targeted_delete={} sent=0".format(
                result["old_drafts"],result["unflagged"],result["uid_expunge"]))
        else:
            print("MAILBOX450=green stored={} deleted={} sent=0".format(result["stored"],result["deleted"]))
        return 0
    except Exception as exc:
        # Fixed in-program error labels only, never server messages or private data.
        reason=str(exc)
        if not re.fullmatch(r"[a-z][a-z0-9_]{3,80}",reason):
            reason="private_mailbox_operation_unverified"
        print("MAILBOX450=blocked reason={} sent=0".format(reason))
        return 1


if __name__=="__main__":
    sys.exit(main())
