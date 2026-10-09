"""One auditable NL/EN three-step Instantly sequence for reviewed Webactueel leads.

First message is the EXACT lead-specific approved copy. Optional first-party
observation/action enhance follow-ups, with generic fallbacks for legacy leads.
No facts, results, testimonials or contact permissions are manufactured.
"""
from __future__ import annotations

NL = {
 "step_2": """Hoi,

Ik kom nog even terug op mijn bericht over jullie website.
{% if leadscanner_observation and leadscanner_value_action %}
Wat ik concreet zag: {{leadscanner_observation}}
Ik kan {{leadscanner_value_action}} maken, zodat je ziet wat ik bedoel.
{% else %}
Ik kan in een paar regels laten zien welke 2–3 onderdelen ik als eerste zou bekijken.
{% endif %}

Zal ik dat kort toesturen?

Groet,
Andrew
Webactueel

Als dit niet relevant is, antwoord gerust met 'nee'; dan stop ik.""",
 "step_3": """Hoi,

Dit is mijn laatste bericht hierover.
{% if leadscanner_observation %}
Mijn eerdere opmerking over {{leadscanner_observation}} is vooral een mogelijk aanknopingspunt, geen oordeel over jullie website.
{% endif %}
Mocht je later behoefte hebben aan een kleine, concrete verbeterschets, dan kun je eenvoudig op dit bericht reageren. Anders laat ik het hierbij.

Groet,
Andrew
Webactueel""",
}
EN = {
 "step_2": """Hi,

Just following up on my note about your website.
{% if leadscanner_observation and leadscanner_value_action %}
What caught my eye: {{leadscanner_observation}}
I can prepare {{leadscanner_value_action}} to make the idea tangible.
{% else %}
I could outline the first 2–3 areas I'd look at, in a few short lines.
{% endif %}

Would you like me to send that over?

Best,
Andrew
Webactueel

If it's not relevant, just reply 'no' and I'll leave it there.""",
 "step_3": """Hi,

This is my last note about this.
{% if leadscanner_observation %}
My earlier comment about {{leadscanner_observation}} was simply one possible starting point, not a judgment on your website.
{% endif %}
If a small, concrete improvement sketch would ever be useful, you can just reply. Otherwise I'll leave it there.

Best,
Andrew
Webactueel""",
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
    "nl": ("5c720281-fd07-4c47-8155-c88d7d3c09b8", "Webactueel NL - Websiteadvies (Concept)"),
    "en": ("fd405145-4bf5-40c5-b6ae-2e7f5af6120c", "Webactueel EN - Website Advice (Draft)"),
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


def resolve_language_destination(client, row: dict, requested_campaign_id: str) -> str:
    """Route only reviewed NL/EN copy to its own identified, non-sending Draft."""
    known={x[0] for x in TARGET_CAMPAIGNS.values()}
    if requested_campaign_id not in known | {AUTO_CAMPAIGN_ID}:
        return requested_campaign_id
    if row.get("status")!="review_draft" or str(row.get("review_mode") or "reviewed_mail")!="reviewed_mail":
        raise ValueError("auto_language_requires_reviewed_mail")
    subject=row.get("subject")
    body=row.get("body")
    if not isinstance(subject,str) or not isinstance(body,str) or not subject.strip() or not body.strip():
        raise ValueError("auto_language_requires_reviewed_copy")
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
    if observed.get("name")!=name or type(observed.get("status")) is not int or observed["status"]!=0:
        raise ValueError("auto_language_requires_matching_draft")
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
    from instantly_client import inspect_campaign_sequence
    report=inspect_campaign_sequence(observed)
    if report["unsupported_leadscanner_variables"] or report["unresolved_template_variables"]:
        raise ValueError("auto_language_unmapped_template_variables")
    return cid
