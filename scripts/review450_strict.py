"""Quality correction for the same explicit 450 task; no mailbox operations.

Country and local-business checks precede acceptance. Existing reviewed copy is
retained for a reverified seed, while new copy is based on a literal official
source term. Candidate selection is broader, not website concurrency (still six).
"""
from __future__ import annotations
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from urllib.parse import urlsplit

import review450 as b

# Conservative exclusions when no independent local decision-maker is verified.
CHAINS = ("amrath", "holiday inn", "ihg", "hilton", "hampton by hilton", "marriott", "ibis",
          "mercure", "novotel", "accor", "nh hotel", "nh collection", "van der valk", "bastion hotel",
          "fletcher", "best western", "the niu", "easyhotel", "motel one", "radisson", "park plaza",
          "leonardo hotel", "golden tulip", "campanile", "premiere classe", "b b hotels",
          "mcdonald", "burger king", "domino", "starbucks", "kfc", "subway", "taco bell",
          "new york pizza", "de beren", "basic fit", "fit for free", "anytime fitness",
          "brainwash", "team kappers", "cosmo hairstyling", "ami kappers", "qmusic", "de eendracht")
POSTCODE = re.compile(r"\b[1-9][0-9]{3}\s?[A-Z]{2}\b")
BRANCH_OFFER = {
 "kappers":"Ik help kapsalons hun behandelingen op mobiel helder uit te leggen, met een duidelijke stap naar de bestaande afspraakmogelijkheden.",
 "schoonheidssalons":"Ik help salons hun behandelingen op mobiel overzichtelijk te tonen en bezoekers gericht naar de bestaande contact- of afspraakmogelijkheid te leiden.",
 "rijscholen":"Ik help rijscholen hun lessen op mobiel helder te presenteren, met een duidelijke stap naar een vraag of proefles.",
 "sportscholen":"Ik help sportscholen om hun aanbod op mobiel duidelijk uit te leggen en bezoekers naar de bestaande contactmogelijkheden te leiden.",
 "restaurants":"Ik help restaurants hun menu en praktische informatie op mobiel overzichtelijk te tonen, met een duidelijke stap naar contact of reserveren.",
 "horecazaken":"Ik help horecazaken hun aanbod op mobiel helder te tonen, met een duidelijke stap naar de bestaande contactmogelijkheden.",
 "logiesbedrijven":"Ik help zelfstandige logiesbedrijven hun verblijf en praktische informatie op mobiel duidelijk te presenteren, met een logische stap naar de bestaande contactroute.",
 "bloemisten":"Ik help bloemisten hun verschillende gelegenheden op mobiel duidelijk te presenteren, met een passende stap naar de bestaande bestel- of contactroute.",
 "fietsenwinkels":"Ik help fietsenwinkels hun aanbod op mobiel overzichtelijk te tonen en vragen over een specifiek model naar de juiste contactroute te leiden.",
 "fysiotherapiepraktijken":"Ik help praktijken hun behandelinformatie rustig uit te leggen, met een duidelijke stap naar persoonlijk contact. Medische keuzes blijven bij de behandelaar.",
}
FALLBACK_LABELS = dict(b.FALLBACK, restaurants="het restaurant", horecazaken="het cafe",
                      bakkerijen="het broodaanbod", slagerijen="het slagersaanbod")


def chain(name, website=""):
    from verify_official_lead import norm
    text=" "+norm(name+" "+website)+" "
    return any((" "+norm(term)) in text for term in CHAINS)


def allowed_hint(hint):
    from verify_official_lead import category
    country=str(hint.get("country_hint") or "").upper().strip()
    return country=="NL" and category(hint) is not None and not chain(str(hint.get("name_hint") or ""),str(hint.get("website_hint") or ""))


def term_match(text, needle):
    from verify_official_lead import norm
    text=norm(text);needle=norm(needle)
    for match in re.finditer(r"\b"+re.escape(needle)+r"[a-z]*\b",text):
        prefix=text[max(0,match.start()-40):match.start()]
        if re.search(r"\b(geen|niet|no|not)\b(?:\s+\w+){0,3}\s*$",prefix):
            continue
        return True
    return False


def local_proof(pages, hint):
    country=str(hint.get("country_hint") or "").upper()
    if country and country!="NL":
        return False
    texts=" ".join(str(p[1]) for p in pages)
    expected=re.sub(r"\s+","",str(hint.get("postcode_hint") or "")).upper()
    actual={re.sub(r"\s+","",m.group()) for m in POSTCODE.finditer(texts)}
    if expected and re.fullmatch(r"[1-9][0-9]{3}[A-Z]{2}",expected):
        return expected in actual
    # Old verified seeds do not carry a country hint. Require an explicit Dutch
    # postal code on their own already-fetched official pages.
    return bool(actual)


def render(item,pages,origin,prior=None):
    from verify_official_lead import BRANCH_PROOF
    branch=item["branche_meervoud"]
    found=None
    for needle,label in b.DETAILS.get(branch,[]):
        page=next((p for p in pages if term_match(p[1],needle)),None)
        if page:
            found=(page[0],needle,label)
            break
    if found is None:
        for page in pages:
            term=next((x for x in BRANCH_PROOF[branch] if term_match(page[1],x)),None)
            if term:
                found=(page[0],term,FALLBACK_LABELS[branch])
                break
    if found is None:
        raise RuntimeError("no_literal_official_service_proof")
    url,term,label=found
    # Use the already validated constructor, but provide only the literal term
    # for deterministic fallback; overwrite with the precisely chosen wording.
    row=b.make_copy(item,pages,origin)
    name=item["company"]
    offer=BRANCH_OFFER.get(branch,b.OFFER[int(item["cluster"])])
    row["subject"]=label[0].upper()+label[1:]+" bij "+name
    row["body"]="\n\n".join((item["greeting"],"Op de website van "+name+" las ik over "+label+".",
                               offer,"Zal ik een kort voorbeeld sturen dat aansluit op "+label+"?",
                               b.OPT,"Groet,\nAndrew"))
    row["evidence_url"]=url
    row["evidence"]="Letterlijke dienstterm: "+term+"; Nederlandse postcode op de officiele site bevestigd."
    if prior:
        if prior[4].casefold()!=item["email"].casefold() or "BLOKKADE" in prior[13]:
            raise RuntimeError("prior_copy_recipient_not_verified")
        # These are the user's existing reviewed texts, not a new generated
        # claim of complete semantic research. Identity, email and branch are
        # freshly verified; all copy-format rules still apply.
        body=prior[9].replace(b.FORBIDDEN+". ","")
        if body.split("\n",1)[0].strip()!=item["greeting"]:
            body=item["greeting"]+"\n"+body.split("\n",1)[1]
        row["subject"],row["body"]=prior[8],body
        row["origin"]="review50_reverified_v3"
        row["evidence"] += " Bestaande reviewtekst behouden na actuele bedrijfs-/adrescontrole."
    b.validate(row)
    return row


def inspect(hint,origin,expected_email=None,prior=None):
    from verify_official_lead import verify_official_site
    from dedupe_preflight import normalize_domain, domains_match
    if chain(str(hint.get("name_hint") or ""),str(hint.get("website_hint") or "")):
        return None
    capture=b.Capture()
    try:
        item=verify_official_site(hint,session=capture)
        if not item or not local_proof(capture.pages,hint):
            return None
        if expected_email:
            if item["email"].casefold()!=expected_email.casefold():
                return None
        elif not domains_match(normalize_domain(item["website"]),item["email"].rsplit("@",1)[1].casefold()):
            # Never accept a footer/provider address on a different domain as a
            # new prospect. Previously verified user seeds have an exact check.
            return None
        if chain(item["company"],item["website"]):
            return None
        return render(item,capture.pages,origin,prior)
    except Exception:
        return None
    finally:
        capture.close()


def persist(conn,rows,phase,checked,regions):
    # Clear only the unused tail of this task's table in the SAME atomic write.
    # This supports rejecting invalid earlier candidates without retaining stale
    # rows. Original DraftQueue and full suppression history remain untouched.
    real_post=b.post
    def atomic(client,requests):
        count=len(rows)+1
        clear={"updateCells":{"range":{"sheetId":b.TAB_ID,"startRowIndex":count,"endRowIndex":451,
                                       "startColumnIndex":0,"endColumnIndex":len(b.COLS)},
                              "fields":"userEnteredValue"}}
        real_post(client,requests+([clear] if count<451 else []))
    b.post=atomic
    try:
        b.state(conn,rows,phase,checked,regions)
    finally:
        b.post=real_post


def prepare():
    from private_candidate_handoff import authorized_writer
    from registry_readonly import load_suppressions, load_discovery_suppressions
    from dedupe_preflight import candidate_identity, match_candidate, normalize_domain
    from verify_official_lead import CATEGORIES
    from overture_discovery import discover
    conn=authorized_writer()
    historical=load_suppressions(session=conn)
    discovery_registry=load_discovery_suppressions(session=conn)
    previous=b.load_rows(conn)
    source=b.read(conn,b.QID,"'Laatste redactieronde - v3'!A1:O51")
    approved=b.read(conn,b.SID,"Approved!A1:I101")
    if len(source)!=51 or not approved:
        raise RuntimeError("private_seed_sources_incomplete")
    reverse={}
    for category,(_,branch) in CATEGORIES.items():
        reverse.setdefault(branch,category)
    aliases={"autobedrijven":"garages"}
    seeds=[]
    for row in source[1:]:
        if len(row)!=15 or "BLOKKADE" in row[13]:
            continue
        branch=aliases.get(row[2].split(" / ")[-1],row[2].split(" / ")[-1])
        if branch in reverse:
            seeds.append(({"name_hint":row[1],"website_hint":row[14],"category_hint":reverse[branch]},"review50",row[4],row,None))
    for row in previous:
        if row["branch"] in reverse:
            seeds.append(({"name_hint":row["company"],"website_hint":row["website"],"category_hint":reverse[row["branch"]]},
                          "reverified",row["email"],None,row["draft_id"]))
    for row in approved[1:]:
        if len(row)==9 and row[8]=="verified_website_and_email" and row[6] in reverse:
            seeds.append(({"name_hint":row[1],"website_hint":row[2],"category_hint":reverse[row[6]]},"approved",row[3],None,None))
    rows=[];known=[];seen=set();checked=0;started=time.monotonic();last_saved=0
    def take(candidate,old_id=None):
        if (len(rows)<b.TARGET and candidate and not match_candidate(candidate,historical) and
                not match_candidate(candidate,known)):
            if old_id:
                candidate["draft_id"]=old_id
            rows.append(candidate)
            known.append({"identity":candidate_identity(candidate),"status":"this_batch","row_number":len(rows)})
    with ThreadPoolExecutor(max_workers=6) as pool:
        todo=[]
        for hint,origin,email,prior,old_id in seeds:
            host=normalize_domain(hint["website_hint"])
            if host in seen or chain(hint["name_hint"],hint["website_hint"]) or match_candidate({**hint,"email":email},historical):
                continue
            seen.add(host)
            todo.append((hint,origin,email,prior,old_id))
        def seed(args):
            return inspect(*args[:4]),args[4]
        for candidate,old_id in pool.map(seed,todo):
            checked+=1;take(candidate,old_id)
        persist(conn,rows,"collecting_strict",checked,0)
        last_saved=len(rows)
        for index,region in enumerate(b.REGIONS,1):
            if len(rows)>=b.TARGET or checked>=10000 or time.monotonic()-started>5100:
                break
            try:
                result=discover(region=region,bbox=None,radius_km=25,keywords=["vakbedrijven"],max_results=5000,
                                require_website=True,probe_websites=False)
            except Exception:
                continue
            todo=[]
            for hint in result.get("candidates",[]):
                if not isinstance(hint,dict) or not allowed_hint(hint):
                    continue
                host=normalize_domain(hint.get("website_hint"))
                if not host or host in seen or match_candidate(hint,discovery_registry) or match_candidate(hint,known):
                    continue
                seen.add(host);todo.append(hint)
            for start in range(0,len(todo),24):
                if len(rows)>=b.TARGET or checked>=10000 or time.monotonic()-started>5100:
                    break
                block=todo[start:start+min(24,2*(b.TARGET-len(rows)))]
                checked+=len(block)
                for candidate in pool.map(lambda h:inspect(h,"discovery_nl_checked"),block):
                    take(candidate)
                if len(rows)-last_saved>=20:
                    persist(conn,rows,"collecting_strict",checked,index)
                    last_saved=len(rows)
            persist(conn,rows,"collecting_strict",checked,index)
            last_saved=len(rows)
    b.unique(rows)
    persist(conn,rows,"ready_for_review" if len(rows)==b.TARGET else "partial_strict",checked,index if 'index' in locals() else 0)
    return len(rows)


def main():
    if os.getenv("REVIEW450_PHASE")!="prepare_strict":
        print("REVIEW450_STRICT=blocked unauthorized_phase sent=0")
        return 1
    try:
        with redirect_stdout(StringIO()),redirect_stderr(StringIO()):
            count=prepare()
        print("REVIEW450_STRICT={} prepared={} target=450 mailbox_writes=0 sent=0".format("ready" if count==450 else "partial",count))
        return 0 if count==450 else 2
    except Exception:
        print("REVIEW450_STRICT=blocked source_registry_or_private_readback sent=0 mailbox_writes=0")
        return 1


if __name__=="__main__":
    sys.exit(main())
