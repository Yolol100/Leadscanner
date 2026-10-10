"""Aggregate-only quality audit of imported mijn.host mail drafts.

No recipient addresses, subjects, bodies, or raw variables are returned. These
are heuristics to prioritize human review, NOT consent or performance evidence.
"""
from __future__ import annotations
import re
from collections import Counter
from instantly_language_campaigns import classify_language, read_imported_leads

UNRESOLVED=re.compile(r"\{\{[^}]{1,100}\}\}|\[(?:bedrijf|company|naam|name|website|voornaam|first.?name)\]",re.I)
OPT_OUT_NL=("geen interesse","niet relevant","geen behoefte","niet geïnteresseerd","laat het weten als")
OPT_OUT_EN=("not interested","not relevant","no thanks","no interest","let me know if this")
SENDER=("andrew baeten",)
def mail_quality_audit(client) -> dict:
    source_id, rows = read_imported_leads(client)
    counts=Counter()
    word_lengths=[]
    for row in rows:
        payload=row.get("payload")
        if not isinstance(payload,dict):
            payload=row.get("custom_variables")
        if not isinstance(payload,dict):
            payload={}
        subj=payload.get("leadscanner_subject")
        body=payload.get("leadscanner_body")
        if not isinstance(subj,str) or not isinstance(body,str) or not subj.strip() or not body.strip():
            counts["missing_subject_or_body"]+=1
            continue
        lang=classify_language(subj,body)
        counts["language_"+lang]+=1
        n=len(body.split())
        word_lengths.append(n)
        if n<35:counts["short_under_35_words"]+=1
        if n>130:counts["long_over_130_words"]+=1
        if len(subj)>65:counts["subject_over_65_chars"]+=1
        if UNRESOLVED.search(subj+"\n"+body):counts["unresolved_template_markers"]+=1
        question_count = body.count("?")
        if question_count == 0:
            counts["questions_zero"] += 1
            counts["not_exactly_one_question"] += 1
        elif question_count == 1:
            counts["questions_one"] += 1
        elif question_count == 2:
            counts["questions_two"] += 1
            counts["not_exactly_one_question"] += 1
        else:
            counts["questions_three_or_more"] += 1
            counts["not_exactly_one_question"] += 1
        lower=body.casefold()
        if "webactueel" in (subj+"\n"+body).casefold():
            counts["legacy_brand_in_copy"]+=1
        if "andrew baeten" not in lower:
            counts["missing_andrew_baeten_signature"]+=1
        if not all(isinstance(payload.get(key),str) and payload[key].strip() for key in (
            "leadscanner_observation","leadscanner_value_action","leadscanner_evidence_url"
        )):
            counts["missing_verified_followup_fields"]+=1
        if not any(v in lower for v in SENDER):counts["no_sender_identification"]+=1
        if not any(v in lower for v in (OPT_OUT_NL if lang=="nl" else OPT_OUT_EN)):counts["no_obvious_optout_phrase"]+=1
        if payload.get("leadscanner_observation") and payload.get("leadscanner_value_action"):
            counts["both_verified_fact_placeholders_present"]+=1
        if payload.get("leadscanner_contact_basis") in {"consent_verified","existing_customer_related_verified"} and payload.get("leadscanner_contact_basis_ref"):
            counts["documented_contact_basis"]+=1
    return {
        "schema_version":"leadscanner-import-mail-quality/1.0",
        "source_list_id":source_id,
        "source_count":len(rows),
        "complete_copy_count":len(word_lengths),
        "language_counts":{k:counts["language_"+k] for k in ("nl","en","unknown")},
        "mail_review_flags":{
            k:counts[k] for k in (
                "missing_subject_or_body","short_under_35_words","long_over_130_words",
                "legacy_brand_in_copy","missing_andrew_baeten_signature",
                "missing_verified_followup_fields",
                "subject_over_65_chars","unresolved_template_markers",
                "not_exactly_one_question","no_sender_identification",
                "no_obvious_optout_phrase",
            )
        },
        "question_count_distribution": {
            "zero": counts["questions_zero"],
            "one": counts["questions_one"],
            "two": counts["questions_two"],
            "three_or_more": counts["questions_three_or_more"],
        },
        "question_count_is_a_review_heuristic_not_reply_rate": True,
        "both_verified_fact_placeholders_present":counts["both_verified_fact_placeholders_present"],
        "documented_contact_basis_count":counts["documented_contact_basis"],
        "copy_is_not_consent":True,
        "quality_guaranteed":False,
        "contains_subject_body_or_emails":False,
        "writes":False,
    }
