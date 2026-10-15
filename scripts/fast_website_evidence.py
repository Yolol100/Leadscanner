"""Fast, private, opt-in recheck of official company websites.

Reads existing Approved or Review450 records; NEVER edits them, produces mail
copy, sends anything, or publishes prospect facts into GitHub output.
One homepage + at most one same-host contact page, with exact email readback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

import requests

from approved_handoff import COLS as APPROVED_COLUMNS
from private_candidate_handoff import SHEET_ID, authorized_writer
from verify_official_lead import (BRANCH_PROOF, CATEGORIES, norm,
                                  verify_official_site)

REVIEW_COLUMNS = (
    "draft_id", "created_at", "company", "email", "source_url", "subject",
    "body", "website", "cluster", "branch", "evidence_url", "evidence",
    "origin", "qa_status", "run_id", "task")
SOURCES = {
    "Approved": ("Approved!A1:I101", list(APPROVED_COLUMNS), 100),
    "Review450": ("Review450!A1:P451", list(REVIEW_COLUMNS), 450),
}
TAB = "WebsiteEvidence"
COLUMNS = (
    "record_key", "source_tab", "source_row", "source_sha256", "company",
    "website", "email", "branch", "email_source_url", "facts_json",
    "feature_mentions_json", "checked_at", "status", "reason")
BATCH_SIZE = 100
MAX_WORKERS = 8
MAX_RECORDS = 900
TTL_SECONDS = 24 * 3600
ZIP_NL = re.compile(r"\b[1-9]\d{3}\s?[A-Z]{2}\b")
DETAILS = {
    "restaurants": ("groepsarrangement", "groepsmenu", "afhalen", "catering", "high tea"),
    "fietsenwinkels": ("proefrit", "elektrische fiets", "tweedehands fietsen", "fietsverhuur"),
    "kappers": ("balayage", "bruidskapsel", "haarkleuring", "highlights"),
    "bloemisten": ("rouwbloemen", "bruidsboeket", "bloemenabonnement"),
    "hoveniers": ("tuinontwerp", "tuinonderhoud", "bestrating", "bedrijfstuin"),
    "fysiotherapiepraktijken": ("handtherapie", "sportfysiotherapie", "manuele therapie"),
    "schoonheidssalons": ("pedicure", "gezichtsbehandeling", "nagelverzorging"),
    "garages": ("apk", "camperonderhoud", "bandenwissel"),
    "schilders": ("houtrotherstel", "kleuradvies", "restauratie"),
    "stukadoors": ("cinewall", "spuitwerk", "buitenstucwerk"),
    # Do not infer a generic sales angle from a branch label. These are
    # concrete, independently confirmable offers on the official website.
    "logiesbedrijven": ("familiekamer", "fietsverhuur", "vergaderruimte",
                        "ontbijtbuffet", "huisdieren toegestaan"),
    "horecazaken": ("high tea", "brunch", "borrelplank", "live muziek",
                    "catering"),
    "sportscholen": ("personal training", "groepsles", "proefles", "pilates",
                    "bootcamp"),
}
FEATURE_MENTIONS = {
    "booking": ("online boeken", "boek een afspraak", "afspraak maken", "boekingssysteem"),
    "webshop": ("webshop", "online bestellen", "winkelwagen"),
    "reservation": ("online reserveren", "tafel reserveren", "reserveringsformulier"),
    "test_ride": ("proefrit", "testrit"),
    "groups": ("groepsarrangement", "groepsreservering", "groepsmenu"),
    "takeaway": ("afhalen", "afhaalmenu"),
}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True).encode()).hexdigest()


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _fresh(value):
    try:
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - date).total_seconds()
        return date.tzinfo is not None and 0 <= age < TTL_SECONDS
    except (TypeError, ValueError, AttributeError):
        return False


def _read(conn, range_a1):
    url = ("https://sheets.googleapis.com/v4/spreadsheets/" + SHEET_ID +
           "/values/" + quote(range_a1, safe=""))
    response = conn.get(url, timeout=35)
    if response.status_code != 200:
        raise RuntimeError("private_evidence_sheet_read_failed")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("private_evidence_sheet_shape_invalid")
    # A valid empty Google Sheets range omits the 'values' field.
    # Caller _input still requires all official source headers; only an
    # interrupted or freshly created evidence-cache tab may be empty.
    values = payload.get("values", [])
    if not isinstance(values, list):
        raise RuntimeError("private_evidence_sheet_shape_invalid")
    return values


def _input(conn, source, batch):
    if source not in SOURCES or not isinstance(batch, int):
        raise ValueError("evidence_source_invalid")
    location, columns, maximum = SOURCES[source]
    max_batches = (maximum + BATCH_SIZE - 1) // BATCH_SIZE
    if not 1 <= batch <= max_batches:
        raise ValueError("evidence_batch_invalid")
    raw = _read(conn, location)
    if not raw or raw[0] != columns:
        raise RuntimeError("evidence_source_headers_changed")
    if source == "Review450" and len(raw) != 451:
        raise RuntimeError("evidence_review450_incomplete")
    if source == "Approved" and not 2 <= len(raw) <= 101:
        raise RuntimeError("evidence_approved_empty")
    start = (batch - 1) * BATCH_SIZE
    extracted = []
    for index in range(start, min(maximum, len(raw) - 1, start + BATCH_SIZE)):
        values = raw[index + 1]
        if len(values) != len(columns):
            raise RuntimeError("evidence_source_row_invalid")
        row = dict(zip(columns, values))
        branch = row["branch"] if source == "Review450" else row["branche_meervoud"]
        if (not all(row.get(k) for k in ("company", "website", "email")) or
                not branch or
                (source == "Approved" and row["status"] != "verified_website_and_email")):
            raise RuntimeError("evidence_source_record_not_verified")
        # SHA binds identity and branch but does not assume unchanged live content.
        key = (source + ":" + row["draft_id"] if source == "Review450" else
               "Approved:" + _digest([row["company"], row["website"], row["email"]])[:24])
        extracted.append({
            "record_key": key, "source_tab": source, "source_row": str(index + 2),
            "source_sha256": _digest([row["company"], row["website"], row["email"], branch]),
            "company": row["company"], "website": row["website"],
            "email": row["email"], "branch": branch,
        })
    if not extracted or len({r["record_key"] for r in extracted}) != len(extracted):
        raise RuntimeError("evidence_empty_or_duplicate_batch")
    return extracted, _digest(raw)


def _has(text, phrase):
    text, phrase = norm(text), norm(phrase)
    if not phrase:
        return False
    for match in re.finditer(r"\b" + re.escape(phrase) + r"[a-z]*\b", text):
        # Do not present explicitly denied services as offered services.
        prefix = text[max(0, match.start() - 45):match.start()]
        if re.search(r"\b(geen|niet|no|not)\b(?:\s+\w+){0,3}\s*$", prefix):
            continue
        return True
    return False


def _excerpt(text, phrase):
    """Return the supported literal mention, never the first denied mention.

    _has() may skip a negative first occurrence and accept a later positive
    one. The extracted quote must follow that same decision, not re-search
    from the beginning and accidentally save the negated sentence.
    """
    pattern = r"\b" + re.escape(phrase) + r"[a-zA-ZÀ-ÿ]*\b"
    for match in re.finditer(pattern, text, re.I):
        before = norm(text[max(0, match.start()-90):match.start()])
        if re.search(r"\b(geen|niet|no|not)\b(?:\s+\w+){0,3}\s*$", before):
            continue
        last_boundary = max(text.rfind(mark, 0, match.start()) for mark in ".?!\n")
        start = max(last_boundary + 1, match.start()-35)
        return re.sub(r"\s+", " ", text[start:match.end()+85]).strip()[:150]
    return ""


def _mentions(pages, words, limit):
    out = []
    for term in words:
        for url, page in pages:
            if _has(page, term):
                excerpt = _excerpt(page, term)
                if excerpt:
                    out.append({"term": term, "excerpt": excerpt, "source_url": url})
                    break
        if len(out) == limit:
            break
    return out


def _initial_result(record):
    return dict(record, checked_at=_utc_now(), email_source_url="",
                facts_json="[]", feature_mentions_json="[]",
                status="needs_manual_check", reason="official_source_unconfirmed")


def inspect_verified(record, official, pages):
    """Classify facts from verified pages without a second network request.

    The official business/email check must already have been performed by
    verify_official_site. A missing or mismatching proof is fail-closed.
    """
    result = _initial_result(record)
    if not isinstance(official, dict) or not isinstance(pages, list):
        result["reason"] = "official_company_or_email_not_confirmed"
        return result
    if (official.get("email", "").casefold() != record["email"].casefold() or
            official.get("branche_meervoud") != record["branch"]):
        result["reason"] = "official_identity_email_or_branch_mismatch"
        return result
    safe_pages = []
    site = urlsplit(record["website"])
    if site.scheme not in ("https", "http") or not site.hostname:
        result["reason"] = "website_url_invalid"
        return result
    for page in pages[:2]:
        if not isinstance(page, (list, tuple)) or len(page) != 2:
            continue
        page_url, page_text = page
        url = urlsplit(str(page_url))
        if (url.scheme not in ("https", "http") or
                not url.hostname or
                url.hostname.removeprefix("www.").casefold() !=
                site.hostname.removeprefix("www.").casefold()):
            continue
        safe_pages.append((str(page_url), str(page_text)[:750000]))
    if not safe_pages:
        result["reason"] = "source_pages_not_captured"
        return result
    if not ZIP_NL.search(" ".join(text for _, text in safe_pages)):
        result["reason"] = "dutch_locality_not_confirmed"
        return result
    try:
        terms = DETAILS.get(record["branch"], ())
        facts = _mentions(safe_pages, terms, 2)
        activity = _mentions(safe_pages, BRANCH_PROOF[record["branch"]], 1)
        if not activity:
            result["reason"] = "activity_not_confirmed"
            return result
        features = []
        for label, words in FEATURE_MENTIONS.items():
            for finding in _mentions(safe_pages, words, 1):
                features.append({**finding, "feature": label,
                                 "certainty": "text_mention_only"})
        result["email_source_url"] = str(official.get("source_url", ""))
        result["facts_json"] = json.dumps(facts, ensure_ascii=False,
                                           separators=(",", ":"))
        result["feature_mentions_json"] = json.dumps(features[:6],
                                                      ensure_ascii=False,
                                                      separators=(",", ":"))
        result["status"] = "verified_with_detail" if facts else "verified_activity_only"
        result["reason"] = "official_email_and_local_activity_confirmed"
        email_domain = record["email"].rsplit("@", 1)[-1].lower()
        host = site.hostname.removeprefix("www.").casefold()
        if email_domain != host:
            result["status"] = "needs_manual_check"
            result["reason"] = "cross_domain_email_needs_independent_association"
        return result
    except (ValueError, TypeError, KeyError, re.error):
        result["reason"] = "source_text_processing_failed"
        return result


def inspect(record):
    """One HTTP verification pass, reusing already-parsed official text."""
    started = time.monotonic()
    result = _initial_result(record)
    try:
        reverse = {}
        for category, (_, branch) in CATEGORIES.items():
            reverse.setdefault(branch, category)
        category = reverse.get(record["branch"])
        if not category:
            result["reason"] = "unsupported_branch"
        else:
            hint = {"name_hint": record["company"], "website_hint": record["website"],
                    "category_hint": category, "country_hint": "NL"}
            with requests.Session() as session:
                official = verify_official_site(
                    hint, session=session, expected_email=record["email"],
                    collect_evidence=True)
            result = inspect_verified(record, official,
                     official.get("_captured_pages", []) if official else [])
    except Exception:
        result = _initial_result(record)
        result["reason"] = "bounded_official_site_request_failed"
    result["_check_duration_ms"] = round(
        (time.monotonic() - started) * 1000)
    return result


def _cache_id(conn):
    base = "https://sheets.googleapis.com/v4/spreadsheets/" + SHEET_ID
    resp = conn.get(base + "?fields=sheets(properties(sheetId,title))", timeout=30)
    if resp.status_code != 200:
        raise RuntimeError("evidence_metadata_unavailable")
    for sheet in resp.json().get("sheets", []):
        prop = sheet.get("properties", {})
        if prop.get("title") == TAB:
            return prop["sheetId"], False
    resp = conn.post(base + ":batchUpdate", timeout=30, json={"requests": [{
        "addSheet": {"properties": {"title": TAB,
            "gridProperties": {"rowCount": 1000, "columnCount": len(COLUMNS),
                               "frozenRowCount": 1}}}}]})
    if resp.status_code != 200:
        raise RuntimeError("evidence_private_tab_create_failed")
    return resp.json()["replies"][0]["addSheet"]["properties"]["sheetId"], True


def _cache(conn):
    raw = _read(conn, TAB + "!A1:N1000")
    # A run interrupted just after addSheet may leave a genuinely empty tab.
    # Retrying is safe: recheck every source before the first actual write.
    if not raw:
        return {}
    if raw[0] != list(COLUMNS):
        raise RuntimeError("evidence_cache_header_invalid")
    result = {}
    for line in raw[1:]:
        if len(line) != len(COLUMNS):
            raise RuntimeError("evidence_cache_row_shape_invalid")
        item = dict(zip(COLUMNS, line))
        if item["record_key"] in result:
            raise RuntimeError("evidence_duplicate_cache_key")
        result[item["record_key"]] = item
    return result


def _cache_rows_after_retention(existing, new):
    """Bound cache growth without ever evicting the active batch or 450 history.

    WebsiteEvidence is a reusable snapshot cache, not canonical LeadHistory.
    Rows older than seven days from a previous Approved snapshot may expire.
    """
    merged = dict(existing)
    merged.update({r["record_key"]: r for r in new})
    active = {r["record_key"] for r in new}
    now = datetime.now(timezone.utc)
    for key, row in list(merged.items()):
        if key in active or row.get("source_tab") != "Approved":
            continue
        try:
            checked = datetime.fromisoformat(
                str(row["checked_at"]).replace("Z", "+00:00"))
            outdated = (checked.tzinfo is None or
                        (now - checked).total_seconds() > 7 * 86400)
        except (KeyError, ValueError, TypeError):
            outdated = True
        if outdated:
            del merged[key]
    if len(merged) > MAX_RECORDS:
        raise RuntimeError("evidence_private_cache_full")
    return merged


def _persist(conn, sheet_id, existing, new):
    merged = _cache_rows_after_retention(existing, new)
    expected = [list(COLUMNS)] + [[str(row.get(k, "")) for k in COLUMNS]
                                   for row in merged.values()]
    # Old trailing rows must be cleared when expired evidence is pruned.
    total = max(len(expected), len(existing) + 1)
    padded = expected + [[""] * len(COLUMNS) for _ in range(total-len(expected))]
    cell_rows = [{"values": [
        {"userEnteredValue": {"stringValue": c}} if c else {} for c in row
    ]} for row in padded]
    url = "https://sheets.googleapis.com/v4/spreadsheets/" + SHEET_ID
    resp = conn.post(url + ":batchUpdate", timeout=45, json={"requests": [{
        "updateCells": {"range": {"sheetId": sheet_id, "startRowIndex": 0,
                         "endRowIndex": total, "startColumnIndex": 0,
                         "endColumnIndex": len(COLUMNS)},
                        "rows": cell_rows, "fields": "userEnteredValue"}}]})
    if resp.status_code != 200:
        raise RuntimeError("evidence_private_write_failed")
    if _read(conn, TAB + "!A1:N" + str(total)) != expected:
        raise RuntimeError("evidence_private_readback_mismatch")


def run(source, batch=1, *, conn=None, worker=inspect, force=False):
    start = time.monotonic()
    conn = conn if conn is not None else authorized_writer()
    candidates, input_sha = _input(conn, source, batch)
    tab_id, created = _cache_id(conn)
    existing = {} if created else _cache(conn)
    reused = [
        existing[row["record_key"]] for row in candidates
        if not force and row["record_key"] in existing
        and existing[row["record_key"]]["source_sha256"] == row["source_sha256"]
        and existing[row["record_key"]]["status"].startswith("verified_")
        and _fresh(existing[row["record_key"]]["checked_at"])
    ]
    reused_ids = {row["record_key"] for row in reused}
    pending = [row for row in candidates if row["record_key"] not in reused_ids]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        checked = list(pool.map(worker, pending))
    if _input(conn, source, batch)[1] != input_sha:
        raise RuntimeError("evidence_source_changed_during_scan")
    if checked:
        _persist(conn, tab_id, existing, checked)
    durations = sorted(
        x["_check_duration_ms"] for x in checked
        if isinstance(x.get("_check_duration_ms"), int)
        and 0 <= x["_check_duration_ms"] <= 3600000)
    n = len(durations)
    return {
        "requested": len(candidates), "website_checks": len(checked),
        "reused_recent": len(reused),
        "verified": sum(x["status"].startswith("verified_") for x in checked) + len(reused),
        "needs_manual_check": sum(not x["status"].startswith("verified_") for x in checked),
        "duration_p50_ms": durations[(n - 1) // 2] if n else None,
        "duration_p95_ms": durations[max(0, (n * 95 + 99) // 100 - 1)] if n else None,
        "seconds": round(time.monotonic() - start, 2),
        "mailbox_writes": 0, "emails_sent": 0,
    }


def _prepare_preverified_records(records, approved):
    """Derive official-site facts from the SAME trusted verification pass."""
    if (not isinstance(approved, list) or len(records) != len(approved)
            or not approved or len(approved) > BATCH_SIZE):
        raise RuntimeError("preverified_approved_invalid")
    output = []
    for record, actual in zip(records, approved):
        if (not isinstance(actual, dict) or
                not isinstance(actual.get("_captured_pages"), list) or
                not actual["_captured_pages"]):
            raise RuntimeError("preverified_official_pages_missing")
        if (record["company"] != actual.get("company") or
                record["website"] != actual.get("website") or
                record["email"] != actual.get("email") or
                record["branch"] != actual.get("branche_meervoud") or
                record["source_sha256"] != _digest([
                    record["company"], record["website"],
                    record["email"], record["branch"]])):
            raise RuntimeError("preverified_approved_snapshot_mismatch")
        output.append(inspect_verified(record, actual, actual["_captured_pages"]))
    return output


def prepare_new_approved_evidence(approved, expected_rows):
    """Build facts before saving an Approved snapshot; no network or writes."""
    if (not isinstance(expected_rows, list) or not expected_rows or
            expected_rows[0] != list(APPROVED_COLUMNS) or
            len(expected_rows) != len(approved) + 1):
        raise RuntimeError("preverified_expected_approved_invalid")
    records = []
    for number, line in enumerate(expected_rows[1:], start=2):
        if (len(line) != len(APPROVED_COLUMNS) or
                line[8] != "verified_website_and_email"):
            raise RuntimeError("preverified_expected_approved_invalid")
        _, company, website, email, _, _, branch, _, _ = line
        records.append({
            "record_key": "Approved:" + _digest([company, website, email])[:24],
            "source_tab": "Approved", "source_row": str(number),
            "source_sha256": _digest([company, website, email, branch]),
            "company": company, "website": website, "email": email,
            "branch": branch,
        })
    return _prepare_preverified_records(records, approved)


def plan_atomic_evidence_write(conn, results):
    """Prepare one updateCells for the Approved+History+Evidence transaction.

    A missing evidence tab is created EMPTY before any lead/history commit.
    A Sheets batchUpdate combining this request and the other two is atomic.
    """
    if (not isinstance(results, list) or not results or
            len(results) > BATCH_SIZE or
            len({r.get("record_key") for r in results}) != len(results) or
            any(r.get("source_tab") != "Approved" for r in results)):
        raise RuntimeError("evidence_atomic_input_invalid")
    tab_id, created = _cache_id(conn)
    existing = {} if created else _cache(conn)
    merged = _cache_rows_after_retention(existing, results)
    expected = [list(COLUMNS)] + [
        [str(r.get(k, "")) for k in COLUMNS] for r in merged.values()]
    length = max(len(expected), len(existing) + 1)
    padded = expected + [[""] * len(COLUMNS) for _ in range(length-len(expected))]
    rows = [{"values": [
        {"userEnteredValue": {"stringValue": item}} if item else {}
        for item in row]} for row in padded]
    request = {"updateCells": {
        "range": {"sheetId": tab_id, "startRowIndex": 0,
                  "endRowIndex": length, "startColumnIndex": 0,
                  "endColumnIndex": len(COLUMNS)},
        "rows": rows, "fields": "userEnteredValue"}}
    return request, expected, existing


def store_preverified_approved(approved, *, conn=None):
    """Persist facts from the *same* first verification, with zero website GETs.

    Called only after store_approved has atomically saved the new Approved
    snapshot and historical suppressions. Verifies that the snapshot is still
    exactly the same before persisting the derived evidence. Never touches
    Review450, DraftQueue, IMAP or public GitHub data.
    """
    if not isinstance(approved, list) or len(approved) > BATCH_SIZE:
        raise ValueError("preverified_approved_invalid")
    if not approved:
        return {"source_rows": 0, "captured_without_refetch": 0,
                "verified_with_detail": 0, "needs_manual_check": 0}
    conn = conn if conn is not None else authorized_writer()
    records, checksum = _input(conn, "Approved", 1)
    if len(records) != len(approved):
        raise RuntimeError("preverified_approved_snapshot_count_changed")
    results = _prepare_preverified_records(records, approved)
    if _input(conn, "Approved", 1)[1] != checksum:
        raise RuntimeError("preverified_approved_changed_during_review")
    tab_id, created = _cache_id(conn)
    existing = {} if created else _cache(conn)
    _persist(conn, tab_id, existing, results)
    return {"source_rows": len(results),
            "captured_without_refetch": len(results),
            "verified_with_detail": sum(r["status"] == "verified_with_detail" for r in results),
            "needs_manual_check": sum(r["status"] == "needs_manual_check" for r in results)}


def main():
    parser = argparse.ArgumentParser(description="Private parallel official-site evidence, no mail")
    parser.add_argument("--source", choices=tuple(SOURCES), required=True)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.batch, force=args.force), sort_keys=True))


if __name__ == "__main__":
    main()
