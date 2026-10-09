"""Retire exactly one paused historical campaign while preserving its one lead.

Never send. Never delete on uncertain copy or history. No lead addresses or
email content appear in GitHub results. Safe to replay only as a NEW command:
existing archive readback prevents duplicate copies before deletion.
"""
from __future__ import annotations
import re
import time

from instantly_client import InstantlyError

CAMPAIGN_ID="827b1b45-6a7e-45ba-88de-d89db2a47d6a"
CAMPAIGN_NAME="Outreach NL - Website & Digitale Diensten"
ARCHIVE_NAME="Webactueel - Oud Campagne Archief - NIET VERZENDEN"


def _text(x):
    return str(x or "").strip()


def _single_campaign_lead(client):
    r=client.list_leads(campaign=CAMPAIGN_ID,limit=100)
    if not isinstance(r,dict) or not isinstance(r.get("items"),list):
        raise RuntimeError("archive_source_lead_list_invalid")
    if len(r["items"])!=1 or r.get("next_starting_after"):
        raise ValueError("archive_requires_exactly_one_lead")
    lead=r["items"][0]
    if not isinstance(lead,dict) or not re.fullmatch(r"[0-9a-fA-F-]{36}",_text(lead.get("id"))):
        raise ValueError("archive_source_lead_id_invalid")
    if "@" not in _text(lead.get("email")):
        raise ValueError("archive_source_lead_email_invalid")
    return lead


def _history_is_empty(client):
    result=client.get_emails(campaign_id=CAMPAIGN_ID,received_only=False,limit=1)
    if not isinstance(result,dict) or not isinstance(result.get("items"),list):
        raise RuntimeError("archive_email_history_unknown")
    return not result["items"] and not result.get("next_starting_after")


def _target_ready(client):
    campaign=client.get_campaign(CAMPAIGN_ID)
    if not isinstance(campaign,dict) or _text(campaign.get("id"))!=CAMPAIGN_ID:
        raise RuntimeError("archive_campaign_identity_changed")
    if campaign.get("name")!=CAMPAIGN_NAME or type(campaign.get("status")) is not int or campaign["status"]!=2:
        raise ValueError("archive_requires_exact_paused_campaign")
    if not _history_is_empty(client):
        raise ValueError("archive_campaign_has_email_history")
    return _single_campaign_lead(client)


def _archive_list(client):
    seen=set()
    cursor=None
    matches=[]
    for _ in range(20):
        params={"limit":100}
        if cursor:
            params["starting_after"]=cursor
        response=client._request("GET","/lead-lists",params=params,retry_safe=True)
        if not isinstance(response,dict) or not isinstance(response.get("items"),list):
            raise RuntimeError("archive_list_page_invalid")
        for row in response["items"]:
            if not isinstance(row,dict):
                raise RuntimeError("archive_list_entry_invalid")
            if row.get("name")==ARCHIVE_NAME:
                matches.append(_text(row.get("id")))
        cursor=_text(response.get("next_starting_after"))
        if not cursor:
            break
        if cursor in seen:
            raise RuntimeError("archive_list_cursor_loop")
        seen.add(cursor)
    else:
        raise RuntimeError("archive_list_page_limit")
    if len(matches)>1 or any(not re.fullmatch(r"[0-9a-fA-F-]{36}",x) for x in matches):
        raise RuntimeError("archive_list_ambiguous")
    if matches:
        return matches[0],False
    # Post outcome unknown must never be retried automatically.
    created=client._request("POST","/lead-lists",json={"name":ARCHIVE_NAME})
    id=_text(created.get("id")) if isinstance(created,dict) else ""
    if not re.fullmatch(r"[0-9a-fA-F-]{36}",id):
        raise RuntimeError("archive_list_create_unknown")
    got=client._request("GET","/lead-lists/"+id,retry_safe=True)
    if not isinstance(got,dict) or got.get("name")!=ARCHIVE_NAME or _text(got.get("id"))!=id:
        raise RuntimeError("archive_list_readback_failed")
    return id,True


def _archive_leads(client,list_id,email):
    response=client.list_leads(list_id=list_id,contacts=[email],limit=100)
    if not isinstance(response,dict) or not isinstance(response.get("items"),list):
        raise RuntimeError("archive_readback_page_invalid")
    items=[
        x for x in response["items"] if isinstance(x,dict)
        and _text(x.get("email")).casefold()==email
        and _text(x.get("list_id"))==list_id
    ]
    if response.get("next_starting_after") or len(items)>1:
        raise RuntimeError("archive_lead_identity_ambiguous")
    return items


def _wait_job(client,id,*,sleep_fn=time.sleep):
    for index in range(25):
        v=client._request("GET","/background-jobs/"+id,retry_safe=True)
        if not isinstance(v,dict):
            raise RuntimeError("archive_job_response_invalid")
        state=_text(v.get("status")).casefold()
        if state in {"completed","success"}:
            return
        if state in {"failed","error"}:
            raise RuntimeError("archive_copy_failed")
        if state not in {"pending","in_progress","queued","running","processing","created",""}:
            raise RuntimeError("archive_job_unknown_state")
        if index<24:
            sleep_fn(1)
    raise RuntimeError("archive_copy_unconfirmed")


def archive_and_retire_old_campaign(client) -> dict:
    lead=_target_ready(client)
    email=_text(lead["email"]).casefold()
    list_id,created=_archive_list(client)
    stored=_archive_leads(client,list_id,email)
    copied=False
    if not stored:
        # Safety: recheck old campaign immediately before copying, never blindly retry POST.
        current=_target_ready(client)
        if _text(current["id"])!=_text(lead["id"]) or _text(current["email"]).casefold()!=email:
            raise RuntimeError("archive_source_changed_prewrite")
        move={
            "campaign":CAMPAIGN_ID,"to_list_id":list_id,
            "ids":[lead["id"]],"copy_leads":True,"reset_interest_status":False
        }
        job=client._request("POST","/leads/move",json=move)
        job_id=_text((job or {}).get("id") or (job or {}).get("job_id")) if isinstance(job,dict) else ""
        if not re.fullmatch(r"[0-9a-fA-F-]{36}",job_id):
            raise RuntimeError("archive_copy_job_missing_id")
        _wait_job(client,job_id)
        copied=True
    stored=_archive_leads(client,list_id,email)
    if len(stored)!=1:
        raise RuntimeError("archive_missing_confirmed_copy")
    original_vars=lead.get("payload") if isinstance(lead.get("payload"),dict) else lead.get("custom_variables")
    stored_vars=stored[0].get("payload") if isinstance(stored[0].get("payload"),dict) else stored[0].get("custom_variables")
    if isinstance(original_vars,dict) and (not isinstance(stored_vars,dict) or any(stored_vars.get(k)!=v for k,v in original_vars.items())):
        raise RuntimeError("archive_custom_fields_changed")
    still=_target_ready(client)
    if _text(still["id"])!=_text(lead["id"]) or _text(still["email"]).casefold()!=email:
        raise RuntimeError("archive_source_changed_before_delete")
    client._request("DELETE","/campaigns/"+CAMPAIGN_ID)
    try:
        after=client.get_campaign(CAMPAIGN_ID)
    except InstantlyError as exc:
        if str(exc)!="instantly_api_error status=404":
            raise
        after=None
    if after is not None:
        raise RuntimeError("archive_old_campaign_still_exists")
    return {
        "schema_version":"leadscanner-old-campaign-retirement/1.0",
        "old_campaign_id":CAMPAIGN_ID,
        "archive_list_name":ARCHIVE_NAME,
        "archive_list_id":list_id,
        "archive_created":created,
        "source_leads_archived":1,
        "lead_copied_on_this_run":copied,
        "old_campaign_deleted":True,
        "original_messages_present":False,
        "email_sent":False,
        "contains_personal_data":False,
    }
