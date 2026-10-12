"""Temporary historical mail-copy QA: 12 read-only batches of <=100.

Only fixed aggregate counters are printed. All source data stays inside the
Actions runner. No email sending, provider writes, mailbox or registry writes.
"""
import argparse
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
import re
import sys

import requests

from dedupe_preflight import normalize_domain, normalize_email, match_candidate
from cold_stages import valid_email
from historical_mail_quality import check_reviewed_copy
from leadscanner_core import fetch_registry
from outreach_stages import review_findings
from url_safety import is_public_http_url

LIST_ID = "24deb187-59e0-43b5-86b8-fe37a7b21e2a"
EXPECTED = 1128
BATCH_SIZE = 100
API = "https://api.instantly.ai/api/v2/leads/list"
UUID = re.compile(r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$")
FIELDS = ("subject", "body", "observation", "value_action", "evidence_url",
          "source_type", "signal_type", "contact_url", "official_domain")


def source_rows():
    api_key = os.getenv("INSTANTLY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("missing_source_access")
    collected, ids, emails, cursors = [], set(), set(), set()
    cursor = ""
    with requests.Session() as client:
        for _ in range(25):
            request = {"list_id": LIST_ID, "limit": BATCH_SIZE}
            if cursor:
                request["starting_after"] = cursor
            response = client.post(
                API, json=request,
                headers={"Authorization": "Bearer " + api_key},
                timeout=30,
            )
            if response.status_code != 200:
                raise RuntimeError("source_read_failed")
            result = response.json()
            records = result.get("items") if isinstance(result, dict) else None
            if not isinstance(records, list):
                raise RuntimeError("source_page_invalid")
            for row in records:
                if not isinstance(row, dict) or row.get("list_id") != LIST_ID:
                    raise RuntimeError("source_identity_mismatch")
                identity = str(row.get("id") or "").strip().lower()
                address = normalize_email(row.get("email"))
                if (not UUID.fullmatch(identity) or not valid_email(address)
                        or identity in ids or address in emails):
                    raise RuntimeError("source_duplicates_or_invalid")
                ids.add(identity)
                emails.add(address)
                collected.append(row)
            nxt = str(result.get("next_starting_after") or "").strip()
            if not nxt:
                break
            if nxt == cursor or nxt in cursors or not records:
                raise RuntimeError("source_cursor_invalid")
            cursors.add(nxt)
            cursor = nxt
        else:
            raise RuntimeError("source_page_limit")
    if len(collected) != EXPECTED:
        raise RuntimeError("source_total_changed")
    return sorted(collected, key=lambda row: str(row["id"]).lower())


def check_one(row, history):
    counters = Counter({"checked": 1})
    email = normalize_email(row["email"])
    hold = match_candidate({"email": email}, [history])
    if not hold or "historical_v2_email" not in hold["matched_by"]:
        raise RuntimeError("missing_history_suppression")
    counters["historical_email_excluded"] += 1
    if row.get("status") in (-1, -2, -3):
        counters["provider_blocked"] += 1

    vals = row.get("payload")
    if not isinstance(vals, dict):
        vals = row.get("custom_variables")
    if not isinstance(vals, dict):
        vals = {}
    prefix = None
    for key in ("leadscanner_site_refresh_", "leadscanner_site_candidate_"):
        if str(vals.get(key + "subject") or "").strip() or str(vals.get(key + "body") or "").strip():
            prefix = key
            break
    if not prefix:
        counters["no_prior_mail_copy"] += 1
        return counters
    counters["prior_copy_present"] += 1
    entry = {name: str(vals.get(prefix + name) or "").strip() for name in FIELDS}
    if not all(entry.values()):
        counters["incomplete_copy_fields"] += 1
        return counters

    domain = normalize_domain(entry["official_domain"])
    if (not domain or entry["source_type"] != "official_site"
            or any(not is_public_http_url(entry[k]) for k in ("contact_url", "evidence_url"))
            or normalize_domain(entry["contact_url"]) != domain
            or normalize_domain(entry["evidence_url"]) != domain
            or vals.get("leadscanner_contact_basis") != "review_required"):
        counters["first_party_metadata_hold"] += 1
        return counters
    counters["first_party_metadata_pass"] += 1
    findings = None
    raw = vals.get(prefix + "findings")
    if raw:
        try:
            findings = review_findings(json.loads(str(raw)), domain)
        except (ValueError, TypeError):
            counters["finding_format_hold"] += 1
            return counters
    candidate = {
        "official_domain": domain,
        "selected_findings": findings or [],
        "public_business_email": email,
        "verified_observation": entry["observation"],
        "verified_observation_source_type": "official_site",
        "verified_observation_source_url": entry["evidence_url"],
        "value_action_status": "proposed",
        "value_first_action": entry["value_action"],
    }
    grade = check_reviewed_copy(candidate, entry["subject"], entry["body"])
    counters["new_validator_pass" if grade == "quality_pass" else "new_validator_hold"] += 1
    return counters


def run(offset):
    if offset not in range(0, EXPECTED, BATCH_SIZE):
        raise ValueError("offset_out_of_bounds")
    source = source_rows()
    try:
        registry = fetch_registry()
    except Exception:
        raise RuntimeError('registry_access_hold') from None
    history = [r for r in registry if r.get("status") == "historical_v2_suppression"]
    if len(history) != 1:
        raise RuntimeError("incomplete_historical_registry")
    selected = source[offset:offset + BATCH_SIZE]
    summary = Counter()
    for row in selected:
        summary.update(check_one(row, history[0]))
    if (summary["checked"] != len(selected)
            or summary["historical_email_excluded"] != len(selected)):
        raise RuntimeError("batch_incomplete")
    return {
        "offset": offset, "size": len(selected), "expected_total": EXPECTED,
        "counts": {k: int(summary[k]) for k in (
            "checked", "historical_email_excluded", "provider_blocked",
            "no_prior_mail_copy", "prior_copy_present",
            "incomplete_copy_fields", "first_party_metadata_hold",
            "first_party_metadata_pass", "finding_format_hold",
            "new_validator_pass", "new_validator_hold",
        )},
        "source_mutated": False, "registry_mutated": False,
        "drafts_created": 0, "emails_sent": 0, "data_exposed": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", required=True, type=int)
    args = parser.parse_args()
    try:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            report = run(args.offset)
    except Exception as exc:
        # Only literal, audited error stages are printable; never arbitrary
        # provider responses or contact values.
        allowed = {
            "missing_source_access", "source_read_failed", "source_page_invalid",
            "source_identity_mismatch", "source_duplicates_or_invalid",
            "source_cursor_invalid", "source_page_limit", "source_total_changed",
            "registry_access_hold", "incomplete_historical_registry",
            "missing_history_suppression", "batch_incomplete",
        }
        stage = str(exc) if str(exc) in allowed else "unknown_hold"
        print("HISTORICAL_MAIL_CHECK=red stage=" + stage + " details_suppressed")
        return 1
    print("HISTORICAL_MAIL_CHECK=green " + json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
