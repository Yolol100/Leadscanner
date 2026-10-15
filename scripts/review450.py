"""Task-scoped private review batch. No sending; no scheduled execution.

Prepare first. Replacing existing Drafts is a separate, verified operation.
Only counters leave the private Sheets boundary.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import secrets
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from io import StringIO
from urllib.parse import quote

TARGET = 450
TASK = "review450-20261015"
SID = "13dLUKiX3mWjPWly_UPJFYolOcLc2JBD7Cxv2QBHXRGM"
QID = "1AOsEsxkG2He6SOlD92BZpmY2DAj3716Fp953oqgy1jk"
TAB = "Review450"
TAB_ID = 683104994
STATE = "Review450State"
STATE_ID = 683104995
HISTORY_ID = 683104992
COLS = ["draft_id", "created_at", "company", "email", "source_url", "subject", "body",
        "website", "cluster", "branch", "evidence_url", "evidence", "origin", "qa_status", "run_id", "task"]
OPT = "Liever geen e-mails meer? Antwoord met 'nee', dan laat ik het hierbij."
FORBIDDEN = "Ik ben Andrew van Webactueel"
REGIONS = ("Rotterdam", "Den Haag", "Utrecht", "Amsterdam", "Eindhoven", "Tilburg",
           "Breda", "Nijmegen", "Arnhem", "Apeldoorn", "Enschede", "Zwolle", "Almere",
           "Amersfoort", "Haarlem", "Alkmaar", "Leiden", "Dordrecht", "Gouda", "Delft",
           "Groningen", "Leeuwarden", "Assen", "Emmen", "Deventer", "Hengelo", "Almelo",
           "Roosendaal", "Bergen op Zoom", "Middelburg", "Goes", "Terneuzen", "Maastricht",
           "Venlo", "Roermond", "Heerlen", "Weert", "Helmond", "Oss", "Waalwijk", "Uden",
           "Hilversum", "Hoorn", "Purmerend", "Den Helder", "Lelystad", "Harderwijk",
           "Doetinchem", "Zutphen", "Tiel", "Veenendaal", "Ede", "Wageningen", "Zeist",
           "Nieuwegein", "Woerden", "Gorinchem", "Heerenveen", "Drachten", "Sneek")
DETAILS = {
 "hoveniers": [("tuinontwerp", "tuinontwerp"), ("tuinonderhoud", "tuinonderhoud"), ("bestrating", "bestrating"), ("tuinaanleg", "tuinaanleg")],
 "schilders": [("houtrotherstel", "houtrotherstel"), ("restauratie", "restauratiewerk"), ("kleuradvies", "kleuradvies"), ("buitenschilderwerk", "buitenschilderwerk")],
 "kappers": [("bruidskapsel", "bruidskapsels"), ("balayage", "balayage"), ("highlights", "highlights"), ("barbier", "barbiersbehandelingen"), ("kleuren", "kleurbehandelingen")],
 "schoonheidssalons": [("pedicure", "pedicurebehandelingen"), ("gezichtsbehandeling", "gezichtsbehandelingen"), ("nagel", "nagelverzorging")],
 "garages": [("camperonderhoud", "camperonderhoud"), ("apk", "APK"), ("onderhoud", "auto-onderhoud")],
 "bloemisten": [("bruids", "bruidsbloemen"), ("rouw", "rouwboeketten"), ("boeket", "boeketten")],
 "fietsenwinkels": [("tweedehands", "tweedehands fietsen"), ("proefrit", "proefritten"), ("elektrisch", "elektrische fietsen")],
 "stukadoors": [("cinewall", "cinewalls"), ("spuitwerk", "spuitwerk"), ("buitenstuc", "buitenstucwerk")],
 "fysiotherapiepraktijken": [("sportfysiotherapie", "sportfysiotherapie"), ("handtherapie", "handtherapie"), ("manuele therapie", "manuele therapie")],
 "glazenwassers": [("gevelreiniging", "gevelreiniging"), ("glasbewassing", "glasbewassing")],
 "restaurants": [("lunch", "lunch"), ("diner", "diner"), ("afhalen", "afhalen")],
}
FALLBACK = {"schilders":"schilderwerk", "hoveniers":"tuinwerk", "loodgieters":"loodgieterswerk",
 "elektriciens":"elektrawerk", "timmerbedrijven":"timmerwerk", "dakdekkers":"dakwerk",
 "stukadoors":"stucwerk", "tegelzetters":"tegelwerk", "aannemers":"bouwwerkzaamheden",
 "glazenwassers":"glasbewassing", "schoonmaakbedrijven":"schoonmaak", "boomverzorgers":"boomverzorging",
 "kappers":"haarverzorging", "schoonheidssalons":"verzorgingsbehandelingen", "rijscholen":"rijlessen",
 "sportscholen":"fitness", "bloemisten":"bloemen", "restaurants":"jullie restaurant",
 "horecazaken":"jullie horecazaak", "bakkerijen":"jullie bakkerij", "slagerijen":"jullie slagerij",
 "logiesbedrijven":"overnachtingen", "fietsenwinkels":"fietsen", "garages":"autoreparaties",
 "pechhulpbedrijven":"pechhulp", "dierenartsen":"jullie dierenartspraktijk",
 "fysiotherapiepraktijken":"fysiotherapie", "dierenoppassers":"dierenoppas", "uitvaartbedrijven":"uitvaartzorg",
 "reparatiebedrijven":"reparaties", "wasserijen":"reiniging van kleding"}
OFFER = {
 1: "Ik help vakbedrijven hun werkzaamheden online duidelijk te presenteren, met een logische stap naar de bestaande aanvraag of het contact.",
 2: "Ik help lokale dienstverleners hun behandelingen of lessen mobiel duidelijk uit te leggen, met een logische stap naar de bestaande afspraakroute.",
 3: "Ik help lokale ondernemers om hun aanbod mobiel duidelijk te presenteren en bezoekers gericht naar de bestaande contact- of bestelroute te leiden.",
 4: "Ik help servicebedrijven om bezoekers mobiel de juiste dienst te laten kiezen en vooraf de relevante gegevens door te geven. Direct bellen blijft mogelijk.",
 5: "Ik help lokale praktijken en dienstverleners om hun informatie rustig en overzichtelijk te tonen, met een duidelijke stap naar persoonlijk contact.",
 6: "Ik help reparatie- en servicebedrijven om hun werkzaamheden mobiel duidelijk uit te leggen en gerichte vragen via de bestaande contactroute te ontvangen.",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def cells(rows):
    return [{"values": [{"userEnteredValue": {"stringValue": str(v)}} if str(v) else {} for v in row]} for row in rows]


def read(conn, sid, a1):
    r = conn.get("https://sheets.googleapis.com/v4/spreadsheets/" + sid + "/values/" + quote(a1, safe=""), timeout=30)
    if r.status_code != 200:
        raise RuntimeError("private_sheet_read_failed")
    values = r.json().get("values", [])
    if not isinstance(values, list):
        raise RuntimeError("private_sheet_shape_invalid")
    return values


def post(conn, requests):
    r = conn.post("https://sheets.googleapis.com/v4/spreadsheets/" + SID + ":batchUpdate", json={"requests": requests}, timeout=45)
    if r.status_code != 200:
        raise RuntimeError("private_sheet_write_failed")


def table_request(gid, rows, width):
    if any(len(row) != width for row in rows):
        raise RuntimeError("private_row_width_invalid")
    return {"updateCells": {"range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": len(rows),
                                      "startColumnIndex": 0, "endColumnIndex": width},
                            "rows": cells(rows), "fields": "userEnteredValue"}}


def load_rows(conn):
    values = read(conn, SID, TAB + "!A1:P451")
    if not values or values[0] != COLS:
        raise RuntimeError("private_batch_headers_invalid")
    out = []
    for raw in values[1:]:
        if len(raw) != len(COLS):
            raise RuntimeError("private_batch_row_invalid")
        row = dict(zip(COLS, raw))
        validate(row)
        out.append(row)
    if len(out) > TARGET:
        raise RuntimeError("too_many_batch_rows")
    unique(out)
    return out


def unique(rows):
    from dedupe_preflight import candidate_identity, domains_match
    seen = []
    ids = set()
    for row in rows:
        ident = candidate_identity(row)
        if row["draft_id"] in ids:
            raise RuntimeError("duplicate_draft_id")
        ids.add(row["draft_id"])
        for other in seen:
            if (ident["company"] == other["company"] or ident["emails"] & other["emails"] or
                    any(domains_match(a, b) for a in ident["domains"] for b in other["domains"])):
                raise RuntimeError("duplicate_business")
        seen.append(ident)


def validate(row):
    from new_leads import safe_hint
    from draft_queue_readonly import valid_general_email
    if (not re.fullmatch(r"draft-[a-f0-9]{32}", row.get("draft_id", "")) or row.get("task") != TASK or
            row.get("qa_status") != "verified_website_email_copy" or
            row.get("cluster") not in {"1", "2", "3", "4", "5", "6"} or
            not row.get("company") or len(row["company"]) > 150 or
            any(c in row["company"] for c in "\r\n\x00") or
            not valid_general_email(row.get("email", "")) or
            not safe_hint(row.get("source_url")) or not safe_hint(row.get("website")) or
            not safe_hint(row.get("evidence_url")) or not row.get("evidence")):
        raise RuntimeError("review_row_invalid")
    body = row.get("body", "")
    if (FORBIDDEN.casefold() in body.casefold() or not 30 <= len(body.split()) <= 110 or
            body.count("?") != 2 or body.count(OPT) != 1 or not body.endswith("Groet,\nAndrew") or
            not body.startswith(("Goedendag,\n", "Hoi,\n", "Hoi ")) or
            any(x in body + row.get("subject", "") for x in ("{{", "}}", "\x00")) or
            not 5 <= len(row.get("subject", "")) <= 160 or any(c in row["subject"] for c in "\r\n")):
        raise RuntimeError("review_copy_invalid")


def make_copy(item, pages, origin):
    from verify_official_lead import norm, BRANCH_PROOF
    branch = item["branche_meervoud"]
    cluster = int(item["cluster"])
    source, evidence, label = None, None, None
    for needle, text in DETAILS.get(branch, []):
        match = next((p for p in pages if norm(needle) in norm(p[1])), None)
        if match:
            source, evidence, label = match[0], needle, text
            break
    if label is None:
        for page in pages:
            word = next((w for w in BRANCH_PROOF[branch] if w in norm(page[1])), None)
            if word:
                source, evidence, label = page[0], word, FALLBACK[branch]
                break
    if not label:
        raise RuntimeError("copy_without_source_evidence")
    name = item["company"]
    if "?" in name:
        raise RuntimeError("ambiguous_business_name")
    hook = "Op de website van " + name + " las ik over " + label + "."
    offer = OFFER[cluster]
    cta = "Zal ik een kort voorbeeld sturen dat aansluit op " + label + "?"
    body = "\n\n".join((item["greeting"], hook, offer, cta, OPT, "Groet,\nAndrew"))
    row = dict(draft_id="draft-" + secrets.token_hex(16), created_at=now(), company=name,
               email=item["email"], source_url=item["source_url"],
               subject=label[:1].upper() + label[1:] + " bij " + name,
               body=body, website=item["website"], cluster=str(cluster), branch=branch,
               evidence_url=source, evidence="Officiele pagina vermeldt: " + evidence,
               origin=origin, qa_status="verified_website_email_copy",
               run_id=os.environ.get("GITHUB_RUN_ID", ""), task=TASK)
    validate(row)
    return row


class Capture:
    """Record only HTML already read by the existing bounded verifier."""
    def __init__(self):
        import requests
        self.conn = requests.Session()
        self.pages = []

    def get(self, url, **kw):
        response = self.conn.get(url, **kw)
        if kw.get("stream") and response.status_code == 200:
            parent = self
            original = response.iter_content
            def stream(*args, **kwargs):
                chunks = []
                size = 0
                for chunk in original(*args, **kwargs):
                    size += len(chunk)
                    if size <= 350000:
                        chunks.append(chunk)
                    yield chunk
                if size <= 350000 and "text/html" in response.headers.get("Content-Type", "").lower():
                    from verify_official_lead import PublicHTML
                    parsed = PublicHTML()
                    parsed.feed(b"".join(chunks).decode("utf-8", errors="replace"))
                    parent.pages.append((url, " ".join(parsed.texts)))
            response.iter_content = stream
        return response

    def close(self):
        self.conn.close()


def inspect(hint, origin, expected_email=None):
    from verify_official_lead import verify_official_site
    cap = Capture()
    try:
        item = verify_official_site(hint, session=cap)
        if not item or (expected_email and item["email"].casefold() != expected_email.casefold()):
            return None
        return make_copy(item, cap.pages, origin)
    except Exception:
        return None
    finally:
        cap.close()


def state(conn, rows, phase, checked=0, regions=0):
    from dedupe_preflight import candidate_identity, match_candidate
    hist = read(conn, SID, "LeadHistory!A:H")
    header = ["first_seen_run", "company", "website", "email", "source_url", "status", "draft_id", "recorded_at"]
    if not hist or hist[0] != header:
        raise RuntimeError("lead_history_unavailable")
    known = []
    for r in hist[1:]:
        if len(r) < 6 or not all(r[i] for i in (1, 2, 3, 4, 5)):
            raise RuntimeError("lead_history_incomplete")
        known.append({"identity": candidate_identity({"company": r[1], "website": r[2], "email": r[3]}),
                      "status": r[5], "row_number": len(known)+2})
    additions = []
    for r in rows:
        if not match_candidate(r, known):
            additions.append([r["run_id"], r["company"], r["website"], r["email"], r["source_url"],
                              "verified_lead", "", r["created_at"]])
            known.append({"identity": candidate_identity(r), "status": "verified_lead", "row_number": 0})
    vals = [COLS] + [[r[k] for k in COLS] for r in rows]
    info = [["key", "value"], ["task", TASK], ["status", phase], ["target", str(TARGET)],
            ["prepared", str(len(rows))], ["sites_checked", str(checked)], ["regions", str(regions)],
            ["run_id", os.environ.get("GITHUB_RUN_ID", "")], ["updated_at", now()],
            ["content_sha256", digest(vals)], ["sent", "0"]]
    requests = [table_request(TAB_ID, vals, len(COLS)), table_request(STATE_ID, info, 2)]
    if additions:
        requests.append({"appendCells": {"sheetId": HISTORY_ID, "rows": cells(additions), "fields": "userEnteredValue"}})
    post(conn, requests)
    if read(conn, SID, TAB + "!A1:P451") != vals or read(conn, SID, STATE + "!A1:B11") != info:
        raise RuntimeError("batch_readback_failed")
    if additions and read(conn, SID, "LeadHistory!A:H") != hist + additions:
        raise RuntimeError("history_readback_failed")


def prepare():
    from private_candidate_handoff import authorized_writer
    from registry_readonly import load_suppressions, load_discovery_suppressions
    from dedupe_preflight import candidate_identity, match_candidate, normalize_domain
    from verify_official_lead import CATEGORIES, category
    from overture_discovery import discover
    conn = authorized_writer()
    historical = load_suppressions(session=conn)
    discovery_registry = load_discovery_suppressions(session=conn)
    rows = load_rows(conn)
    if len(rows) == TARGET:
        state(conn, rows, "ready_for_review")
        return len(rows)
    seen = {normalize_domain(r["website"]) for r in rows}
    kept = [{"identity": candidate_identity(r), "status": "this_batch", "row_number": i+1} for i,r in enumerate(rows)]
    reverse = {}
    for cat, (_, branch) in CATEGORIES.items():
        reverse.setdefault(branch, cat)
    aliases = {"autobedrijven":"garages"}
    seeds = []
    review = read(conn, QID, "'Laatste redactieronde - v3'!A1:O51")
    if len(review) != 51:
        raise RuntimeError("original_fifty_not_available")
    for r in review[1:]:
        if len(r) != 15 or "BLOKKADE" in r[13]:
            continue
        branch = aliases.get(r[2].split(" / ")[-1], r[2].split(" / ")[-1])
        if branch in reverse:
            seeds.append(({"name_hint": r[1], "website_hint": r[14], "category_hint": reverse[branch]}, "review50", r[4]))
    approved = read(conn, SID, "Approved!A1:I101")
    if not approved or approved[0] != ["run_id","company","website","email","source_url","cluster","branche_meervoud","greeting","status"]:
        raise RuntimeError("approved_headers_invalid")
    for r in approved[1:]:
        if len(r) == 9 and r[8] == "verified_website_and_email" and r[6] in reverse:
            seeds.append(({"name_hint":r[1],"website_hint":r[2],"category_hint":reverse[r[6]]}, "approved", r[3]))
    checked = 0
    started = time.monotonic()
    last_saved = len(rows)
    def take(candidate):
        if candidate and not match_candidate(candidate, historical) and not match_candidate(candidate, kept):
            rows.append(candidate)
            kept.append({"identity":candidate_identity(candidate),"status":"this_batch","row_number":len(rows)})
    with ThreadPoolExecutor(max_workers=6) as pool:
        todo = []
        for hint, origin, email in seeds:
            host = normalize_domain(hint["website_hint"])
            if host in seen or match_candidate({**hint,"email":email}, historical):
                continue
            seen.add(host)
            todo.append((hint, origin, email))
        for candidate in pool.map(lambda args: inspect(*args), todo):
            checked += 1
            take(candidate)
        state(conn, rows, "collecting", checked, 0)
        last_saved = len(rows)
        for region_index, region in enumerate(REGIONS, 1):
            if len(rows) >= TARGET or checked >= 10000 or time.monotonic() - started > 5100:
                break
            try:
                result = discover(region=region, bbox=None, radius_km=25, keywords=["vakbedrijven"],
                                  max_results=700, require_website=True, probe_websites=False)
            except Exception:
                continue
            if not isinstance(result, dict) or not isinstance(result.get("candidates"), list):
                raise RuntimeError("source_shape_invalid")
            todo = []
            for hint in result["candidates"]:
                if not isinstance(hint, dict) or not category(hint):
                    continue
                host = normalize_domain(hint.get("website_hint"))
                if not host or host in seen or match_candidate(hint, discovery_registry) or match_candidate(hint, kept):
                    continue
                seen.add(host)
                todo.append(hint)
            for start in range(0, len(todo), 24):
                if len(rows) >= TARGET or checked >= 10000 or time.monotonic() - started > 5100:
                    break
                block = todo[start:start + min(24, 2*(TARGET-len(rows)))]
                results = list(pool.map(lambda h: inspect(h,"discovery"), block))
                checked += len(block)
                for candidate in results:
                    if len(rows) < TARGET:
                        take(candidate)
                if len(rows) - last_saved >= 20:
                    state(conn, rows, "collecting", checked, region_index)
                    last_saved = len(rows)
            state(conn, rows, "collecting", checked, region_index)
            last_saved = len(rows)
    unique(rows)
    state(conn, rows, "ready_for_review" if len(rows)==TARGET else "partial", checked, region_index if 'region_index' in locals() else 0)
    return len(rows)


def main():
    if os.environ.get("REVIEW450_PHASE") != "prepare":
        print("REVIEW450=blocked phase_not_authorized sent=0")
        return 1
    try:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            count = prepare()
        print("REVIEW450={} prepared={} target=450 mailbox_writes=0 sent=0".format("ready" if count==TARGET else "partial", count))
        return 0 if count==TARGET else 2
    except Exception:
        print("REVIEW450=blocked private_source_or_registry_or_readback sent=0 mailbox_writes=0")
        return 1


if __name__ == "__main__":
    sys.exit(main())
