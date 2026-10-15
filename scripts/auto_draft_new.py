"""Strictly private, scheduled FIRST-DRAFT handoff for new, evidence-rich leads.

This is never an email sender. It cannot process historical Review450, and never
modifies existing DraftQueue rows. It only uses the current GitHub-run Approved
snapshot and the already verified WebsiteEvidence. A human MUST review Drafts.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

from approved_handoff import COLS as APPROVED_HEADERS, HISTORY_COLS
from dedupe_preflight import match_candidate, normalize_company, normalize_domain
from draft_queue_readonly import (
    DRAFT_QUEUE_ID, DRAFT_QUEUE_TAB, HEADERS as DRAFT_HEADERS,
    _validate_row as validate_draft, valid_general_email,
)
from fast_website_evidence import (
    COLUMNS as EVIDENCE_HEADERS, SHEET_ID as SOURCE_SHEET_ID,
    _digest as evidence_digest, _fresh as fresh_evidence,
)
from private_candidate_handoff import authorized_writer
from registry_readonly import load_suppressions
from myhost_draft import create_batch_from_queue
from verify_official_lead import CATEGORIES

MAX_DRAFTS = 25  # Controlled rollout; never 450
AUTO_TAB = "AutoDraftState"
STATE_HEADERS = ["auto_run_id", "draft_id", "identity_sha256",
                 "source_sha256", "quality_status"]
OPT_OUT = "Liever geen e-mails meer? Antwoord met 'nee', dan laat ik het hierbij."
SAFE_TERM = re.compile(r"^[\wÀ-ÿ][\wÀ-ÿ \-/]{2,48}$", re.UNICODE)
RUN_ID = re.compile(r"^[0-9]{1,20}$")
DRAFT_RE = re.compile(r"^draft-[0-9a-f]{32}$")

# A factual observation + a small, relevant sample of content — NOT a claim
# that an existing booking, webshop, FAQ or contact feature is absent.
SERVICE_CONTEXT = {
    "proefrit": "wat klanten bij een proefrit kunnen verwachten",
    "tweedehands fietsen": "de afwegingen bij een tweedehands fiets",
    "fietsverhuur": "de praktische vragen bij fietsverhuur",
    "groepsarrangement": "de voorbereiding van een groepsbezoek",
    "groepsmenu": "de mogelijkheden voor groepen",
    "afhalen": "de belangrijkste vragen over afhalen",
    "high tea": "wat bezoekers bij een high tea kunnen verwachten",
    "tuinontwerp": "de stappen van een eerste idee tot een tuinplan",
    "tuinonderhoud": "het verschil tussen eenmalig en terugkerend onderhoud",
    "bestrating": "wat klanten vooraf moeten weten over bestrating",
    "bedrijfstuin": "de keuzes voor onderhoud van een bedrijfstuin",
    "houtrotherstel": "wanneer houtrotherstel relevant is",
    "restauratie": "de stappen in een restauratietraject",
    "kleuradvies": "hoe klanten zich op kleuradvies voorbereiden",
    "balayage": "wat klanten voor een balayagebehandeling willen weten",
    "bruidskapsel": "de voorbereiding van een bruidskapsel",
    "haarkleuring": "de keuzes voor een haarkleuring",
    "highlights": "de verschillen tussen kleurbehandelingen",
    "pedicure": "de praktische voorbereiding voor een pedicurebehandeling",
    "gezichtsbehandeling": "wat klanten bij een gezichtsbehandeling verwachten",
    "nagelverzorging": "de verschillende mogelijkheden voor nagelverzorging",
    "apk": "wat klanten bij een APK-keuring kunnen verwachten",
    "camperonderhoud": "de voorbereiding van een onderhoudsafspraak voor een camper",
    "bandenwissel": "het juiste moment voor een bandenwissel",
    "bruidsboeket": "de stappen naar een persoonlijk bruidsboeket",
    "rouwbloemen": "de keuzes bij passende rouwbloemen",
    "bloemenabonnement": "hoe een bloemenabonnement praktisch werkt",
    "handtherapie": "wat een cliënt van een handtherapietraject kan verwachten",
    "sportfysiotherapie": "de eerste stappen bij sportfysiotherapie",
    "manuele therapie": "wat een eerste behandeling inhoudt",
    "cinewall": "de keuzes in formaat en afwerking van een cinewall",
    "spuitwerk": "wat vooraf belangrijk is bij spuitwerk",
    "buitenstucwerk": "de voorbereiding van buitenstucwerk",
    "catering": "hoe klanten een cateringaanvraag kunnen voorbereiden",
}
# Do not generate a new factual claim by automatically inflecting arbitrary
# website text or guessing a missing website function.
SUBJECT_MAX = 95


def _read(conn, spreadsheet, a1):
    url = ("https://sheets.googleapis.com/v4/spreadsheets/" + spreadsheet
           + "/values/" + quote(a1, safe=""))
    response = conn.get(url, timeout=30)
    if response.status_code != 200:
        raise RuntimeError("autodraft_private_source_read_failed")
    rows = response.json().get("values")
    if not isinstance(rows, list):
        raise RuntimeError("autodraft_private_source_shape_invalid")
    return rows


def _fingerprint(record):
    return hashlib.sha256(json.dumps(
        [record["company"], record["website"], record["email"], record["branch"]],
        ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def _host(url):
    try:
        p = urlsplit(str(url))
        return (p.hostname or "").lower().removeprefix("www.") if p.scheme == "https" else ""
    except (TypeError, ValueError):
        return ""


def _identity(row):
    return hashlib.sha256(json.dumps([
        normalize_company(row["company"]), normalize_domain(row["website"]),
        row["email"].casefold()], sort_keys=True).encode()).hexdigest()


def _parse_table(values, headers, *, allow_empty=False):
    if not values:
        if allow_empty:
            return []
        raise RuntimeError("autodraft_missing_private_headers")
    if values[0] != list(headers):
        raise RuntimeError("autodraft_private_headers_changed")
    result = []
    for raw in values[1:]:
        if len(raw) > len(headers) or not raw:
            raise RuntimeError("autodraft_private_row_invalid")
        row = [str(x or "") for x in raw] + [""] * (len(headers) - len(raw))
        result.append(dict(zip(headers, row)))
    return result


def _load_latest(conn, run_id):
    approved_raw = _read(conn, SOURCE_SHEET_ID, "Approved!A1:I101")
    approved = _parse_table(approved_raw, APPROVED_HEADERS)
    if not approved:
        return [], {}, approved_raw
    # Existing Approved data must be owned by THIS scheduled discovery run,
    # never the previous 57 businesses or any of the historical 450.
    if any(x["run_id"] != run_id for x in approved):
        return [], {}, approved_raw
    evidence_raw = _read(conn, SOURCE_SHEET_ID, "WebsiteEvidence!A1:N1000")
    evidence = _parse_table(evidence_raw, EVIDENCE_HEADERS)
    seen = {}
    for item in evidence:
        if item["record_key"] in seen:
            raise RuntimeError("autodraft_duplicate_private_evidence")
        seen[item["record_key"]] = item
    # Each current lead must appear in the permanent approved history.
    history_raw = _read(conn, SOURCE_SHEET_ID, "LeadHistory!A1:H10000")
    history = _parse_table(history_raw, HISTORY_COLS)
    history_current = {(_identity({
        "company": h["company"], "website": h["website"],
        "email": h["email"]}), h["first_seen_run"])
                       for h in history if h["status"] in
                       ("verified_lead", "draft_queued", "draft_saved")}
    for row in approved:
        key = _identity({"company": row["company"], "website": row["website"],
                         "email": row["email"]})
        if (key, run_id) not in history_current:
            raise RuntimeError("autodraft_historical_readback_missing")
    return approved, seen, approved_raw


def _compose(row, fact):
    term = str(fact.get("term", "")).strip().lower()
    if not SAFE_TERM.fullmatch(term) or term not in SERVICE_CONTEXT:
        return None
    if any(ch in term for ch in "\n\r{}[]"):
        return None
    guidance = SERVICE_CONTEXT[term]
    greeting = row["greeting"].strip()
    if greeting not in ("Goedendag,", "Hoi,") and not re.fullmatch(
            r"Hoi [A-ZÀ-ÿ][A-Za-zÀ-ÿ-]{1,40},", greeting):
        return None
    subject = f"Korte vraag over {term} bij {row['company']}"
    if len(subject) > SUBJECT_MAX:
        subject = f"Korte vraag over {term}"
    # One confirmed observation, one small illustrative proposal, one CTA.
    # Do not imply the site is broken or a booking function is missing.
    # One of the six original industry angles, personalized only with facts
    # already confirmed on the official site. No non-existent feature claims.
    angles = {
        "1": f"een heldere uitleg over {guidance}, passend bij jullie huidige aanvraagroute",
        "2": f"praktische informatie over {guidance}, naast jullie huidige afsprakenroute",
        "3": f"een mobiel leesbaar overzicht over {guidance}, passend bij de huidige contact- of bestelroute",
        "4": f"een korte toelichting over {guidance}, zodat bezoekers gericht contact kunnen opnemen",
        "5": f"een rustig en begrijpelijk overzicht over {guidance}, naast de bestaande persoonlijke contactroute",
        "6": f"een helder voorbeeld over {guidance}, aansluitend op jullie bestaande contactmogelijkheden",
    }
    angle = angles.get(row.get("cluster"))
    if not angle:
        return None
    body = (f"{greeting}\n\n"
            f"Jullie noemen {term} op de website.\n\n"
            f"Ik kan een kort voorbeeld maken met {angle}. "
            "Dat is een aanvulling op wat jullie al aanbieden, niet een "
            "vervanging van jullie bestaande werkwijze.\n\n"
            "Mag ik zo'n voorbeeld sturen?\n\n"
            f"{OPT_OUT}\n\nGroet,\nAndrew")
    return subject, body


def _eligible(row, evidence):
    matching_clusters = {str(cluster) for cluster, label in CATEGORIES.values()
                         if label == row.get("branche_meervoud")}
    if row.get("cluster") not in matching_clusters:
        return None
    if (row.get("status") != "verified_website_and_email" or
            not valid_general_email(row.get("email", "")) or
            not _host(row.get("website", "")) or
            _host(row["website"]) != row["email"].rsplit("@", 1)[-1].lower()):
        return None
    key = "Approved:" + evidence_digest(
        [row["company"], row["website"], row["email"]])[:24]
    fact_row = evidence.get(key)
    if not fact_row or fact_row.get("status") != "verified_with_detail":
        return None
    if (fact_row.get("source_sha256") != evidence_digest(
            [row["company"], row["website"], row["email"],
             row["branche_meervoud"]]) or
            fact_row.get("company") != row["company"] or
            fact_row.get("website") != row["website"] or
            fact_row.get("email") != row["email"] or
            fact_row.get("branch") != row["branche_meervoud"] or
            not fresh_evidence(fact_row.get("checked_at", "")) or
            not _host(fact_row.get("email_source_url", "")) ==
            _host(row["website"])):
        return None
    try:
        facts = json.loads(fact_row["facts_json"])
    except (ValueError, TypeError):
        return None
    if not isinstance(facts, list):
        return None
    for item in facts[:2]:
        if not isinstance(item, dict):
            continue
        term = str(item.get("term", "")).strip().lower()
        excerpt = str(item.get("excerpt", ""))
        page = str(item.get("source_url", ""))
        if (not _host(page) == _host(row["website"]) or
                not re.search(r"\b" + re.escape(term) + r"\b", excerpt, re.I)):
            continue
        # No uncertain negated statements in the opening, even if a more
        # sophisticated upstream matcher accepted a later occurrence.
        if re.search(r"\b(geen|niet|no|not)\b", excerpt, re.I):
            continue
        result = _compose(row, item)
        if result:
            return result
    return None


def _state_id(conn):
    base = "https://sheets.googleapis.com/v4/spreadsheets/" + DRAFT_QUEUE_ID
    r = conn.get(base + "?fields=sheets(properties(sheetId,title))", timeout=30)
    if r.status_code != 200:
        raise RuntimeError("autodraft_state_metadata_unavailable")
    sheets = {p["properties"]["title"]: p["properties"]["sheetId"]
              for p in r.json().get("sheets", [])}
    if DRAFT_QUEUE_TAB not in sheets:
        raise RuntimeError("autodraft_draft_queue_tab_missing")
    if AUTO_TAB not in sheets:
        # An empty tab is recoverable. Never touch the existing seven columns.
        resp = conn.post(base + ":batchUpdate", timeout=30, json={
            "requests": [{"addSheet": {"properties": {"title": AUTO_TAB,
              "gridProperties": {"rowCount": 10000, "columnCount": 5,
                                 "frozenRowCount": 1}}}}]})
        if resp.status_code != 200:
            raise RuntimeError("autodraft_state_create_failed")
        sheets[AUTO_TAB] = resp.json()["replies"][0]["addSheet"]["properties"]["sheetId"]
    return sheets[DRAFT_QUEUE_TAB], sheets[AUTO_TAB]


def _new_row(row, subject, body):
    from datetime import datetime, timezone
    record = {
        "draft_id": "draft-" + secrets.token_hex(16),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "company": row["company"], "email": row["email"],
        "source_url": row["source_url"],
        "subject": subject, "body": body,
    }
    if len(body.split()) > 110 or body.count(OPT_OUT) != 1 or \
            body.split(OPT_OUT, 1)[0].count("?") != 1 or \
            not body.endswith("Groet,\nAndrew"):
        raise RuntimeError("autodraft_copy_gate_failed")
    return validate_draft(record)


def _cells(row):
    return {"values": [{"userEnteredValue": {"stringValue": str(x)}}
                       if str(x) else {} for x in row]}


def _write_atomic(conn, queue_tab, state_tab, old_queue, old_state,
                  new_queue, new_state):
    if len(new_queue) != len(new_state):
        raise RuntimeError("autodraft_transaction_shape_invalid")
    if not new_queue:
        return
    base = "https://sheets.googleapis.com/v4/spreadsheets/" + DRAFT_QUEUE_ID
    q_rows = [[r[h] for h in DRAFT_HEADERS] for r in new_queue]
    s_rows = [[r[h] for h in STATE_HEADERS] for r in new_state]
    # Revalidate both private snapshots immediately before committing.
    if (_read(conn, DRAFT_QUEUE_ID, "DraftQueue!A:G") != old_queue or
            _read(conn, DRAFT_QUEUE_ID, AUTO_TAB + "!A:E") != old_state):
        raise RuntimeError("autodraft_source_changed_before_write")
    requests = []
    if not old_state:
        requests.append({"appendCells": {
            "sheetId": state_tab, "rows": [_cells(STATE_HEADERS)],
            "fields": "userEnteredValue"}})
    requests.extend([
        {"appendCells": {"sheetId": queue_tab,
            "rows": [_cells(r) for r in q_rows], "fields": "userEnteredValue"}},
        {"appendCells": {"sheetId": state_tab,
            "rows": [_cells(r) for r in s_rows], "fields": "userEnteredValue"}},
    ])
    resp = conn.post(base + ":batchUpdate", json={"requests": requests}, timeout=45)
    if resp.status_code != 200:
        raise RuntimeError("autodraft_private_transaction_failed")
    if (_read(conn, DRAFT_QUEUE_ID, "DraftQueue!A:G") != old_queue + q_rows or
            _read(conn, DRAFT_QUEUE_ID, AUTO_TAB + "!A:E") !=
            (old_state or [STATE_HEADERS]) + s_rows):
        raise RuntimeError("autodraft_exact_readback_failed")


def scheduled_draft_run(run_id, *, conn=None, mailbox=create_batch_from_queue,
                        suppressions=load_suppressions):
    if not RUN_ID.fullmatch(str(run_id)):
        raise ValueError("autodraft_run_id_invalid")
    conn = conn if conn is not None else authorized_writer()
    approved, evidence, baseline = _load_latest(conn, run_id)
    if not approved:
        return {"status": "no_new_current_run", "prepared": 0,
                "stored": 0, "sent": 0}
    q_tab, s_tab = _state_id(conn)
    queue_raw = _read(conn, DRAFT_QUEUE_ID, "DraftQueue!A:G")
    state_raw = _read(conn, DRAFT_QUEUE_ID, AUTO_TAB + "!A:E")
    queue_rows = _parse_table(queue_raw, DRAFT_HEADERS)
    state_rows = _parse_table(state_raw, STATE_HEADERS, allow_empty=True)
    previous = [r for r in state_rows if r["auto_run_id"] == run_id]
    ids = [r["draft_id"] for r in previous]
    if len(set(ids)) != len(ids) or any(not DRAFT_RE.fullmatch(i) for i in ids):
        raise RuntimeError("autodraft_state_duplicate_or_invalid")
    # Idempotent resume: only known auto IDs are replayed after an IMAP fault.
    if previous:
        queue_by_id = {r["draft_id"]: r for r in queue_rows}
        if len(queue_by_id) != len(queue_rows) or not set(ids).issubset(queue_by_id):
            raise RuntimeError("autodraft_queued_ids_missing")
        source_by_identity = {_identity(r): r for r in approved}
        if len(source_by_identity) != len(approved):
            raise RuntimeError("autodraft_duplicate_current_identity")
        for saved in previous:
            source = source_by_identity.get(saved["identity_sha256"])
            row = queue_by_id[saved["draft_id"]]
            if (source is None or
                saved["quality_status"] != "source_verified_human_review_required" or
                saved["source_sha256"] != evidence_digest([
                    source["company"], source["website"], source["email"],
                    source["branche_meervoud"]]) or
                row["company"] != source["company"] or
                row["email"].casefold() != source["email"].casefold() or
                row["source_url"] != source["source_url"]):
                raise RuntimeError("autodraft_resume_provenance_mismatch")
        mailbox_result = mailbox(ids) if ids else {}
        return {"status": "resumed", "prepared": len(ids),
                "stored": mailbox_result.get("created", 0) +
                          mailbox_result.get("existing", 0), "sent": 0}
    registry = suppressions(session=conn)
    seen = {(normalize_company(r["company"]), r["email"].casefold(),
             normalize_domain(r["source_url"])) for r in queue_rows}
    prepared = []
    new_state = []
    for r in approved:
        if len(prepared) >= MAX_DRAFTS:
            break
        source = _eligible(r, evidence)
        if not source:
            continue
        identity = (normalize_company(r["company"]), r["email"].casefold(),
                    normalize_domain(r["source_url"]))
        if identity in seen or match_candidate({
            "name_hint": r["company"], "website_hint": r["website"],
            "email": r["email"]}, registry) is not None:
            continue
        # Any existing company, email or host is sufficient to suppress.
        if any(identity[0] == x[0] or identity[1] == x[1] or
               identity[2] == x[2] for x in seen):
            continue
        draft = _new_row(r, *source)
        prepared.append(draft)
        seen.add(identity)
        new_state.append(dict(auto_run_id=run_id, draft_id=draft["draft_id"],
                              identity_sha256=_identity(r),
                              source_sha256=evidence_digest([
                                  r["company"], r["website"], r["email"],
                                  r["branche_meervoud"]]),
                              quality_status="source_verified_human_review_required"))
    if not prepared:
        return {"status": "no_eligible_evidence_rich_leads",
                "prepared": 0, "stored": 0, "sent": 0}
    # Fail if another discovery/reader changed the source during preparation.
    if _read(conn, SOURCE_SHEET_ID, "Approved!A1:I101") != baseline:
        raise RuntimeError("autodraft_approved_changed_during_prepare")
    _write_atomic(conn, q_tab, s_tab, queue_raw, state_raw,
                  prepared, new_state)
    # Only the existing IMAP APPEND + exact same-folder Draft readback path.
    # Never SMTP. A later retry reuses saved IDs and cannot append duplicates.
    result = mailbox([r["draft_id"] for r in prepared])
    stored = result["created"] + result["existing"]
    return {"status": "saved_with_human_review" if stored else "skipped",
            "prepared": len(prepared), "stored": stored,
            "skipped": len(prepared) - stored, "sent": 0}


def private_preflight(*, conn=None):
    """One-time authorized *metadata-only* live probe; never connects to IMAP.

    It creates or reads only the private AutoDraftState header. No queued
    prospect row, no historical Review450 mutation, no mailbox or send.
    """
    conn = conn if conn is not None else authorized_writer()
    _parse_table(_read(conn, SOURCE_SHEET_ID, "Approved!A1:I101"), APPROVED_HEADERS)
    _parse_table(_read(conn, DRAFT_QUEUE_ID, "DraftQueue!A:G"), DRAFT_HEADERS)
    _, tab = _state_id(conn)
    rows = _read(conn, DRAFT_QUEUE_ID, AUTO_TAB + "!A:E")
    if not rows:
        base = "https://sheets.googleapis.com/v4/spreadsheets/" + DRAFT_QUEUE_ID
        header = {"updateCells": {
            "range": {"sheetId": tab, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": len(STATE_HEADERS)},
            "rows": [_cells(STATE_HEADERS)],
            "fields": "userEnteredValue"}}
        resp = conn.post(base + ":batchUpdate", timeout=30,
                         json={"requests": [header]})
        if resp.status_code != 200:
            raise RuntimeError("autodraft_preflight_header_write_failed")
        rows = _read(conn, DRAFT_QUEUE_ID, AUTO_TAB + "!A:E")
    _parse_table(rows, STATE_HEADERS)
    return {"status": "private_state_ready",
            "review450_rows_touched": 0, "mailbox_writes": 0, "sent": 0}


def main():
    try:
        import sys
        if sys.argv[1:] == ["--preflight"]:
            result = private_preflight()
        elif not sys.argv[1:]:
            result = scheduled_draft_run(os.getenv("GITHUB_RUN_ID", ""))
        else:
            raise ValueError("autodraft_unknown_argument")
        # GitHub only sees aggregate counters; zero customer identifiers/copy.
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0
    except Exception as exc:
        # Only closed internal diagnostic codes, never raw API messages,
        # company/email/subject or untrusted exception strings in GitHub.
        allowed = frozenset({
            "autodraft_private_source_read_failed",
            "autodraft_private_source_shape_invalid",
            "autodraft_missing_private_headers",
            "autodraft_private_headers_changed",
            "autodraft_private_row_invalid",
            "autodraft_state_metadata_unavailable",
            "autodraft_state_create_failed",
            "autodraft_preflight_header_write_failed",
            "autodraft_draft_queue_tab_missing",
            "autodraft_private_transaction_failed",
            "autodraft_exact_readback_failed",
        })
        detail = str(exc)
        code = detail if detail in allowed else "unclassified_failure"
        print(json.dumps({"status": "blocked", "reason": code, "sent": 0},
                         sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
