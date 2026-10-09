"""Privacy-safe NL/EN planning for imported mijn.host drafts.

Language is inferred from the actual reviewed email copy. Never infer from names,
TLDs, company nationality, recipient name, or personal data. Ambiguous = hold.
No campaign, lead, account, or mailbox write occurs here.
"""
from __future__ import annotations

import re
from collections import Counter

from myhost_instantly_import import matching_list_ids

NL_WORDS = frozenset((
    "aan als bij dan dat de deze die dit een er geen graag heb hebben het hier "
    "hoi ik is je jij jullie kan kunnen kort laat met mij mijn naar nog ook op "
    "ons onze voor van wat we wel wij wil willen wordt zou zullen zijn "
    "bedankt bericht benieuwd even vraag bekeken zag idee voorstel"
).split())
EN_WORDS = frozenset((
    "a about and are as at be been can could dear do for from had has have "
    "hello hey hi how i if in is it just let me my not on our please saw "
    "send short some that the their there this to was we were what when "
    "with would you your yours website thought idea quick question noticed"
).split())
NL_PHRASES = (
    "goedemorgen", "goede middag", "goedemiddag", "met vriendelijke groet",
    "laat maar weten", "laat gerust weten", "ik zag", "ik dacht", "ik merkte",
    "ik heb", "jullie website", "jouw website", "ik vroeg me af",
    "zou je", "zou u", "wat vind je", "een korte vraag",
)
EN_PHRASES = (
    "good morning", "kind regards", "best regards", "let me know",
    "i noticed", "i saw", "i thought", "i wanted to", "would you",
    "your website", "a quick question", "i was wondering", "could you",
    "i have an idea", "if you're interested",
)
LANGUAGE_CAMPAIGN_NAMES = {
    "nl": "Webactueel NL - Websiteadvies (Concept)",
    "en": "Webactueel EN - Website Advice (Draft)",
}
MAX_SOURCE_ROWS = 5000


def classify_language(subject: str, body: str) -> str:
    """Classify only when independent sentence tokens establish one language."""
    if not isinstance(subject, str) or not isinstance(body, str):
        return "unknown"
    text = (subject + "\n" + body).casefold()
    if not text.strip():
        return "unknown"
    words = set(re.findall(r"[a-zà-ÿ']+", text))
    nl_words = len(words & NL_WORDS)
    en_words = len(words & EN_WORDS)
    nl_phrases = sum(1 for p in NL_PHRASES if p in text)
    en_phrases = sum(1 for p in EN_PHRASES if p in text)
    nl_score = nl_words + 3 * nl_phrases
    en_score = en_words + 3 * en_phrases
    # Require at least four distinct supporting words and clear separation.
    if nl_words >= 4 and nl_score >= en_score + 5 and nl_score >= 8:
        return "nl"
    if en_words >= 4 and en_score >= nl_score + 5 and en_score >= 8:
        return "en"
    return "unknown"


def _text(value: object) -> str:
    return str(value or "").strip()


def _safe_page(raw: object) -> tuple[list[dict], str]:
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise RuntimeError("language_source_page_invalid")
    rows = raw["items"]
    if any(not isinstance(item, dict) for item in rows):
        raise RuntimeError("language_source_row_invalid")
    return rows, _text(raw.get("next_starting_after"))


def read_imported_leads(client) -> tuple[str, list[dict]]:
    ids = matching_list_ids(client)
    if len(ids) != 1:
        raise RuntimeError("single_import_source_list_required")
    list_id = ids[0]
    result, cursor, seen = [], "", set()
    while True:
        raw = client.list_leads(list_id=list_id, limit=100, starting_after=cursor or None)
        rows, next_cursor = _safe_page(raw)
        for row in rows:
            observed_id = _text(row.get("list_id"))
            if observed_id != list_id:
                raise RuntimeError("language_source_list_identity_mismatch")
        result.extend(rows)
        if len(result) > MAX_SOURCE_ROWS:
            raise RuntimeError("language_source_limit_exceeded")
        if not next_cursor:
            return list_id, result
        if not rows or next_cursor == cursor or next_cursor in seen:
            raise RuntimeError("language_source_pagination_invalid")
        seen.add(next_cursor)
        cursor = next_cursor


def inspect_lead_language(lead: dict) -> str:
    if _text(lead.get("campaign")):
        return "already_assigned"
    if lead.get("status") in {-1, -2, -3}:
        return "suppressed"
    variables = lead.get("payload")
    if not isinstance(variables, dict):
        variables = lead.get("custom_variables")
    if not isinstance(variables, dict):
        return "missing_data"
    if variables.get("leadscanner_import_origin") != "myhost_drafts":
        return "missing_data"
    if variables.get("leadscanner_contact_basis") not in {"review_required", "consent_verified", "existing_customer_related_verified"}:
        return "missing_data"
    subject = variables.get("leadscanner_subject")
    body = variables.get("leadscanner_body")
    if not isinstance(subject, str) or not isinstance(body, str) or not subject.strip() or not body.strip():
        return "missing_data"
    return classify_language(subject, body)


def audit_language_split(client) -> dict:
    list_id, leads = read_imported_leads(client)
    seen_emails: set[str] = set()
    result = Counter()
    for lead in leads:
        email = _text(lead.get("email")).casefold()
        if not email or email in seen_emails:
            raise RuntimeError("language_source_duplicate_or_missing_email")
        seen_emails.add(email)
        result[inspect_lead_language(lead)] += 1
    return {
        "schema_version": "leadscanner-instantly-language-audit/1.0",
        "source_list_id": list_id,
        "source_count": len(leads),
        "nl": result["nl"],
        "en": result["en"],
        "unknown_hold": result["unknown"],
        "already_assigned_hold": result["already_assigned"],
        "suppressed_hold": result["suppressed"],
        "missing_data_hold": result["missing_data"],
        "total_routeable": result["nl"] + result["en"],
        "all_others_held": len(leads) - result["nl"] - result["en"],
        "campaign_names": LANGUAGE_CAMPAIGN_NAMES,
        "automatic_send": False,
        "write": False,
        "contains_lead_data": False,
    }
