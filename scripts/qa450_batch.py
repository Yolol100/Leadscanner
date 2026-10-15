"""Read-only editorial/source QA of one user's private 450-draft batch.

Check 100 drafts per run (last batch 50). Each candidate is independently
rechecked against a bounded official homepage/contact page with the Leads
website verifier. Results and commentary go only into the user's private
Google Sheet; GitHub logs contain aggregate numbers, never recipient data.
This module NEVER logs in to IMAP, changes a draft, sends, or deletes email.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import os
import re
import sys

import review450 as b

ROWS_TAB = "QA450PerMail"
ROWS_ID = 683105014
STATE_TAB = "QA450Batches"
STATE_ID = 683105015
EXPECTED_SOURCE_SHA = "6494eda72436a045bb6c9a83302d4c1431f011bbec832c95afbc5f09c4cb2832"
TASK = "review450-20261015"
MAX_WORKERS = 6
HEADERS = [
    "Nr", "Draft-ID", "Bedrijf", "Branche", "Score /10",
    "Redactionele score-uitleg", "Officiële site live",
    "E-mailadres opnieuw bevestigd", "Dienst/feit controle",
    "Opening", "Aanbod passend", "Onderwerp", "Verbeteradvies",
    "Beoordeling", "Officiële bron", "Gecontroleerd op",
]
BATCH_HEADERS = [
    "Batch", "Rijen", "Status", "Gecontroleerd", "Officiële verificatie",
    "Bron niet bevestigd", "Herschrijven nodig", "Gem. score",
    "Bronversie SHA256", "Uitvoering", "Laatst gecontroleerd", "Volgende actie",
]


def now():
    return datetime.now(timezone.utc).isoformat()


def ranges_for_batch(index):
    if not isinstance(index, int) or not 1 <= index <= 5:
        raise RuntimeError("batch_index_invalid")
    start = (index - 1) * 100
    end = min(index * 100, 450)
    return start, end


def opening_kind(body):
    pieces = body.split("\n\n")
    start = pieces[1].strip() if len(pieces) > 1 else ""
    if start.startswith("Ik kwam de website van "):
        return "algemene_opening"
    if start.startswith("Op de website van ") and (
            "zag ik informatie over " in start or "las ik over " in start):
        return "dienstterm_zonder_unieke_observatie"
    return "specifieke_bedrijfsobservatie"


def offer_status(row):
    """The generic cluster promise can be topical without being truly specific."""
    text = row["body"].casefold()
    branch = row["branch"].casefold()
    expected = {
        "restaurants": ("restaurants",),
        "horecazaken": ("horecazaken",),
        "logiesbedrijven": ("logiesbedrijven",),
        "sportscholen": ("sportscholen",),
        "kappers": ("salons", "kapsalons", "kappers"),
        "hoveniers": ("hoveniers",),
        "fysiotherapiepraktijken": ("praktijken",),
        "reparatiebedrijven": ("reparatiebedrijven", "tweewieler"),
        "schilders": ("schilders", "vakbedrijven", "specialisten"),
        "schoonheidssalons": ("praktijken", "salons"),
        "bloemisten": ("bloemisten",),
        "fietsenwinkels": ("fietsenwinkels",),
        "stukadoors": ("stukadoors", "vakbedrijven"),
        "glazenwassers": ("dienstverleners", "glazenwassers"),
    }
    terms = expected.get(branch)
    if not terms:
        return "handmatig_beoordelen"
    return "branche_passend" if any(t in text for t in terms) else "aanbod_mogelijk_niet_passend"


def live_check(row):
    """Strict, bounded verification; no inferred addresses or third-party profiles."""
    import review450_strict as strict
    from verify_official_lead import CATEGORIES, verify_official_site
    reverse = {}
    for category, (_, branch) in CATEGORIES.items():
        reverse.setdefault(branch, category)
    category = reverse.get(row["branch"])
    if category is None:
        return "niet_bevestigd", "niet_bevestigd", "niet_bevestigd"
    hint = {
        "name_hint": row["company"],
        "website_hint": row["website"],
        "category_hint": category,
        "country_hint": "NL",
    }
    cap = b.Capture()
    try:
        item = verify_official_site(hint, session=cap)
        if not item or not cap.pages or not strict.local_proof(cap.pages, hint):
            return "niet_bevestigd", "niet_bevestigd", "niet_bevestigd"
        site_status = "bevestigd"
        email_status = ("bevestigd" if row["email"].casefold() == item["email"].casefold()
                        else "ander_adres_op_site")
        original_term = re.search(r"Letterlijke dienstterm: ([^;]+);", row["evidence"])
        if not original_term:
            term_status = "bewijs_onvoldoende_specifiek"
        elif any(strict.term_match(text, original_term.group(1)) for _, text in cap.pages):
            term_status = "bevestigd"
        else:
            term_status = "dienstterm_niet_hervonden"
        if item["branche_meervoud"] != row["branch"]:
            term_status = "branche_wijkt_af"
        return site_status, email_status, term_status
    except Exception:
        return "niet_bevestigd", "niet_bevestigd", "niet_bevestigd"
    finally:
        cap.close()


def review_one(nr, row, live=None, checked_at=None):
    """An editorial estimate, NOT conversion or legal permission to mail."""
    if live is None:
        live = live_check(row)
    site, email, term = live
    kind = opening_kind(row["body"])
    fit = offer_status(row)
    subject = row["subject"]
    specific = kind == "specifieke_bedrijfsobservatie"
    if specific:
        base = 8.7
        note = "Natuurlijke openingszin met bedrijfsspecifieke invalshoek"
        suggestion = "Controleer alle details van de openingszin handmatig tegen de officiële site."
    elif kind == "dienstterm_zonder_unieke_observatie":
        base = 7.1
        note = "Dienst relevant, maar alleen een standaardobservatie over de website"
        suggestion = "Gebruik een echt onderscheidend aanbod/dienst uit de officiële website, zonder probleem te verzinnen."
    else:
        base = 6.5
        note = "Opening noemt alleen de website; te algemeen voor een sterke cold email"
        suggestion = "Vervang de algemene opening door één concreet en controleerbaar bedrijfsdetail."
    if subject.startswith(("Jullie zaak bij ", "Sportaanbod bij ", "Verblijfsinformatie bij ")):
        base -= 0.3
        note += "; onderwerp kan specifieker"
    if fit != "branche_passend":
        base -= 1.0
        suggestion += " Controleer of het aanbod daadwerkelijk past bij de hoofdactiviteit."
    if site != "bevestigd":
        base = min(base, 6.0)
        suggestion += " Website of bedrijfsidentiteit kon nu niet opnieuw worden vastgesteld."
    elif email != "bevestigd":
        base = min(base, 5.0)
        suggestion += " Het gekozen zakelijke adres is niet opnieuw bevestigd; niet verzenden."
    elif term != "bevestigd":
        base = min(base, 6.5)
        suggestion += " Het relevante dienstwoord werd niet opnieuw bevestigd."
    elif specific:
        # The public service-word proof does not independently verify every
        # separate appointment, opening-hour or product-detail claim.
        base = min(base, 8.6)
    score = max(1.0, round(base, 1))
    if site != "bevestigd" or email != "bevestigd" or term != "bevestigd":
        verdict = "BRONCONTROLE_NODIG"
    elif score < 8.5:
        verdict = "HERSCHRIJVEN_AANBEVOLEN"
    else:
        verdict = "INHOUDELIJK_BIJNA_GOED_DETAILCHECK_NODIG"
    explanation = note + ". Score is een redactionele inschatting; geen bewezen effectiviteit."
    return [
        str(nr), row["draft_id"], row["company"], row["branch"], "%.1f" % score,
        explanation, site, email, term, kind, fit,
        "specifiek" if not subject.startswith(("Jullie zaak", "Sportaanbod", "Verblijfsinformatie"))
        else "algemeen",
        suggestion, verdict, row["evidence_url"], checked_at or now(),
    ]


def preflight(conn):
    src = b.load_rows(conn)
    status = dict(b.read(conn, b.SID, "Review450State!A2:B11"))
    contents = [b.COLS] + [[row[k] for k in b.COLS] for row in src]
    if (len(src) != 450 or status.get("task") != TASK or
        status.get("status") != "ready_for_review" or
        status.get("content_sha256") != EXPECTED_SOURCE_SHA or
        b.digest(contents) != EXPECTED_SOURCE_SHA):
        raise RuntimeError("source_version_changed")
    control = dict(b.read(conn, b.SID, "Mailbox450Control!A2:B25"))
    if (control.get("phase") != "completed" or control.get("stored") != "450" or
        control.get("deleted") != "546" or control.get("sent") != "0" or
        control.get("approved_content_sha256") != EXPECTED_SOURCE_SHA):
        raise RuntimeError("mailbox_readback_gate_not_confirmed")
    if b.read(conn, b.SID, ROWS_TAB + "!A1:P1") != [HEADERS]:
        raise RuntimeError("audit_sheet_headers_changed")
    if b.read(conn, b.SID, STATE_TAB + "!A1:L1") != [BATCH_HEADERS]:
        raise RuntimeError("audit_state_headers_changed")
    return src


def audit_batch(conn, index):
    src = preflight(conn)
    start, end = ranges_for_batch(index)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        checked = list(pool.map(live_check, src[start:end]))
    now_iso = now()
    rows = [review_one(i+1, src[i], status, now_iso)
            for i, status in zip(range(start, end), checked)]
    if len(rows) != end-start or any(r[1] != src[int(r[0])-1]["draft_id"] for r in rows):
        raise RuntimeError("audit_batch_identity_mismatch")
    verified = sum(1 for r in rows if r[6:9] == ["bevestigd"]*3)
    blocked = sum(1 for r in rows if r[13] == "BRONCONTROLE_NODIG")
    improve = sum(1 for r in rows if r[13] == "HERSCHRIJVEN_AANBEVOLEN")
    score = sum(float(r[4]) for r in rows) / len(rows)
    record = [
        str(index) + "/5", str(start+1) + "-" + str(end), "GECONTROLEERD_MET_OPMERKINGEN",
        str(len(rows)), str(verified), str(blocked), str(improve), "%.2f" % score,
        EXPECTED_SOURCE_SHA, os.environ.get("GITHUB_RUN_ID", ""), now_iso,
        ("batch " + str(index+1) if index < 5 else "eindcontrole"),
    ]
    # Re-check the immutable source just before touching private audit tabs.
    fresh = b.load_rows(conn)
    if fresh != src:
        raise RuntimeError("batch_changed_during_qa")
    preflight(conn)
    previous = b.read(conn,b.SID,ROWS_TAB+"!A"+str(start+2)+":P"+str(end+1))
    if previous:
        raise RuntimeError("batch_already_reviewed_refuse_overwrite")
    request_rows = [{"values": [{"userEnteredValue": {"stringValue": value}}
                                for value in record_row]} for record_row in rows]
    req = [
        {"updateCells": {"range": {
            "sheetId": ROWS_ID, "startRowIndex": start+1,
            "endRowIndex": end+1, "startColumnIndex": 0, "endColumnIndex": 16,
        }, "rows": request_rows, "fields": "userEnteredValue"}},
        {"updateCells": {"range": {
            "sheetId": STATE_ID, "startRowIndex": index,
            "endRowIndex": index+1, "startColumnIndex": 0, "endColumnIndex": 12,
        }, "rows": [{"values":[{"userEnteredValue":{"stringValue":value}}
                  for value in record]}], "fields": "userEnteredValue"}},
    ]
    b.post(conn, req)
    written = b.read(conn,b.SID,ROWS_TAB+"!A"+str(start+2)+":P"+str(end+1))
    state = b.read(conn,b.SID,STATE_TAB+"!A"+str(index+1)+":L"+str(index+1))
    if written != rows or state != [record]:
        raise RuntimeError("audit_readback_failed")
    return {"batch": index, "checked": len(rows), "site_email_service": verified,
            "needs_reverify": blocked, "rewrite_recommended": improve,
            "mean_score": round(score,2), "sent": 0, "mailbox_writes": 0}


SAFE_CODES = frozenset({
    "source_version_changed", "mailbox_readback_gate_not_confirmed",
    "audit_sheet_headers_changed", "audit_state_headers_changed",
    "audit_batch_identity_mismatch", "batch_changed_during_qa",
    "batch_already_reviewed_refuse_overwrite", "audit_readback_failed",
    "batch_index_invalid",
})


def main():
    try:
        index = int(os.environ.get("QA450_BATCH", "0"))
    except ValueError:
        index = 0
    if not 1 <= index <= 5 or os.getenv("QA450_TASK") != TASK:
        print("QA450=blocked reason=batch_not_authorized sent=0 mailbox_writes=0")
        return 1
    try:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            from private_candidate_handoff import authorized_writer
            result = audit_batch(authorized_writer(), index)
        print("QA450=green batch={batch} checked={checked} verified={site_email_service} "
              "needs_reverify={needs_reverify} rewrite={rewrite_recommended} "
              "mean_score={mean_score:.2f} sent=0 mailbox_writes=0".format(**result))
        return 0
    except Exception as exc:
        reason = str(exc) if str(exc) in SAFE_CODES else "private_qa_operation_failed"
        print("QA450=blocked reason={} sent=0 mailbox_writes=0".format(reason))
        return 1


if __name__ == "__main__":
    sys.exit(main())
