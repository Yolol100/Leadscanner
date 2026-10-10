"""One auditable NL/EN three-step Instantly sequence for reviewed Andrew Baeten leads.

First message is the EXACT lead-specific approved copy. Verified first-party
observation/action are required before any target-campaign staging; both
follow-ups refer to the actual recipient's verified observation.
No facts, results, testimonials or contact permissions are manufactured.
"""
from __future__ import annotations

from urllib.parse import urlparse

NL = {
 "step_2": """Hoi,

Ik kom nog even terug op mijn eerdere bericht. Op jullie website zag ik dit:

"{{leadscanner_observation}}"

Ik kan {{leadscanner_value_action}} maken om mijn idee concreet te laten zien.

Zal ik dat kort toesturen?

Als dit niet relevant is, antwoord gerust met 'nee'; dan stop ik.

Groet,
Andrew Baeten""",
 "step_3": """Hoi,

Dit is mijn laatste bericht. Mijn idee kwam voort uit dit onderdeel van jullie website:

"{{leadscanner_observation}}"

Dat is slechts een mogelijk aanknopingspunt, geen oordeel over jullie huidige aanpak. Mocht een kort voorbeeld later nuttig zijn, dan kun je eenvoudig reageren. Anders laat ik het hierbij.

Groet,
Andrew Baeten""",
}
EN = {
 "step_2": """Hi,

Just following up on my earlier note. This was the detail I noticed on your website:

"{{leadscanner_observation}}"

I can prepare {{leadscanner_value_action}} to make the idea concrete.

Would you like me to email that over?

If it's not relevant, just reply 'no' and I'll stop.

Best,
Andrew Baeten""",
 "step_3": """Hi,

This is my last note. My earlier idea came from this detail on your website:

"{{leadscanner_observation}}"

It's just a possible starting point, not a judgment on your current approach. If a short example would be useful later, feel free to reply. Otherwise I'll leave it here.

Best,
Andrew Baeten""",
}

def campaign_steps(language: str) -> list[dict]:
    if language not in {"nl", "en"}:
        raise ValueError("campaign_language_invalid")
    texts = NL if language == "nl" else EN
    # Instantly applies a step's delay to the NEXT step: first follow-up after
    # 4 calendar days, final follow-up 5 days after that. The final step's
    # unused delay is zero because there is no fourth message.
    return [
        {"type": "email", "delay": 4, "delay_unit": "days",
         "variants": [{"subject": "{{leadscanner_subject}}", "body": "{{leadscanner_body}}"}]},
        {"type": "email", "delay": 5, "delay_unit": "days",
         "variants": [{"subject": "", "body": texts["step_2"]}]},
        {"type": "email", "delay": 0, "delay_unit": "days",
         "variants": [{"subject": "", "body": texts["step_3"]}]},
    ]

def campaign_payload(language: str) -> dict:
    return {"sequences": [{"steps": campaign_steps(language)}],
        "daily_limit": 10, "daily_max_leads": 5,
        "email_gap": 12, "random_wait_max": 5,
        "stop_on_reply": True, "stop_on_auto_reply": True,
        "stop_for_company": True, "allow_risky_contacts": False,
        "open_tracking": False, "link_tracking": False,
        "text_only": True, "insert_unsubscribe_header": True,
        "email_list": []}


AUTO_CAMPAIGN_ID = "auto_language"
TARGET_CAMPAIGNS = {
    "nl": ("5c720281-fd07-4c47-8155-c88d7d3c09b8", "Websiteadvies NL"),
    "en": ("fd405145-4bf5-40c5-b6ae-2e7f5af6120c", "Websiteadvies EN"),
}


def campaign_copy_matches(campaign: dict, language: str) -> bool:
    """Compare saved provider copy and delays, ignoring provider-owned IDs."""
    sequences = campaign.get("sequences") if isinstance(campaign, dict) else None
    if not isinstance(sequences, list) or len(sequences) != 1:
        return False
    actual = sequences[0].get("steps") if isinstance(sequences[0], dict) else None
    expected = campaign_steps(language)
    if not isinstance(actual, list) or len(actual) != len(expected):
        return False
    for step, baseline in zip(actual, expected):
        if not isinstance(step, dict) or any(
            step.get(key) != baseline[key] for key in ("type", "delay", "delay_unit")
        ):
            return False
        variants = step.get("variants")
        if not isinstance(variants, list) or len(variants) != 1 or not isinstance(variants[0], dict):
            return False
        if any(variants[0].get(key) != baseline["variants"][0][key] for key in ("subject", "body")):
            return False
    return True


def campaign_activation_baseline_matches(campaign: dict, language: str) -> bool:
    """Never launch either reviewed NL/EN campaign after copy or safety drift."""
    if not campaign_copy_matches(campaign, language):
        return False
    expected = campaign_payload(language)
    fields = ("stop_on_reply", "stop_on_auto_reply", "stop_for_company",
              "allow_risky_contacts", "open_tracking", "link_tracking",
              "text_only", "insert_unsubscribe_header", "daily_limit",
              "daily_max_leads", "email_gap")
    if any(type(campaign.get(key)) is not type(expected[key])
           or campaign.get(key) != expected[key] for key in fields):
        return False
    schedule = campaign.get("campaign_schedule")
    entries = schedule.get("schedules") if isinstance(schedule, dict) else None
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        return False
    entry = entries[0]
    timing = entry.get("timing")
    return (
        entry.get("timezone") == "Arctic/Longyearbyen"
        and isinstance(timing, dict)
        and timing.get("from") == "09:30"
        and timing.get("to") == "16:30"
        and entry.get("days") == {str(i): 1 <= i <= 5 for i in range(7)}
    )


def first_mail_uses_verified_recipient_detail(
    body: object, observation: object, action: object,
    source_type: object, evidence_url: object,
) -> bool:
    """Conservative recipient-specificity gate; never a claim of human approval.

    Changing only the company name cannot satisfy this check. The first mail
    must literally mention both a usable first-party customer journey detail
    AND the related value-first offer that also personalize the follow-ups.
    """
    if not all(isinstance(value, str) and value.strip()
               for value in (body, observation, action, evidence_url)):
        return False
    if source_type != "official_site" or len(action.split()) < 3:
        return False
    try:
        url = urlparse(evidence_url)
        if (url.scheme not in {"https", "http"} or not url.hostname
            or url.username is not None or url.password is not None
            or url.hostname in {"localhost", "127.0.0.1", "::1"}):
            return False
    except ValueError:
        return False
    # Share the already established Leadscanner signal vocabulary. A generic
    # compliment about a website never becomes evidence just by being unique.
    from outreach_stages import classify_evidence, normalize_text
    if classify_evidence({
        "text": observation, "source_type": source_type, "source_url": evidence_url,
    }) is None:
        return False
    normalized = normalize_text(body)
    return (
        normalize_text(observation) in normalized
        and normalize_text(action) in normalized
    )


def resolve_language_destination(client, row: dict, requested_campaign_id: str) -> str:
    """Route reviewed NL/EN copy only to the exact Draft/Paused campaign without senders."""
    known={x[0] for x in TARGET_CAMPAIGNS.values()}
    if requested_campaign_id not in known | {AUTO_CAMPAIGN_ID}:
        return requested_campaign_id
    if row.get("status")!="review_draft" or str(row.get("review_mode") or "reviewed_mail")!="reviewed_mail":
        raise ValueError("auto_language_requires_reviewed_mail")
    subject=row.get("subject")
    body=row.get("body")
    if not isinstance(subject,str) or not isinstance(body,str) or not subject.strip() or not body.strip():
        raise ValueError("auto_language_requires_reviewed_copy")
    if "webactueel" in (subject+"\n"+body).casefold():
        raise ValueError("reviewed_mail_obsolete_sender_brand_forbidden")
    # Avoid cycles through the existing mijn.host migration adapter.
    from instantly_language_campaigns import classify_language
    lang=classify_language(subject,body)
    if lang not in TARGET_CAMPAIGNS:
        raise ValueError("reviewed_mail_language_ambiguous_hold")
    cid,name=TARGET_CAMPAIGNS[lang]
    if requested_campaign_id!=AUTO_CAMPAIGN_ID and requested_campaign_id!=cid:
        raise ValueError("reviewed_mail_campaign_language_mismatch")
    observed=client.get_campaign(cid)
    if not isinstance(observed,dict) or observed.get("id")!=cid:
        raise RuntimeError("auto_language_campaign_readback_invalid")
    from instantly_client import SAFE_CAMPAIGN_STATUSES
    if (observed.get("name")!=name or type(observed.get("status")) is not int
            or observed["status"] not in SAFE_CAMPAIGN_STATUSES):
        raise ValueError("auto_language_requires_matching_non_sending_campaign")
    if observed.get("email_list")!=[]:
        raise ValueError("auto_language_requires_zero_senders")
    sequences=observed.get("sequences")
    if not isinstance(sequences,list) or len(sequences)!=1:
        raise ValueError("auto_language_requires_three_step_sequence")
    steps=sequences[0].get("steps") if isinstance(sequences[0],dict) else None
    if not isinstance(steps,list) or len(steps)!=3:
        raise ValueError("auto_language_requires_three_step_sequence")
    if steps[0].get("variants")!=[{
        "subject":"{{leadscanner_subject}}","body":"{{leadscanner_body}}"
    }]:
        raise ValueError("auto_language_first_step_copy_contract_invalid")
    if not campaign_copy_matches(observed, lang):
        raise ValueError("auto_language_copy_readback_mismatch")
    if not first_mail_uses_verified_recipient_detail(
        body, row.get("verified_observation"), row.get("value_first_action"),
        row.get("verified_observation_source_type"),
        row.get("verified_observation_source_url"),
    ):
        raise ValueError("auto_language_first_mail_lacks_verified_specificity")
    from instantly_client import inspect_campaign_sequence
    report=inspect_campaign_sequence(observed)
    if report["unsupported_leadscanner_variables"] or report["unresolved_template_variables"]:
        raise ValueError("auto_language_unmapped_template_variables")
    return cid
