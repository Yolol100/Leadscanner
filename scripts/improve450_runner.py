"""One authorized 100-record editorial improvement phase; final phase is 50.

Reads source and previous verified independent QA, writes *proposals only* to
private Sheets. Never imports an IMAP module. Staged rows may be blocked and
must NOT be treated as approved replacement content.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
import sys

import review450 as b
import improve450_copy as copy

SOURCE_DIGEST = "6494eda72436a045bb6c9a83302d4c1431f011bbec832c95afbc5f09c4cb2832"
NEW_TAB = "Verbeter450Concepten"
NEW_ID = 683105016
STATUS_TAB = "Verbeter450Fases"
STATUS_ID = 683105017
TASK = "review450-20261015"
HEADERS = ["Nr","Draft-ID","Bedrijf","E-mailadres","Officiële bron","Website","Branche",
           "Huidig onderwerp","Verbeterd onderwerp","Verbeterde mailtekst",
           "Geverifieerd bedrijfskenmerk","Vindplaats kenmerk","Bronstatus",
           "Redactionele score /10","Verbeterpunt of blokkade","Controleer op"]
SUMMARY_HEADERS = ["Batch","Rijen","Status","Gecontroleerd","Bron bevestigd",
                   "Bron onzeker","Nieuwe versies","Reeds sterke mails behouden",
                   "Gemiddelde indicatieve score","Oorspronkelijke hash","Run-ID","Controle op"]


def _rowvalues(conn, tab, a1):
    return b.read(conn,b.SID,tab+"!"+a1)


def source_guard(conn):
    orig = b.load_rows(conn)
    state = dict(_rowvalues(conn,"Review450State","A2:B11"))
    mailbox = dict(_rowvalues(conn,"Mailbox450Control","A2:B20"))
    if (len(orig)!=450 or state.get("task")!=TASK or state.get("status")!="ready_for_review" or
            state.get("content_sha256")!=SOURCE_DIGEST or
            b.digest([b.COLS]+[[x[k] for k in b.COLS] for x in orig])!=SOURCE_DIGEST):
        raise RuntimeError("source_digest_mismatch")
    if (mailbox.get("phase")!="completed" or mailbox.get("stored")!="450" or
            mailbox.get("deleted")!="546" or mailbox.get("sent")!="0" or
            mailbox.get("approved_content_sha256")!=SOURCE_DIGEST):
        raise RuntimeError("mailbox_original_install_not_verified")
    audits = _rowvalues(conn,"QA450PerMail","A1:P451")
    if len(audits)!=451 or audits[0][0:4]!=["Nr","Draft-ID","Bedrijf","Branche"]:
        raise RuntimeError("audit_not_complete")
    for i,(r,raw) in enumerate(zip(orig,audits[1:]),start=1):
        if len(raw)!=16 or raw[0]!=str(i) or raw[1]!=r["draft_id"] or raw[2]!=r["company"]:
            raise RuntimeError("audit_identity_mismatch")
    if _rowvalues(conn,NEW_TAB,"A1:P1")!=[HEADERS]:
        raise RuntimeError("improvement_sheet_headers_wrong")
    if _rowvalues(conn,STATUS_TAB,"A1:L1")!=[SUMMARY_HEADERS]:
        raise RuntimeError("improvement_state_headers_wrong")
    return orig,audits[1:]


def limits(batch):
    if batch not in range(1,6):
        raise RuntimeError("batch_index_invalid")
    start = 100*(batch-1)
    end = min(100*batch,450)
    return start,end


def run(conn,batch):
    original, prior=source_guard(conn)
    start,end=limits(batch)
    # Existing review rows are immutable. Phase n depends on verified phase n-1.
    states=_rowvalues(conn,STATUS_TAB,"A2:L6")
    for i in range(1,batch):
        if len(states)<i or states[i-1][0]!=str(i)+"/5" or not states[i-1][2].startswith("OPGESLAGEN"):
            raise RuntimeError("previous_batch_not_completed")
    if len(states)>=batch and states[batch-1]:
        raise RuntimeError("batch_already_processed")
    if _rowvalues(conn,NEW_TAB,"A"+str(start+2)+":P"+str(end+1)):
        raise RuntimeError("proposals_already_exist")

    with ThreadPoolExecutor(max_workers=5) as pool:
        revised=list(pool.map(lambda pair:copy.evaluate(pair[0]+1,pair[1],prior[pair[0]]),
                              [(i,original[i]) for i in range(start,end)]))
    if len(revised)!=end-start:
        raise RuntimeError("batch_count_invalid")
    for n,row in enumerate(revised,start+1):
        if row[0]!=str(n) or row[1]!=original[n-1]["draft_id"] or len(row)!=16:
            raise RuntimeError("revision_identity_mismatch")
    confirmed=sum(r[12].startswith("BRON_EN_ADRES_BEVESTIGD") or
                  r[12]=="BESTAANDE_STERKE_TEKST_BEHOUDEN" for r in revised)
    blocked=sum(r[12]=="BRON_OF_ADRES_NIET_BEVESTIGD" for r in revised)
    edited=sum("VOORSTEL_" in r[12] for r in revised)
    preserved=sum(r[12]=="BESTAANDE_STERKE_TEKST_BEHOUDEN" for r in revised)
    ready=sum(bool(r[9]) for r in revised)
    missing=len(revised)-ready
    mean=(sum(float(r[13]) for r in revised if r[9])/(ready or 1))
    if mean>10 or confirmed+blocked!=len(revised):
        raise RuntimeError("improvement_quality_counts_invalid")
    summary=[
        str(batch)+"/5",str(start+1)+"-"+str(end),
        "OPGESLAGEN_MET_"+str(missing)+"_OPEN_CONTROLEPUNTEN",
        str(len(revised)),str(confirmed),str(blocked),str(edited),str(preserved),
        "%.2f"%mean,SOURCE_DIGEST,os.getenv("GITHUB_RUN_ID",""),
        str(missing)+" mails nog niet klaar; gecontroleerd op "+b.now()
    ]
    # Before *private* updates source must still be the exact approved version.
    if original!=b.load_rows(conn) or prior!=_rowvalues(conn,"QA450PerMail","A2:P451"):
        raise RuntimeError("source_changed_during_copy_revision")
    source_guard(conn)
    def values(r):
        return {"values":[{"userEnteredValue":{"stringValue":str(v)}} for v in r]}
    req=[
        {"updateCells":{"range":{
            "sheetId":NEW_ID,"startRowIndex":start+1,"endRowIndex":end+1,
            "startColumnIndex":0,"endColumnIndex":16,
        },"rows":[values(r) for r in revised],"fields":"userEnteredValue"}},
        {"updateCells":{"range":{
            "sheetId":STATUS_ID,"startRowIndex":batch,"endRowIndex":batch+1,
            "startColumnIndex":0,"endColumnIndex":12,
        },"rows":[values(summary)],"fields":"userEnteredValue"}},
    ]
    b.post(conn,req)
    if (_rowvalues(conn,NEW_TAB,"A"+str(start+2)+":P"+str(end+1))!=revised or
            _rowvalues(conn,STATUS_TAB,"A"+str(batch+1)+":L"+str(batch+1))!=[summary]):
        raise RuntimeError("private_improvement_readback_failed")
    return {"batch":batch,"checked":len(revised),"verified":confirmed,"needs_source":blocked,
            "pending":missing,"ready":ready,
            "proposed":edited,"preserved":preserved,"mean":round(mean,2)}


SAFE=frozenset({
"source_digest_mismatch","mailbox_original_install_not_verified","audit_not_complete",
"audit_identity_mismatch","improvement_sheet_headers_wrong","improvement_state_headers_wrong",
"previous_batch_not_completed","batch_already_processed","proposals_already_exist",
"batch_count_invalid","revision_identity_mismatch","source_changed_during_copy_revision",
"private_improvement_readback_failed","batch_index_invalid",
"improvement_quality_counts_invalid"
})


def main():
    if os.getenv("IMPROVE450_TASK")!=TASK:
        print("IMPROVE450=blocked unauthorized_task sent=0 mailbox_writes=0")
        return 1
    try:
        batch=int(os.getenv("IMPROVE450_BATCH","0"))
        with redirect_stdout(StringIO()),redirect_stderr(StringIO()):
            from private_candidate_handoff import authorized_writer
            result=run(authorized_writer(),batch)
        print("IMPROVE450=partial batch={batch} checked={checked} verified={verified} "
              "needs_source={needs_source} ready={ready} pending={pending} proposed={proposed} preserved={preserved} "
              "indicative_mean={mean:.2f} sent=0 mailbox_writes=0".format(**result))
        return 0
    except Exception as exc:
        name=str(exc) if str(exc) in SAFE else "source_or_private_write_failed"
        print("IMPROVE450=blocked reason="+name+" sent=0 mailbox_writes=0")
        return 1


if __name__=="__main__":
    sys.exit(main())
