"""Aggregate-only quality audit of imported mijn.host mail drafts.

No recipient addresses, subjects, bodies, or raw variables are returned. These
are heuristics to prioritize human review, NOT consent or performance evidence.
"""
from __future__ import annotations
import re
import hashlib
from collections import Counter
from instantly_language_campaigns import classify_language, read_imported_leads

UNRESOLVED=re.compile(r"\{\{[^}]{1,100}\}\}|\[(?:bedrijf|company|naam|name|website|voornaam|first.?name)\]",re.I)
# A generic "laat het weten als" / "let me know if this" is not an opt-out.
# This is a review heuristic, not evidence of compliant unsubscribe handling.
OPT_OUT_NL = ("geen interesse", "niet relevant", "geen behoefte", "niet geïnteresseerd",
              "dan stop ik", "niet meer mailen", "geen mail meer", "ik stop",
              "uitschrijven", "afmelden", "als je dit niet wilt")
OPT_OUT_EN = ("not interested", "not relevant", "no thanks", "no interest",
              "i'll stop", "i will stop", "reply 'no'", "reply \"no\"",
              "unsubscribe", "don't email", "do not email", "stop emailing",
              "if this isn't relevant", "if this is not relevant")
SENDER=("andrew baeten",)
# Only recognize unambiguous, single-name signatures at the very end of a
# reviewed source email. Never guess which sender an unsigned mail represents.
SIGNATURE_FULL = re.compile(r"(?i)(?:^|\n)[ \t]*andrew[ \t]+baeten[ \t]*[.!]?[ \t]*\Z")
SIGNATURE_FIRST = re.compile(
    r"(?i)(?:^|\n)[ \t]*(?:groet|met vriendelijke groet|hartelijke groet|"
    r"vriendelijke groeten|best|kind regards|regards|cheers)[ \t]*[,!.]?[ \t]*\r?\n"
    r"[ \t]*andrew[ \t]*[.!]?[ \t]*\Z"
)
CLOSING_ONLY = re.compile(
    r"(?i)(?:^|\n)[ \t]*(?:groet|met vriendelijke groet|hartelijke groet|"
    r"vriendelijke groeten|best|kind regards|regards|cheers)[ \t]*[,!.]?[ \t]*\Z"
)


def classify_signature_tail(body: str) -> str:
    if not isinstance(body, str) or not body.strip():
        return "missing_copy"
    normalized = body.strip()
    if SIGNATURE_FULL.search(normalized):
        return "full_name_tail"
    if SIGNATURE_FIRST.search(normalized):
        return "first_name_only_tail"
    if CLOSING_ONLY.search(normalized):
        return "closing_without_name_tail"
    return "unrecognized_tail"

def _private_copy_digest(value: str) -> str:
    """Fingerprint normalized content only inside the runner, never return it."""
    normalized = " ".join(value.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _reused_groups(values: Counter) -> dict[str, int]:
    return {
        "distinct_count": len(values),
        "reused_group_count": sum(freq > 1 for freq in values.values()),
        "recipients_in_reused_groups": sum(freq for freq in values.values() if freq > 1),
        "largest_group_size": max(values.values(), default=0),
    }


def mail_quality_audit(client) -> dict:
    source_id, rows = read_imported_leads(client)
    counts=Counter()
    word_lengths=[]
    subject_fingerprints=Counter()
    body_fingerprints=Counter()
    pair_fingerprints=Counter()
    language_quality={language:Counter() for language in ("nl", "en", "unknown")}
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
        subject_hash = _private_copy_digest(subj)
        body_hash = _private_copy_digest(body)
        subject_fingerprints[subject_hash] += 1
        body_fingerprints[body_hash] += 1
        pair_fingerprints[_private_copy_digest(subject_hash + "|" + body_hash)] += 1
        language_quality[lang]["complete_copy_count"] += 1
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
            language_quality[lang]["multiple_or_missing_questions"] += 1
        elif question_count == 1:
            counts["questions_one"] += 1
        elif question_count == 2:
            counts["questions_two"] += 1
            counts["not_exactly_one_question"] += 1
            language_quality[lang]["multiple_or_missing_questions"] += 1
        else:
            counts["questions_three_or_more"] += 1
            counts["not_exactly_one_question"] += 1
            language_quality[lang]["multiple_or_missing_questions"] += 1
        lower=body.casefold()
        counts["signature_tail_"+classify_signature_tail(body)]+=1
        if row.get("campaign") is not None:
            counts["source_lead_assigned_to_campaign"]+=1
        if "webactueel" in (subj+"\n"+body).casefold():
            counts["legacy_brand_in_copy"]+=1
        if "andrew baeten" not in lower:
            counts["missing_andrew_baeten_signature"]+=1
        if not all(isinstance(payload.get(key),str) and payload[key].strip() for key in (
            "leadscanner_observation","leadscanner_value_action","leadscanner_evidence_url"
        )):
            counts["missing_verified_followup_fields"]+=1
        if not any(v in lower for v in SENDER):counts["no_sender_identification"]+=1
        if not any(v in lower for v in (OPT_OUT_NL if lang=="nl" else OPT_OUT_EN)):
            counts["no_obvious_optout_phrase"] += 1
            language_quality[lang]["no_obvious_optout_phrase"] += 1
        if payload.get("leadscanner_observation") and payload.get("leadscanner_value_action"):
            counts["both_verified_fact_placeholders_present"]+=1
        basis = payload.get("leadscanner_contact_basis")
        if basis in {"consent_verified", "existing_customer_related_verified"} and payload.get("leadscanner_contact_basis_ref"):
            counts["documented_contact_basis"] += 1
        if basis == "review_required":
            counts["contact_basis_unverified"] += 1
        if not any(isinstance(payload.get(k), str) and payload[k].strip()
                   for k in ("leadscanner_evidence_url", "leadscanner_observation")):
            language_quality[lang]["no_separate_first_party_evidence"] += 1
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
        "copy_diversity": {
            "subject": _reused_groups(subject_fingerprints),
            "body": _reused_groups(body_fingerprints),
            "subject_and_body_pair": _reused_groups(pair_fingerprints),
            "diversity_is_not_personalization_proof": True,
            "raw_text_or_fingerprints_returned": False,
        },
        "language_review": {
            lang: {
                "complete_copy_count": language_quality[lang]["complete_copy_count"],
                "multiple_or_missing_questions": language_quality[lang]["multiple_or_missing_questions"],
                "no_obvious_optout_phrase": language_quality[lang]["no_obvious_optout_phrase"],
                "no_separate_first_party_evidence": language_quality[lang]["no_separate_first_party_evidence"],
            }
            for lang in ("nl", "en", "unknown")
        },
        "contact_basis_unverified_count": counts["contact_basis_unverified"],
        "both_verified_fact_placeholders_present":counts["both_verified_fact_placeholders_present"],
        "documented_contact_basis_count":counts["documented_contact_basis"],
        "signature_tail_distribution":{
            key:counts["signature_tail_"+key] for key in (
                "full_name_tail","first_name_only_tail",
                "closing_without_name_tail","unrecognized_tail","missing_copy"
            )
        },
        "source_leads_assigned_to_campaign":counts["source_lead_assigned_to_campaign"],
        "signature_fix_is_not_permission_or_content_approval":True,
        "copy_is_not_consent":True,
        "quality_guaranteed":False,
        "contains_subject_body_or_emails":False,
        "writes":False,
    }
