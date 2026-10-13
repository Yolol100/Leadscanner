"""Private in-run, read-only audit of historical source and actual mijn.host Drafts.

Public Actions log contains ONLY aggregate integer counters, no PII, URLs,
mail bodies, HMAC values, IMAP UIDs, provider exception text or local files.
No mailbox mutation, sending, campaign, or dedupe write is implemented here.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from io import StringIO
import json
import os
import re
import sys

from _once_historical_source_diagnose import EXPECTED, FATAL_KEYS, classify, read_source
from _once_historical_site_redraft import (
    BATCH_SIZE, STATUSES, build_batch, excluded_history,
    historical_site, historical_name, historical_registry_hold, safe_failure_marker,
)
from dedupe_preflight import match_candidate, normalize_domain, normalize_email, domains_match
from historical_v2 import token
from leadscanner_core import fetch_registry
from myhost_draft import (
    connect_imap, find_drafts_folder, select_folder, fetch_message,
    lead_id_from_message, review_status_from_message, plain_body,
    uid_for_message_id, require_draft_flag, LEAD_ID_HEADERS,
    normalize_text, build_message, exact_message_matches,
)

EXPECTED_NEW = 43
RUN_START = datetime(2026, 10, 12, 23, 49, tzinfo=timezone.utc)
RUN_END = datetime(2026, 10, 13, 0, 25, tzinfo=timezone.utc)
FIXED_FIELDS = (
    "checked", "excluded_history", "hold_source_status",
    "hold_missing_website", "hold_missing_business_identity",
    "hold_duplicate_website", "hold_website_verification",
    "hold_website_research", "hold_insufficient_findings",
    "hold_unverified_contact", "hold_mail_validation",
    "hold_duplicate_recipient", "ready_for_review",
)
MAX_MESSAGE_BYTES = 180000


def load_private_source():
    rows, _ = read_source()
    summary = classify(rows)
    if len(rows) != EXPECTED or any(summary[k] for k in FATAL_KEYS):
        raise RuntimeError("source_integrity_hold")
    registry = fetch_registry()
    historical = [row for row in registry
                  if row.get("status") == "historical_v2_suppression"]
    if len(historical) != 1:
        raise RuntimeError("historical_suppression_incomplete")
    history = historical[0]
    key = history.get("v2_key")
    if (not isinstance(key, bytes)
            or len(history.get("v2_emails") or ()) != EXPECTED):
        raise RuntimeError("historical_suppression_incomplete")
    ordinary = [row for row in registry
                if row.get("status") != "historical_v2_suppression"]
    source_domains = set()
    source_emails = set()
    excluded = 0
    for row in rows:
        address = normalize_email(row.get("email"))
        if not address or address in source_emails:
            raise RuntimeError("historical_source_duplicates")
        source_emails.add(address)
        matched = match_candidate({"email": address}, [history])
        if not matched or "historical_v2_email" not in matched.get("matched_by", []):
            raise RuntimeError("historical_suppression_missing")
        website = historical_site(row)
        domain = normalize_domain(website)
        if domain:
            source_domains.add(domain)
        if excluded_history(row) or historical_registry_hold(
            {"email": address, "website": website,
             "company": historical_name(row)}, ordinary,
            original_email=address,
        ):
            excluded += 1
    return rows, history, ordinary, {
        "source_checked": len(rows),
        "source_unique_emails": len(source_emails),
        "source_hmac_suppressed": len(source_emails),
        "source_historical_exclusions": excluded,
        "source_known_website_domains": len(source_domains),
    }, source_domains


def _safe_mail_ids(client):
    """Use server-side header search. No fetching of unrelated inbox bodies."""
    found = set()
    for header in LEAD_ID_HEADERS:
        status, data = client.search(None, "HEADER", header, '"growth-"')
        if status != "OK":
            raise RuntimeError("imap_header_search_hold")
        found.update((data[0] if data else b"").split())
    return sorted(found, key=int)


def _one_address(message, header):
    values = getaddresses(message.get_all(header, []))
    if len(values) != 1:
        return ""
    return normalize_email(values[0][1])


def _sent_folder(client):
    status, data = client.list()
    if status != "OK":
        return ""
    folders = []
    for b in data or []:
        value = b.decode("utf-8", errors="replace") if isinstance(b, bytes) else str(b)
        candidate = value.rsplit('"', 2)[-2] if value.count('"') >= 2 else value.split()[-1].strip('"')
        if "sent" in candidate.casefold() or "verzonden" in candidate.casefold():
            folders.append(candidate)
    return folders[0] if len(folders) == 1 else ""


def _quota(client, folder):
    try:
        if not hasattr(client, "getquotaroot"):
            return {"quota_available": 0, "quota_unknown": 1}
        status, data = client.getquotaroot(folder)
        if status != "OK":
            return {"quota_available": 0, "quota_unknown": 1}
        plain = " ".join(
            x.decode("ascii", errors="ignore") if isinstance(x, bytes) else str(x)
            for x in data or [] if x
        )
        m = re.search(r"\bSTORAGE\s+(\d+)\s+(\d+)\b", plain, re.I)
        if not m:
            return {"quota_available": 0, "quota_unknown": 1}
        used, limit = map(int, m.groups())
        if limit <= 0 or used > limit:
            return {"quota_available": 0, "quota_unknown": 1}
        return {
            "quota_available": 1, "quota_unknown": 0,
            "quota_used_kib": used, "quota_limit_kib": limit,
        }
    except Exception:
        return {"quota_available": 0, "quota_unknown": 1}


def inventory(client, folder, history, source_domains):
    select_folder(client, folder, readonly=True)
    status, data = client.search(None, "ALL")
    if status != "OK":
        raise RuntimeError("draft_folder_search_hold")
    total_folder = len((data[0] if data else b"").split())
    records = []
    candidates = _safe_mail_ids(client)
    counts = Counter({
        "folder_messages": total_folder,
        "tagged_growth_messages": len(candidates),
    })
    seen_ids, seen_emails, seen_domains, seen_message_ids = set(), set(), set(), set()
    for mid in candidates:
        msg = fetch_message(client, mid)
        lead_id = lead_id_from_message(msg)
        email = _one_address(msg, "To")
        sender = _one_address(msg, "From")
        subj = normalize_text(msg.get("Subject", ""))
        body = plain_body(msg)
        if (not lead_id.startswith("growth-")
                or len(lead_id) != 27
                or not re.fullmatch(r"growth-[0-9a-f]{20}", lead_id)):
            counts["invalid_lead_identifier"] += 1
            continue

        # This audited historic run is distinguished by original Date
        # metadata, not by guessing that unrelated old Drafts are new.
        try:
            sent_at = parsedate_to_datetime(msg.get("Date", ""))
            if sent_at.tzinfo is None:
                raise ValueError("date_missing_timezone")
            created_during_run = RUN_START <= sent_at.astimezone(timezone.utc) <= RUN_END
        except (ValueError, TypeError, OverflowError):
            created_during_run = False
        if not created_during_run:
            counts["other_tagged_drafts"] += 1
            continue

        counts["run_drafts"] += 1
        if not email or email.count("@") != 1 or sender != normalize_email(os.environ.get(
                "OUTREACH_SENDER_EMAIL", "info@andrewbaeten.nl")):
            counts["identity_failure"] += 1
        if email and lead_id != "growth-" + token(history["v2_key"], "email", email)[:20]:
            counts["identity_failure"] += 1
        if review_status_from_message(msg) != "contact-basis":
            counts["review_flag_failure"] += 1
        try:
            uid = uid_for_message_id(client, mid)
            require_draft_flag(client, uid)
        except Exception:
            counts["draft_flag_failure"] += 1
        domain = normalize_domain(email.rsplit("@", 1)[1]) if "@" in email else ""
        if not domain or not any(domains_match(domain, known) for known in source_domains):
            counts["not_linked_by_historical_domain"] += 1
        if (lead_id in seen_ids or email in seen_emails
                or (domain and domain in seen_domains)
                or normalize_text(msg.get("Message-ID")) in seen_message_ids):
            counts["duplicate_identity"] += 1
        seen_ids.add(lead_id)
        seen_emails.add(email)
        if domain:
            seen_domains.add(domain)
        seen_message_ids.add(normalize_text(msg.get("Message-ID")))
        bullets = [x for x in body.splitlines() if x.startswith("- ")]
        if (not subj or subj != subj.casefold() or not body
                or not (4 <= len(bullets) <= 6)
                or len(body.split()) > 260
                or body.count("?") != 1
                or not body.endswith("Andrew Baeten")
                or "Webactueel" in body
                or any(t in body for t in ("{{", "}}", "{%", "%}", "\x00"))
                or email in body
                or any(not x.strip("- ").strip() for x in bullets)):
            counts["copy_template_failure"] += 1
        else:
            counts["copy_template_pass"] += 1
        records.append({"lead_id": lead_id, "email": email,
                        "domain": domain, "message": msg})

    counts["historic_drafts"] = len(records)
    sent_folder = _sent_folder(client)
    if sent_folder:
        select_folder(client, sent_folder, readonly=True)
        counts["sent_folder_readable"] = 1
        for row in records:
            status, data = client.search(None, "TO", '"' + row["email"] + '"')
            if status != "OK":
                counts["sent_folder_search_failure"] += 1
                continue
            if (data[0] if data else b"").split():
                counts["recipients_with_sent_mail"] += 1
    else:
        counts["sent_folder_not_verified"] = 1
    select_folder(client, folder, readonly=True)
    counts.update(_quota(client, folder))
    return records, dict(counts)


def source_and_mailbox_snapshot():
    rows, history, ordinary, src, source_domains = load_private_source()
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        records, counts = inventory(client, folder, history, source_domains)
    finally:
        try:
            client.logout()
        except Exception:
            pass
    return rows, history, ordinary, src, records, counts


def inventory_report():
    _, _, _, source, _, box = source_and_mailbox_snapshot()
    good = (
        source["source_checked"] == EXPECTED
        and source["source_hmac_suppressed"] == EXPECTED
        and box.get("historic_drafts") == EXPECTED_NEW
        and box.get("run_drafts") == EXPECTED_NEW
        and not any(box.get(key, 0) for key in (
            "identity_failure", "invalid_lead_identifier", "review_flag_failure",
            "draft_flag_failure", "duplicate_identity", "copy_template_failure",
            "sent_folder_search_failure", "recipients_with_sent_mail",
            "not_linked_by_historical_domain",
        ))
    )
    return {"status": "green" if good else "hold",
            "source": source, "mailbox": box,
            "no_mutations": True, "emails_sent_by_audit": 0}


def batch_report(offset):
    if offset not in range(0, EXPECTED, BATCH_SIZE):
        raise RuntimeError("offset_out_of_bounds")
    rows, history, ordinary, src, records, box = source_and_mailbox_snapshot()
    # This audit never manufactures, replaces or saves a Draft.
    report, batch = build_batch(
        offset=offset, rows=rows, history=history, ordinary=ordinary,
    )
    ready = {r["lead_id"]: r for r in batch["rows"]}
    # Any reviewable draft in this batch must exactly equal the freshly
    # evidenced version, including actual To/From/subject/body/review state.
    matches, mismatches = 0, 0
    for item in records:
        if item["lead_id"] not in ready:
            continue
        _, expected_message = build_message(ready[item["lead_id"]])
        if exact_message_matches(item["message"], expected_message):
            matches += 1
        else:
            mismatches += 1
    if report["counts"]["checked"] != report["size"]:
        raise RuntimeError("historical_batch_missing")
    return {
        "status": "green" if not mismatches and
        box.get("historic_drafts") == EXPECTED_NEW and
        box.get("duplicate_identity", 0) == 0 else "hold",
        "offset": offset, "size": report["size"],
        "counts": {k: report["counts"].get(k, 0) for k in FIXED_FIELDS},
        "current_ready_matching_stored": matches,
        "current_ready_different_stored": mismatches,
        "current_ready_without_stored": sum(
            1 for lead_id in ready
            if lead_id not in {r["lead_id"] for r in records}
        ),
        "source_checked": src["source_checked"],
        "source_hmac_suppressed": src["source_hmac_suppressed"],
        "mailbox_drafts_recount": box.get("historic_drafts", 0),
        "no_mutations": True, "emails_sent_by_audit": 0,
    }


def deep_duplicate_report():
    """Cross-check the 43 historic run Drafts against ALL other Draft headers.

    Bounded header-only FETCH on the entire folder; no body of unrelated
    drafts is fetched or persisted, no UID/recipient is printed publicly.
    """
    from email.parser import BytesParser
    from email.policy import default
    _, _, _, source, records, initial = source_and_mailbox_snapshot()
    if len(records) != EXPECTED_NEW:
        raise RuntimeError("historic_baseline_missing")
    focus_emails = {r["email"] for r in records}
    focus_ids = {r["lead_id"] for r in records}
    # Shared public mailbox providers are not company identities. Count
    # corporate-domain collisions only; exact To collisions still count.
    from cold_stages import PUBLIC_MAIL_DOMAINS
    focus_domains = {r["domain"] for r in records
                     if r["domain"] and r["domain"] not in PUBLIC_MAIL_DOMAINS}
    # Read all folder headers, including untagged and prior Drafts. Do not
    # equate the 43 audited Drafts with the whole 1,180-message mailbox.
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        select_folder(client, folder, readonly=True)
        status, response = client.search(None, "ALL")
        if status != "OK":
            raise RuntimeError("imap_folder_scan_hold")
        message_ids = (response[0] if response else b"").split()
        if not EXPECTED_NEW <= len(message_ids) <= 5000:
            raise RuntimeError("imap_folder_count_out_of_bounds")
        recipient_counts, domain_counts, lead_counts = Counter(), Counter(), Counter()
        header_ok = 0
        with_to = 0
        for start in range(0, len(message_ids), 40):
            seq = b",".join(message_ids[start:start + 40]).decode("ascii")
            status, payload = client.fetch(
                seq, "(BODY.PEEK[HEADER.FIELDS (TO X-Leadscanner-Lead-ID X-Webactueel-Lead-ID)])",
            )
            if status != "OK":
                raise RuntimeError("imap_header_fetch_hold")
            for part in payload or []:
                if not isinstance(part, tuple) or len(part) < 2 or not isinstance(part[1], bytes):
                    continue
                header_ok += 1
                msg = BytesParser(policy=default).parsebytes(part[1])
                email = _one_address(msg, "To")
                lead = lead_id_from_message(msg)
                if email:
                    with_to += 1
                    recipient_counts[email] += 1
                    if "@" in email:
                        domain = normalize_domain(email.rsplit("@", 1)[1])
                        if domain and domain not in PUBLIC_MAIL_DOMAINS:
                            domain_counts[domain] += 1
                if lead:
                    lead_counts[lead] += 1
        if header_ok != len(message_ids):
            raise RuntimeError("imap_header_readback_incomplete")
        cross_email = sum(recipient_counts[email] - 1 for email in focus_emails
                          if recipient_counts[email] > 1)
        cross_lead = sum(lead_counts[lid] - 1 for lid in focus_ids
                         if lead_counts[lid] > 1)
        cross_domain = sum(domain_counts[domain] - 1 for domain in focus_domains
                           if domain_counts[domain] > 1)
        return {
            "status": "green" if not (cross_email or cross_lead or cross_domain) else "hold",
            "source_checked": source["source_checked"],
            "folder_messages": len(message_ids),
            "header_messages_read": header_ok,
            "header_messages_with_to": with_to,
            "historic_drafts": len(records),
            "cross_recipient_duplicates": cross_email,
            "cross_lead_id_duplicates": cross_lead,
            "cross_business_domain_duplicates": cross_domain,
            "writes": 0, "sends": 0,
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--mode", required=True, choices=("inventory", "batch", "deep"))
    cli.add_argument("--offset", type=int, default=0)
    args = cli.parse_args()
    try:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            result = (inventory_report() if args.mode == "inventory" else
                      deep_duplicate_report() if args.mode == "deep" else
                      batch_report(args.offset))
    except Exception as exc:
        print("HISTORICAL_INDEPENDENT_AUDIT=red " + safe_failure_marker(exc)
              + " details_suppressed")
        return 1
    print("HISTORICAL_INDEPENDENT_AUDIT=" + result["status"] + " "
          + json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "green" else 2


if __name__ == "__main__":
    sys.exit(main())
