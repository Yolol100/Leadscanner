"""Replace a small number of scope-rejected prospects before final editing.

Prospect seeds are private and remain hints until the ordinary strict official
site, Dutch postcode, source/email and historical suppression checks pass.
No mailbox access, no deletion, and no approval is granted by this module.
"""
from __future__ import annotations
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO

import review450 as b
import review450_strict as s

HEADERS = ["name_hint","website_hint","category_hint","country_hint","postcode_hint"]
# Broad organization-level exclusions, not a list of private prospect identities.
ADDITIONAL_EXCLUSIONS = ("carlton", "sportbedrijf")


def scope_allowed(row):
    from verify_official_lead import norm
    text=norm(str(row.get("company") or row.get("name_hint") or "")+" "+
              str(row.get("website") or row.get("website_hint") or ""))
    if s.chain(str(row.get("company") or row.get("name_hint") or ""),
               str(row.get("website") or row.get("website_hint") or "")):
        return False
    return not any(token in text for token in ADDITIONAL_EXCLUSIONS)


def supplement(conn):
    from registry_readonly import load_suppressions, load_discovery_suppressions
    from dedupe_preflight import candidate_identity, match_candidate, normalize_domain
    from overture_discovery import discover
    current=b.load_rows(conn)
    state=dict(b.read(conn,b.SID,b.STATE+"!A2:B11"))
    before=[b.COLS]+[[r[k] for k in b.COLS] for r in current]
    if len(current)!=450 or state.get("status")!="ready_for_review" or b.digest(before)!=state.get("content_sha256"):
        raise RuntimeError("complete_unchanged_batch_required")
    rows=[r for r in current if scope_allowed(r)]
    removed=len(current)-len(rows)
    if not removed:
        return {"excluded":0,"replacements":0,"prepared":450}
    if removed>20:
        raise RuntimeError("too_many_scope_issues_requires_review")
    historical=load_suppressions(session=conn)
    discovery_registry=load_discovery_suppressions(session=conn)
    known=[{"identity":candidate_identity(r),"status":"this_task","row_number":i+1} for i,r in enumerate(rows)]
    seeds=b.read(conn,b.SID,"Review450Supplement!A1:E30")
    if not seeds or seeds[0]!=HEADERS or any(len(r)!=5 for r in seeds[1:]):
        raise RuntimeError("supplement_hints_invalid")
    hints=[dict(zip(HEADERS,r)) for r in seeds[1:]]
    seen=set();checked=0
    def select_hints(values):
        selected=[]
        for hint in values:
            domain=normalize_domain(hint.get("website_hint"))
            if (not domain or domain in seen or not s.allowed_hint(hint) or not scope_allowed(hint) or
                    match_candidate(hint,discovery_registry) or match_candidate(hint,known)):
                continue
            seen.add(domain);selected.append(hint)
        return selected
    def accept(row):
        if (row and len(rows)<450 and scope_allowed(row) and not match_candidate(row,historical) and
                not match_candidate(row,discovery_registry) and not match_candidate(row,known)):
            rows.append(row)
            known.append({"identity":candidate_identity(row),"status":"this_task","row_number":len(rows)})
    with ThreadPoolExecutor(max_workers=6) as pool:
        todo=select_hints(hints)
        checked+=len(todo)
        for row in pool.map(lambda h:s.inspect(h,"discovery_nl_checked"),todo):
            accept(row)
        for region in ("Emmeloord","Dokkum","Enkhuizen"):
            if len(rows)==450:
                break
            try:
                result=discover(region=region,bbox=None,radius_km=12,keywords=["vakbedrijven"],max_results=5000,
                                require_website=True,probe_websites=False)
            except Exception:
                continue
            todo=select_hints(result.get("candidates",[]))
            for start in range(0,len(todo),24):
                if len(rows)==450 or checked>=600:
                    break
                block=todo[start:start+min(24,2*(450-len(rows)))]
                checked+=len(block)
                for row in pool.map(lambda h:s.inspect(h,"discovery_nl_checked"),block):
                    accept(row)
    if len(rows)!=450:
        raise RuntimeError("scope_replacements_incomplete_original_batch_unchanged")
    b.unique(rows)
    if any(not scope_allowed(row) for row in rows):
        raise RuntimeError("scope_rejection_remaining")
    if b.load_rows(conn)!=current:
        raise RuntimeError("batch_changed_during_scope_review")
    s.persist(conn,rows,"ready_for_review",int(state.get("sites_checked","0"))+checked,int(state.get("regions","0")))
    if b.load_rows(conn)!=rows:
        raise RuntimeError("scope_replacement_readback_failed")
    return {"excluded":removed,"replacements":removed,"prepared":len(rows)}


def main():
    if os.getenv("REVIEW450_PHASE")!="final_copy":
        print("REVIEW450_SCOPE=blocked unauthorized_phase sent=0")
        return 1
    try:
        with redirect_stdout(StringIO()),redirect_stderr(StringIO()):
            from private_candidate_handoff import authorized_writer
            result=supplement(authorized_writer())
        print("REVIEW450_SCOPE=green excluded={} replacements={} prepared=450 sent=0 mailbox_writes=0".format(result["excluded"],result["replacements"]))
        return 0
    except Exception:
        print("REVIEW450_SCOPE=blocked private_scope_or_source_or_readback sent=0 mailbox_writes=0")
        return 1


if __name__=="__main__":
    sys.exit(main())
