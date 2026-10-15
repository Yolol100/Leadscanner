"""Replace scope-rejected prospects before final editing, without mailbox access.

Seeds and exclusions remain private. Replacements require the ordinary strict
source, Dutch postal code, contact-address and historical suppression checks.
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
ADDITIONAL_EXCLUSIONS = ("carlton", "sportbedrijf")


def scope_allowed(row, excluded_domains=()):
    from verify_official_lead import norm
    from dedupe_preflight import normalize_domain, domains_match
    name=str(row.get("company") or row.get("name_hint") or "")
    website=str(row.get("website") or row.get("website_hint") or "")
    text=norm(name+" "+website)
    domain=normalize_domain(website)
    if s.chain(name,website) or any(token in text for token in ADDITIONAL_EXCLUSIONS):
        return False
    if any(domains_match(domain,old) for old in excluded_domains):
        return False
    email=str(row.get("email") or "")
    if email and row.get("origin")!="review50_reverified_v3":
        if "@" not in email or not domains_match(domain,email.rsplit("@",1)[1].casefold()):
            return False
    return True


def private_exclusions(conn):
    from dedupe_preflight import normalize_domain
    values=b.read(conn,b.SID,"Review450ScopeExclusions!A1:C40")
    if not values or values[0]!=["domain","reason","source_url"]:
        raise RuntimeError("private_scope_review_unavailable")
    domains=[]
    for row in values[1:]:
        if len(row)!=3 or not row[1] or not row[2].startswith(("https://","http://")):
            raise RuntimeError("private_scope_review_invalid")
        domain=normalize_domain(row[0])
        if not domain or "." not in domain or domain!=row[0].casefold():
            raise RuntimeError("private_scope_domain_invalid")
        domains.append(domain)
    return set(domains)


def supplement(conn):
    from registry_readonly import load_suppressions, load_discovery_suppressions
    from dedupe_preflight import candidate_identity, match_candidate, normalize_domain
    from overture_discovery import discover
    current=b.load_rows(conn)
    state=dict(b.read(conn,b.SID,b.STATE+"!A2:B11"))
    before=[b.COLS]+[[r[k] for k in b.COLS] for r in current]
    if len(current)!=450 or state.get("status")!="ready_for_review" or b.digest(before)!=state.get("content_sha256"):
        raise RuntimeError("complete_unchanged_batch_required")
    exclusions=private_exclusions(conn)
    allowed=lambda row:scope_allowed(row,exclusions)
    rows=[r for r in current if allowed(r)]
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
            if (not domain or domain in seen or not s.allowed_hint(hint) or not allowed(hint) or
                    match_candidate(hint,discovery_registry) or match_candidate(hint,known)):
                continue
            seen.add(domain);selected.append(hint)
        return selected
    def accept(row):
        if (row and len(rows)<450 and allowed(row) and not match_candidate(row,historical) and
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
    if any(not allowed(row) for row in rows):
        raise RuntimeError("scope_rejection_remaining")
    if b.load_rows(conn)!=current or private_exclusions(conn)!=exclusions:
        raise RuntimeError("batch_changed_during_scope_review")
    s.persist(conn,rows,"ready_for_review",int(state.get("sites_checked","0"))+checked,int(state.get("regions","0")))
    if b.load_rows(conn)!=rows:
        raise RuntimeError("scope_replacement_readback_failed")
    return {"excluded":removed,"replacements":removed,"prepared":len(rows)}


SAFE_REASONS = frozenset({
    "complete_unchanged_batch_required", "private_scope_review_unavailable",
    "private_scope_review_invalid", "private_scope_domain_invalid",
    "too_many_scope_issues_requires_review", "supplement_hints_invalid",
    "scope_replacements_incomplete_original_batch_unchanged", "scope_rejection_remaining",
    "batch_changed_during_scope_review", "scope_replacement_readback_failed",
    "private_sheet_read_failed", "private_sheet_shape_invalid", "private_sheet_write_failed",
    "private_batch_headers_invalid", "private_batch_row_invalid", "too_many_batch_rows",
    "duplicate_draft_id", "duplicate_business", "review_row_invalid", "review_copy_invalid",
    "lead_history_headers_invalid", "lead_history_invalid_row", "lead_history_incomplete",
    "lead_history_identity_missing", "lead_history_duplicate_identity", "lead_history_blank_row",
    "draft_queue_registry_headers_invalid", "draft_queue_registry_invalid_row",
    "draft_queue_registry_invalid_identity", "draft_queue_registry_identity_missing",
    "historical_suppression_unavailable", "registry_read_failed", "registry_auth_invalid",
    "batch_readback_failed", "history_readback_failed",
})


def safe_reason(exc):
    """Only fixed failure codes reach public logs; never exception details."""
    reason = str(exc)
    if reason in SAFE_REASONS:
        return reason
    name = type(exc).__name__
    if name in {"TypeError", "ValueError", "KeyError", "IndexError", "AttributeError"}:
        return name
    return "private_scope_or_source_or_readback"


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
    except Exception as exc:
        print("REVIEW450_SCOPE=blocked reason={} sent=0 mailbox_writes=0".format(safe_reason(exc)))
        return 1


if __name__=="__main__":
    sys.exit(main())
