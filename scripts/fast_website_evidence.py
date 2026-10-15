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
from urllib.parse import quote

import requests

from approved_handoff import COLS as APPROVED_COLUMNS
from private_candidate_handoff import SHEET_ID, authorized_writer
from verify_official_lead import (BRANCH_PROOF, CATEGORIES, MAX_BYTES,
                                  PublicHTML, norm, verify_official_site)

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
    values = response.json().get("values")
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


class Capture:
    """One connection-pooled session PER worker, never shared across threads."""
    def __init__(self):
        self.session = requests.Session()
        self.pages = []

    def get(self, url, **kwargs):
        response = self.session.get(url, **kwargs)
        if kwargs.get("stream") and response.status_code == 200:
            original = response.iter_content
            owner = self

            def capture(*args, **kw):
                saved = bytearray()
                complete = True
                for chunk in original(*args, **kw):
                    if len(saved) + len(chunk) <= MAX_BYTES:
                        saved.extend(chunk)
                    else:
                        complete = False
                    yield chunk
                if complete and b"<" in saved:
                    parsed = PublicHTML()
                    parsed.feed(saved.decode("utf-8", errors="replace"))
                    owner.pages.append((url, " ".join(parsed.texts)))
            response.iter_content = capture
        return response

    def close(self):
        self.session.close()


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
    match = re.search(re.escape(phrase), text, re.I)
    if not match:
        # Accents or casing may differ in the normalization-aware matcher.
        return ""
    return re.sub(r"\s+", " ", text[max(0, match.start()-35):match.end()+85]).strip()[:150]


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


def inspect(record):
    """No unverified website fact ever receives a confirmed status."""
    reverse = {}
    for category, (_, branch) in CATEGORIES.items():
        reverse.setdefault(branch, category)
    category = reverse.get(record["branch"])
    result = dict(record, checked_at=_utc_now(), email_source_url="",
                  facts_json="[]", feature_mentions_json="[]",
                  status="needs_manual_check", reason="official_source_unconfirmed")
    if not category:
        result["reason"] = "unsupported_branch"
        return result
    hint = {"name_hint": record["company"], "website_hint": record["website"],
            "category_hint": category, "country_hint": "NL"}
    cap = Capture()
    try:
        official = verify_official_site(hint, session=cap,
                                        expected_email=record["email"])
        if not official or official["email"].casefold() != record["email"].casefold():
            result["reason"] = "official_company_or_email_not_confirmed"
            return result
        if official["branche_meervoud"] != record["branch"]:
            result["reason"] = "branch_mismatch"
            return result
        if not ZIP_NL.search(" ".join(page for _, page in cap.pages)):
            result["reason"] = "dutch_locality_not_confirmed"
            return result
        terms = DETAILS.get(record["branch"], ())
        facts = _mentions(cap.pages, terms, 2)
        # An industry word is proof of general activity only, not a unique hook.
        activity = _mentions(cap.pages, BRANCH_PROOF[record["branch"]], 1)
        if not activity:
            result["reason"] = "activity_not_confirmed"
            return result
        features = []
        for label, words in FEATURE_MENTIONS.items():
            for finding in _mentions(cap.pages, words, 1):
                features.append({**finding, "feature": label,
                                 "certainty": "text_mention_only"})
        result["email_source_url"] = official["source_url"]
        result["facts_json"] = json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
        result["feature_mentions_json"] = json.dumps(features[:6], ensure_ascii=False, separators=(",", ":"))
        result["status"] = "verified_with_detail" if facts else "verified_activity_only"
        result["reason"] = "official_email_and_local_activity_confirmed"
        if record["email"].rsplit("@", 1)[-1].removeprefix("www.") != \
                record["website"].split("/")[2].removeprefix("www.").split(":")[0]:
            result["status"] = "needs_manual_check"
            result["reason"] = "cross_domain_email_needs_independent_association"
        return result
    except Exception:
        result["reason"] = "bounded_official_site_request_failed"
        return result
    finally:
        cap.close()


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


def _persist(conn, sheet_id, existing, new):
    merged = dict(existing)
    merged.update({r["record_key"]: r for r in new})
    if len(merged) > MAX_RECORDS:
        raise RuntimeError("evidence_private_cache_full")
    expected = [list(COLUMNS)] + [[str(row.get(k, "")) for k in COLUMNS]
                                   for row in merged.values()]
    cell_rows = [{"values": [
        {"userEnteredValue": {"stringValue": c}} if c else {} for c in row
    ]} for row in expected]
    url = "https://sheets.googleapis.com/v4/spreadsheets/" + SHEET_ID
    resp = conn.post(url + ":batchUpdate", timeout=45, json={"requests": [{
        "updateCells": {"range": {"sheetId": sheet_id, "startRowIndex": 0,
                         "endRowIndex": len(expected), "startColumnIndex": 0,
                         "endColumnIndex": len(COLUMNS)},
                        "rows": cell_rows, "fields": "userEnteredValue"}}]})
    if resp.status_code != 200:
        raise RuntimeError("evidence_private_write_failed")
    if _read(conn, TAB + "!A1:N" + str(len(expected))) != expected:
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
    return {
        "requested": len(candidates), "website_checks": len(checked),
        "reused_recent": len(reused),
        "verified": sum(x["status"].startswith("verified_") for x in checked) + len(reused),
        "needs_manual_check": sum(not x["status"].startswith("verified_") for x in checked),
        "seconds": round(time.monotonic() - start, 2),
        "mailbox_writes": 0, "emails_sent": 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Private parallel official-site evidence, no mail")
    parser.add_argument("--source", choices=tuple(SOURCES), required=True)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.batch, force=args.force), sort_keys=True))


if __name__ == "__main__":
    main()
