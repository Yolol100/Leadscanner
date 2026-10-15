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


def require_rejection_review(rejected, excluded_domains):
    """Large rejection sets need an explicit private entry for EVERY domain.

    The original threshold still blocks unreviewed large changes. A completed
    human/source review is represented by the existing private exclusions table,
    whose rows each require a canonical domain, nonempty reason and source URL.
    No rejected prospect is ever accepted by this gate. Every replacement must
    independently pass the unchanged full source and historical checks.
    """
    from dedupe_preflight import normalize_domain
    if len(rejected) > 20:
        if any(normalize_domain(row.get("website", "")) not in excluded_domains
               for row in rejected):
            raise RuntimeError("too_many_scope_issues_requires_review")


# All private records stay in the owner's existing Google Sheet, never in GitHub.
POOL_TAB = "Review450Replacements"
POOL_ID = 683105012
POOL_STATE_TAB = "Review450ReplacementState"
POOL_STATE_ID = 683105013
POOL_LIMIT = 60
MAX_NEW_SITE_CHECKS = 1500
MAX_SEARCH_SECONDS = 900


def load_checkpoint(conn, base_digest):
    """Read the last complete private checkpoint, fail closed on inconsistencies."""
    values = b.read(conn, b.SID, POOL_TAB + "!A1:P61")
    if not values or values[0] != b.COLS or len(values) > POOL_LIMIT + 1:
        raise RuntimeError("checkpoint_headers_invalid")
    pool = []
    for raw in values[1:]:
        if len(raw) != len(b.COLS):
            raise RuntimeError("checkpoint_rows_invalid")
        row = dict(zip(b.COLS, raw))
        b.validate(row)
        pool.append(row)
    b.unique(pool)
    raw_state = b.read(conn, b.SID, POOL_STATE_TAB + "!A1:B20")
    if not raw_state or raw_state[0] != ["key", "value"]:
        raise RuntimeError("checkpoint_state_invalid")
    pairs = {}
    for raw in raw_state[1:]:
        if not raw or len(raw) > 2 or raw[0] in pairs:
            raise RuntimeError("checkpoint_state_invalid")
        pairs[raw[0]] = raw[1] if len(raw) == 2 else ""
    if pairs.get("task") != b.TASK or pairs.get("base_digest") != base_digest:
        raise RuntimeError("checkpoint_digest_mismatch")
    if pairs.get("status") not in {"pending", "partial", "complete_candidates", "committed"}:
        raise RuntimeError("checkpoint_state_invalid")
    try:
        cursor = int(pairs["next_region_index"])
        checks = int(pairs["checked_sites"])
        count = int(pairs["verified_replacements"])
    except (KeyError, ValueError):
        raise RuntimeError("checkpoint_state_invalid") from None
    if not (0 <= cursor <= len(b.REGIONS[6:]) and checks >= 0 and count == len(pool)):
        raise RuntimeError("checkpoint_state_invalid")
    if pairs["status"] == "committed":
        raise RuntimeError("checkpoint_unexpected_committed")
    return pool, cursor, checks


def save_checkpoint(conn, pool, base_digest, next_region, total_checked, phase):
    """One atomic Sheets write + exact readback; does not change Review450."""
    if len(pool) > POOL_LIMIT:
        raise RuntimeError("checkpoint_pool_full")
    b.unique(pool)
    contents = [b.COLS] + [[r[k] for k in b.COLS] for r in pool]
    state = [
        ["key", "value"], ["task", b.TASK], ["base_digest", base_digest],
        ["next_region_index", str(next_region)],
        ["checked_sites", str(total_checked)],
        ["verified_replacements", str(len(pool))],
        ["status", phase], ["updated_at", b.now()],
    ]
    b.post(conn, [b.table_request(POOL_ID, contents, len(b.COLS)),
                  b.table_request(POOL_STATE_ID, state, 2)])
    if (b.read(conn, b.SID, POOL_TAB + "!A1:P61") != contents or
            b.read(conn, b.SID, POOL_STATE_TAB + "!A1:B8") != state):
        raise RuntimeError("checkpoint_readback_failed")


def supplement(conn):
    """Phase 1: keep 428 fit candidates. Phase 2: checkpoint verified replacements.
    Only when all 450 pass do we atomically change the final candidate list.
    """
    import time
    from registry_readonly import load_suppressions, load_discovery_suppressions
    from dedupe_preflight import candidate_identity, match_candidate, normalize_domain
    from overture_discovery import discover

    current = b.load_rows(conn)
    state = dict(b.read(conn, b.SID, b.STATE + "!A2:B11"))
    before = [b.COLS] + [[r[k] for k in b.COLS] for r in current]
    digest = b.digest(before)
    if (len(current) != b.TARGET or state.get("status") != "ready_for_review" or
            digest != state.get("content_sha256")):
        raise RuntimeError("complete_unchanged_batch_required")
    exclusions = private_exclusions(conn)
    allowed = lambda item: scope_allowed(item, exclusions)
    rows = [r for r in current if allowed(r)]
    rejected = [r for r in current if not allowed(r)]
    needed = len(rejected)
    if not needed:
        return {"excluded": 0, "replacements": 0, "prepared": b.TARGET}
    require_rejection_review(rejected, exclusions)
    pool, cursor, total_checked = load_checkpoint(conn, digest)
    if len(pool) > needed:
        raise RuntimeError("checkpoint_pool_exceeds_rejections")

    historical = load_suppressions(session=conn)
    discovery_registry = load_discovery_suppressions(session=conn)
    known = [{"identity": candidate_identity(r), "status": "this_task", "row_number": i+1}
             for i, r in enumerate(rows)]
    for candidate in pool:
        if (not allowed(candidate) or match_candidate(candidate, historical) or
                match_candidate(candidate, discovery_registry) or
                match_candidate(candidate, known)):
            raise RuntimeError("checkpoint_candidate_invalid")
        rows.append(candidate)
        known.append({"identity": candidate_identity(candidate),
                      "status": "checkpointed", "row_number": len(rows)})

    seeds = b.read(conn, b.SID, "Review450Supplement!A1:E30")
    if not seeds or seeds[0] != HEADERS or any(len(r) != 5 for r in seeds[1:]):
        raise RuntimeError("supplement_hints_invalid")
    hints = [dict(zip(HEADERS, raw)) for raw in seeds[1:]]
    seen = set()
    checked_now = 0
    started = time.monotonic()

    def select_hints(values):
        selected = []
        for hint in values:
            domain = normalize_domain(hint.get("website_hint"))
            if (not domain or domain in seen or not s.allowed_hint(hint) or
                    not allowed(hint) or match_candidate(hint, discovery_registry) or
                    match_candidate(hint, known)):
                continue
            seen.add(domain)
            selected.append(hint)
        return selected

    def accept(candidate):
        if (candidate and len(rows) < b.TARGET and allowed(candidate) and
                not match_candidate(candidate, historical) and
                not match_candidate(candidate, discovery_registry) and
                not match_candidate(candidate, known)):
            rows.append(candidate)
            pool.append(candidate)
            known.append({"identity": candidate_identity(candidate),
                          "status": "this_task", "row_number": len(rows)})

    with ThreadPoolExecutor(max_workers=6) as workers:
        initial = select_hints(hints)
        checked_now += len(initial)
        for candidate in workers.map(lambda hint: s.inspect(hint, "discovery_nl_checked"), initial):
            accept(candidate)
        save_checkpoint(conn, pool, digest, cursor, total_checked + checked_now,
                        "complete_candidates" if len(rows) == b.TARGET else "partial")
        last_saved = len(pool)
        next_cursor = cursor
        for index in range(cursor, len(b.REGIONS[6:])):
            if (len(rows) >= b.TARGET or checked_now >= MAX_NEW_SITE_CHECKS or
                    time.monotonic() - started > MAX_SEARCH_SECONDS):
                break
            region = b.REGIONS[6:][index]
            try:
                found = discover(region=region, bbox=None, radius_km=25,
                                 keywords=["vakbedrijven"], max_results=5000,
                                 require_website=True, probe_websites=False)
            except Exception:
                next_cursor = index + 1
                save_checkpoint(conn, pool, digest, next_cursor,
                                total_checked + checked_now, "partial")
                continue
            todo = select_hints(found.get("candidates", []))
            for offset in range(0, len(todo), 24):
                if (len(rows) >= b.TARGET or checked_now >= MAX_NEW_SITE_CHECKS or
                        time.monotonic() - started > MAX_SEARCH_SECONDS):
                    break
                batch = todo[offset:offset + min(24, 2 * (b.TARGET - len(rows)),
                                                  MAX_NEW_SITE_CHECKS - checked_now)]
                checked_now += len(batch)
                for candidate in workers.map(
                        lambda hint: s.inspect(hint, "discovery_nl_checked"), batch):
                    accept(candidate)
                if len(pool) >= last_saved + 4:
                    save_checkpoint(conn, pool, digest, index,
                                    total_checked + checked_now,
                                    "complete_candidates" if len(rows) == b.TARGET else "partial")
                    last_saved = len(pool)
            next_cursor = index + 1
            save_checkpoint(conn, pool, digest, next_cursor, total_checked + checked_now,
                            "complete_candidates" if len(rows) == b.TARGET else "partial")
            last_saved = len(pool)

    if len(rows) != b.TARGET:
        return {"status": "partial", "excluded": needed, "prepared": len(rows),
                "replacements": len(pool), "missing": b.TARGET - len(rows),
                "checked": checked_now, "next_region": next_cursor}

    b.unique(rows)
    if any(not allowed(row) for row in rows):
        raise RuntimeError("scope_rejection_remaining")
    if (b.load_rows(conn) != current or
            dict(b.read(conn, b.SID, b.STATE + "!A2:B11")) != state or
            private_exclusions(conn) != exclusions):
        raise RuntimeError("batch_changed_during_scope_review")
    # Suppressions can change during a long run: refresh before promoting.
    historical_now = load_suppressions(session=conn)
    discovery_now = load_discovery_suppressions(session=conn)
    if any(match_candidate(r, historical_now) or match_candidate(r, discovery_now)
           for r in pool):
        raise RuntimeError("new_suppression_before_commit")

    s.persist(conn, rows, "ready_for_review",
              int(state.get("sites_checked", "0")) + total_checked + checked_now,
              int(state.get("regions", "0")) + next_cursor)
    if b.load_rows(conn) != rows:
        raise RuntimeError("scope_replacement_readback_failed")
    save_checkpoint(conn, pool, digest, next_cursor, total_checked + checked_now, "committed")
    return {"excluded": needed, "replacements": len(pool),
            "prepared": len(rows)}


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
    "checkpoint_headers_invalid", "checkpoint_rows_invalid",
    "checkpoint_state_invalid", "checkpoint_digest_mismatch",
    "checkpoint_unexpected_committed", "checkpoint_pool_exceeds_rejections",
    "checkpoint_candidate_invalid", "checkpoint_pool_full",
    "checkpoint_readback_failed", "new_suppression_before_commit",
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
        if result.get("status") == "partial":
            print("REVIEW450_SCOPE=partial verified={} missing={} checked={} next_region={} sent=0 mailbox_writes=0".format(
                  result["replacements"], result["missing"], result["checked"], result["next_region"]))
            return 2
        print("REVIEW450_SCOPE=green excluded={} replacements={} prepared=450 sent=0 mailbox_writes=0".format(
              result["excluded"], result.get("replacements", 0)))
        return 0
    except Exception as exc:
        print("REVIEW450_SCOPE=blocked reason={} sent=0 mailbox_writes=0".format(safe_reason(exc)))
        return 1


if __name__=="__main__":
    sys.exit(main())
