"""Final editing and QA for the user's exact private 450-draft batch.

No mailbox access, no automatic approval, no sending. Existing individually
reviewed seed texts are preserved. Generic generated copy is made natural and
branch-specific without adding a new fact beyond the recorded official term.
"""
from __future__ import annotations
import copy
import os
import re
import sys
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO

import review450 as b
import review450_strict as strict

# Concrete offers are proposals, never allegations about the recipient's site.
OFFERS = {
 "schilders": ("Ik help schilders om het verschil tussen werkzaamheden op hun website helder uit te leggen, met voorbeelden en een logische stap naar de bestaande aanvraag.", "schilderwerk"),
 "hoveniers": ("Ik help hoveniers om projectfoto's en diensten op mobiel duidelijk met elkaar te verbinden, zodat een bezoeker gericht contact kan opnemen.", "tuinwerk"),
 "loodgieters": ("Ik help loodgieters hun werkzaamheden op mobiel duidelijk te presenteren, zodat klanten het juiste soort vraag en de belangrijkste gegevens kunnen doorgeven.", "loodgieterswerk"),
 "elektriciens": ("Ik help elektriciens om verschillende werkzaamheden helder uit te leggen en klanten gericht naar de bestaande contactmogelijkheid te leiden.", "elektrawerk"),
 "timmerbedrijven": ("Ik help timmerbedrijven om projectvoorbeelden en werkzaamheden op mobiel duidelijk te tonen, met een eenvoudige stap naar een gerichte aanvraag.", "timmerwerk"),
 "dakdekkers": ("Ik help dakdekkers om hun werkzaamheden duidelijk te onderscheiden en bezoekers via de bestaande contactroute een gerichte vraag te laten stellen.", "dakwerk"),
 "stukadoors": ("Ik help stukadoors om afwerkingen met duidelijke voorbeelden te tonen, zodat klanten beter weten welke informatie bij hun aanvraag hoort.", "stucwerk"),
 "tegelzetters": ("Ik help tegelzetters om voorbeelden van hun werk mobiel overzichtelijk te tonen, met een logische stap naar een gerichte aanvraag.", "tegelwerk"),
 "aannemers": ("Ik help aannemers om projectvoorbeelden en werkzaamheden op hun website helder te verbinden, zodat bezoekers gericht contact opnemen.", "bouwprojecten"),
 "glazenwassers": ("Ik help glazenwassers om verschillende werkzaamheden op mobiel duidelijk te laten kiezen, met de relevante pandgegevens bij een aanvraag.", "glasbewassing"),
 "schoonmaakbedrijven": ("Ik help schoonmaakbedrijven om hun diensten helder te onderscheiden, zodat een bezoeker gericht informatie over een pand of opdracht kan doorgeven.", "schoonmaak"),
 "boomverzorgers": ("Ik help boomverzorgers om werkzaamheden met voorbeelden uit te leggen en klanten via de bestaande contactroute een gerichte vraag te laten stellen.", "boomverzorging"),
 "kappers": ("Ik help kapsalons om behandelingen op mobiel helder uit te leggen en bezoekers naar de bestaande afspraakmogelijkheden te leiden.", "haarverzorging"),
 "schoonheidssalons": ("Ik help salons om bezoekers het verschil tussen behandelingen duidelijk te laten zien, met een logische stap naar persoonlijk contact of een afspraak.", "behandelingen"),
 "rijscholen": ("Ik help rijscholen om lesinformatie en praktische vragen op mobiel overzichtelijk te presenteren, met een duidelijke stap naar de bestaande contactroute.", "rijlessen"),
 "sportscholen": ("Ik help sportscholen om hun aanbod op mobiel duidelijk uit te leggen, zodat bezoekers weten wat bij hen past en hoe ze contact opnemen.", "sportaanbod"),
 "restaurants": ("Ik help restaurants om hun menu en praktische informatie op mobiel overzichtelijk te tonen, met een duidelijke stap naar de bestaande contact- of reserveermogelijkheid.", "het menu"),
 "horecazaken": ("Ik help horecazaken om aanbod, openingstijden en contact op mobiel snel vindbaar te maken, zonder de bestaande werkwijze te vervangen.", "jullie zaak"),
 "bakkerijen": ("Ik help bakkerijen om hun aanbod op mobiel overzichtelijk te tonen en bezoekers naar de bestaande bestel- of contactmogelijkheid te leiden.", "het aanbod"),
 "slagerijen": ("Ik help slagerijen om hun producten en praktische bestelinformatie op mobiel duidelijk te presenteren, passend bij de bestaande werkwijze.", "het aanbod"),
 "logiesbedrijven": ("Ik help logiesbedrijven om kamers, ligging en praktische informatie op mobiel helder te presenteren, met een logische stap naar de bestaande contact- of boekingsroute.", "verblijfsinformatie"),
 "bloemisten": ("Ik help bloemisten om het aanbod per gelegenheid op mobiel duidelijk te tonen, met een passende stap naar de bestaande bestel- of contactmogelijkheid.", "bloemwerk"),
 "fietsenwinkels": ("Ik help fietsenwinkels om hun aanbod op mobiel overzichtelijk te presenteren, zodat bezoekers een gerichte vraag over een fiets kunnen stellen.", "het fietsaanbod"),
 "garages": ("Ik help garages om verschillende diensten op mobiel duidelijk te laten kiezen en klanten via de bestaande contactroute hun vraag te laten toelichten.", "de werkplaats"),
 "pechhulpbedrijven": ("Ik help servicebedrijven om bereikbaarheid en werkwijze mobiel duidelijk te tonen. Voor dringende hulp blijft direct bellen centraal staan.", "bereikbaarheid"),
 "dierenartsen": ("Ik help praktijken om diensten en praktische informatie mobiel rustig te ordenen, met een duidelijke stap naar persoonlijk contact. Medische keuzes blijven bij de dierenarts.", "praktijkinformatie"),
 "fysiotherapiepraktijken": ("Ik help praktijken om behandelinformatie mobiel rustig uit te leggen en bezoekers naar persoonlijk contact te leiden. Medische keuzes blijven bij de behandelaar.", "behandelinformatie"),
 "dierenoppassers": ("Ik help lokale dienstverleners om werkwijze en praktische informatie mobiel helder te tonen, zodat bezoekers weten hoe ze persoonlijk contact leggen.", "de werkwijze"),
 "uitvaartbedrijven": ("Ik help uitvaartbedrijven om praktische informatie rustig en overzichtelijk te presenteren, met een duidelijke weg naar persoonlijk contact.", "persoonlijk contact"),
 "reparatiebedrijven": ("Ik help reparatiebedrijven om hun werkzaamheden duidelijk uit te leggen en klanten gericht het type apparaat of voertuig en de klacht te laten beschrijven.", "servicevragen"),
 "wasserijen": ("Ik help wasserijen en stomerijen om hun diensten en praktische informatie mobiel overzichtelijk te tonen, met een duidelijke stap naar de bestaande contactroute.", "reinigingsdiensten"),
}


def label_from_proof(row):
    evidence = row.get("evidence", "")
    match = re.fullmatch(r"Letterlijke dienstterm: ([^;]+); Nederlandse postcode op de officiele site bevestigd\.", evidence)
    if not match:
        raise RuntimeError("final_copy_requires_strict_source_proof")
    term = match.group(1)
    branch = row["branch"]
    from verify_official_lead import BRANCH_PROOF
    for needle, label in b.DETAILS.get(branch, []):
        if needle == term:
            return label
    if term not in BRANCH_PROOF.get(branch, ()):
        raise RuntimeError("recorded_service_not_in_verified_branch")
    return strict.FALLBACK_LABELS[branch]


def polish(row):
    row = copy.deepcopy(row)
    b.validate(row)
    if strict.chain(row["company"], row["website"]):
        raise RuntimeError("chain_needs_independent_decision_proof")
    if row["origin"] == "review50_reverified_v3":
        # This is the user's already reviewed, individually written version.
        # Never replace it with a generic branch template.
        row["body"] = row["body"].replace(b.FORBIDDEN + ". ", "")
        b.validate(row)
        return row
    label = label_from_proof(row)
    branch = row["branch"]
    if branch not in OFFERS:
        raise RuntimeError("branch_copy_not_reviewed")
    offer, fallback_topic = OFFERS[branch]
    generic = label in strict.FALLBACK_LABELS.values()
    name = row["company"]
    greeting = row["body"].split("\n", 1)[0]
    if generic:
        opening = "Ik kwam de website van " + name + " tegen."
        topic = fallback_topic
    else:
        opening = "Op de website van " + name + " zag ik informatie over " + label + "."
        topic = label
    cta = "Zal ik een korte voorbeeldopzet voor " + topic + " sturen?"
    row["subject"] = topic[0].upper() + topic[1:] + " bij " + name
    row["body"] = "\n\n".join((greeting, opening, offer, cta, b.OPT, "Groet,\nAndrew"))
    b.validate(row)
    return row


def audit(rows):
    from dedupe_preflight import normalize_domain, domains_match
    if len(rows) != b.TARGET:
        raise RuntimeError("final_review_requires_exactly_450")
    b.unique(rows)
    subjects = set()
    texts = set()
    cluster_counts = {}
    min_words, max_words = 999, 0
    old_review = 0
    for row in rows:
        b.validate(row)
        if strict.chain(row["company"], row["website"]):
            raise RuntimeError("chain_not_allowed")
        if row["origin"] == "review50_reverified_v3":
            old_review += 1
            if "Nederlandse postcode op de officiele site bevestigd." not in row["evidence"]:
                raise RuntimeError("seed_country_evidence_missing")
        else:
            label_from_proof(row)
        if row["origin"] == "discovery_nl_checked" and not domains_match(
                normalize_domain(row["website"]), row["email"].rsplit("@", 1)[1].casefold()):
            raise RuntimeError("new_contact_domain_not_confirmed")
        text = row["body"]
        if re.search(r"\{\{|\}\}|\[(?:naam|bedrijf|voornaam|voorbeeld)\]", text, re.I):
            raise RuntimeError("copy_placeholder_remaining")
        if row["subject"] in subjects or text in texts:
            raise RuntimeError("duplicate_copy_requires_review")
        if any(term in text.casefold() for term in ("gegarandeerd", "100%", b.FORBIDDEN.casefold())):
            raise RuntimeError("unsupported_claim_or_removed_sentence")
        subjects.add(row["subject"])
        texts.add(text)
        words = len(text.split())
        min_words, max_words = min(min_words, words), max(max_words, words)
        cluster_counts[row["cluster"]] = cluster_counts.get(row["cluster"], 0) + 1
    return {"count":len(rows), "unique_subjects":len(subjects), "unique_bodies":len(texts),
            "min_words":min_words, "max_words":max_words, "review50_retained":old_review,
            "clusters":cluster_counts, "sent":0, "mailbox_writes":0}


def main():
    if os.getenv("REVIEW450_PHASE") != "final_copy":
        print("REVIEW450_QA=blocked unauthorized_phase sent=0")
        return 1
    try:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            from private_candidate_handoff import authorized_writer
            from registry_readonly import load_suppressions
            from dedupe_preflight import match_candidate
            conn = authorized_writer()
            state = dict(b.read(conn, b.SID, b.STATE + "!A2:B11"))
            current = b.load_rows(conn)
            before = [b.COLS] + [[row[k] for k in b.COLS] for row in current]
            if state.get("status") != "ready_for_review" or b.digest(before) != state.get("content_sha256"):
                raise RuntimeError("batch_not_complete_or_changed")
            registry = load_suppressions(session=conn)
            if any(match_candidate(row, registry) for row in current):
                raise RuntimeError("historical_exclusion_before_final_copy")
            after = [polish(row) for row in current]
            report = audit(after)
            fresh = b.load_rows(conn)
            if fresh != current:
                raise RuntimeError("batch_changed_during_editorial_review")
            strict.persist(conn, after, "ready_for_review", int(state.get("sites_checked", "0")), int(state.get("regions", "0")))
            actual = b.load_rows(conn)
            if actual != after:
                raise RuntimeError("final_copy_readback_failed")
            final_report = audit(actual)
        import json
        print("REVIEW450_QA=green " + json.dumps(final_report, sort_keys=True))
        return 0
    except Exception:
        print("REVIEW450_QA=blocked private_source_copy_or_readback sent=0 mailbox_writes=0")
        return 1


if __name__ == "__main__":
    sys.exit(main())
