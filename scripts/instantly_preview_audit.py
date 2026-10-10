"""No-send synthetic rendering audit of the exact live Andrew Baeten NL/EN campaigns.

This is deliberately NOT the provider's campaign Preview UI. All recipients,
website details and first messages below are synthetic and never staged or sent.
No real contact content, emails, lead IDs or rendered copy is returned.
"""
from __future__ import annotations

import re

from instantly_campaign_copy import TARGET_CAMPAIGNS, campaign_copy_matches

VARIABLE = re.compile(r"\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*\}\}")
PERMITTED = frozenset({
    "leadscanner_subject", "leadscanner_body",
    "leadscanner_observation", "leadscanner_value_action",
})
UNRESOLVED = re.compile(r"\{\{|\}\}|\{%|%\}")


def render_synthetic(text: str, variables: dict[str, str]) -> str:
    """Substitute an allowlisted subset without evaluating arbitrary Liquid."""
    if not isinstance(text, str):
        raise ValueError("synthetic_preview_template_invalid")
    if "{%" in text or "%}" in text:
        raise ValueError("synthetic_preview_liquid_not_supported")
    fields = set(VARIABLE.findall(text))
    if fields - PERMITTED:
        raise ValueError("synthetic_preview_unexpected_merge_variable")
    if any(
        not isinstance(variables.get(key), str) or not variables[key].strip()
        for key in fields
    ):
        raise ValueError("synthetic_preview_required_fact_missing")
    rendered = VARIABLE.sub(lambda match: variables[match.group(1)], text)
    if UNRESOLVED.search(rendered):
        raise ValueError("synthetic_preview_unresolved_or_unescaped_input")
    return rendered


def _profiles(language: str) -> list[dict[str, str]]:
    if language == "nl":
        observations = (
            ("Klanten kunnen via het fietsafspraakformulier onderhoud aanvragen.",
             "een korte schets voor de fietsafspraakroute"),
            ("Gasten kunnen via het reserveringsformulier een tafel kiezen.",
             "een korte schets voor de reserveringsroute"),
        )
        prefix = "Hoi, op jullie website zag ik: "
        question = "Zal ik een voorbeeld toesturen?"
        closing = "\n\nGeen interesse? Antwoord met nee; dan stop ik.\n\nGroet,\nAndrew Baeten"
        subjects = ("vraag over een fietsafspraak", "vraag over reserveren")
    elif language == "en":
        observations = (
            ("Customers can request bike repairs via the booking form.",
             "a short sketch of the bike appointment flow"),
            ("Guests can reserve a table through the reservation form.",
             "a short sketch of the reservation flow"),
        )
        prefix = "Hi, I noticed on your website: "
        question = "Would you like a short example?"
        closing = "\n\nNot interested? Reply no and I will stop.\n\nBest,\nAndrew Baeten"
        subjects = ("question about bike appointments", "question about reservations")
    else:
        raise ValueError("synthetic_preview_language_invalid")
    return [
        {
            "leadscanner_subject": subjects[i],
            "leadscanner_body": prefix + observation + "\n\n" + question + closing,
            "leadscanner_observation": observation,
            "leadscanner_value_action": action,
        }
        for i, (observation, action) in enumerate(observations)
    ]


def audit_synthetic_campaign_previews(client) -> dict:
    """Check 12 synthetic renderings of six live campaign steps, no lead writes."""
    reports = []
    for language in ("nl", "en"):
        campaign_id, name = TARGET_CAMPAIGNS[language]
        campaign = client.get_campaign(campaign_id)
        if (
            not isinstance(campaign, dict)
            or campaign.get("id") != campaign_id
            or campaign.get("name") != name
            or type(campaign.get("status")) is not int
            or campaign["status"] != 2
            or campaign.get("email_list") != []
            or not campaign_copy_matches(campaign, language)
        ):
            raise RuntimeError("synthetic_preview_requires_exact_paused_campaign")
        leads = client.list_leads(campaign=campaign_id, limit=100)
        if (not isinstance(leads, dict)
            or leads.get("items") != []
            or leads.get("next_starting_after")):
            raise RuntimeError("synthetic_preview_requires_empty_campaign")
        steps = campaign["sequences"][0]["steps"]
        rendered_per_profile = []
        for profile in _profiles(language):
            messages = [
                {
                    "subject": render_synthetic(step["variants"][0]["subject"], profile),
                    "body": render_synthetic(step["variants"][0]["body"], profile),
                }
                for step in steps
            ]
            if len(messages) != 3 or messages[0]["subject"] != profile["leadscanner_subject"]:
                raise RuntimeError("synthetic_preview_step_count_or_subject_invalid")
            if messages[0]["body"] != profile["leadscanner_body"]:
                raise RuntimeError("synthetic_preview_first_mail_mismatch")
            for index in (1, 2):
                if profile["leadscanner_observation"] not in messages[index]["body"]:
                    raise RuntimeError("synthetic_preview_observation_missing")
            if profile["leadscanner_value_action"] not in messages[1]["body"]:
                raise RuntimeError("synthetic_preview_proposal_missing")
            if messages[1]["body"].count("?") != 1 or messages[2]["body"].count("?") != 0:
                raise RuntimeError("synthetic_preview_followup_cta_invalid")
            if any(
                "andrew baeten" not in message["body"].casefold()
                or "webactueel" in message["body"].casefold()
                or UNRESOLVED.search(message["body"])
                for message in messages
            ):
                raise RuntimeError("synthetic_preview_signature_or_merge_invalid")
            rendered_per_profile.append(messages)
        if any(
            rendered_per_profile[0][index]["body"] == rendered_per_profile[1][index]["body"]
            for index in (0, 1, 2)
        ):
            raise RuntimeError("synthetic_preview_cross_recipient_nonpersonalized")
        reports.append({
            "language": language,
            "campaign_id": campaign_id,
            "synthetic_profiles_checked": 2,
            "live_steps_checked": 3,
            "rendered_email_bodies_checked": 6,
            "exact_provider_copy": True,
            "cross_profile_contamination_detected": False,
            "unresolved_merge_variables": 0,
            "provider_ui_preview_performed": False,
            "real_contacts_staged": 0,
            "senders_assigned": 0,
        })
    return {
        "schema_version": "leadscanner-synthetic-live-sequence-audit/1.0",
        "campaigns": reports,
        "synthetic_profiles_checked": 4,
        "rendered_email_bodies_checked": 12,
        "all_checks_passed": True,
        "provider_ui_preview_performed": False,
        "preview_is_simulated_not_provider_render": True,
        "real_contact_data_used": False,
        "contains_recipient_or_message_text": False,
        "writes": False,
        "sends": False,
    }
