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
Als je dat nuttig vindt, kan ik {{leadscanner_value_action}} uitwerken als kort voorbeeld.
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
If useful, I can put together {{leadscanner_value_action}} as a short example.
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
