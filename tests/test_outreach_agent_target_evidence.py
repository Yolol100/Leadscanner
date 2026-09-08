from __future__ import annotations

import json
import unittest

import outreach_target_evidence_preflight as p


FACT = "The website of Example Clinic gives visitors an appointment or booking path."
IDEA = "An AI Front Desk & Sales Agent can answer first questions for Example Clinic, collect relevant details, qualify the lead and prepare an appointment or human handoff."
ADDRESS = "Example Business, 1 Test Street, New York, NY 10001, USA"


def agent_source(**overrides):
    payload = {
        "offer_family": "ai_agent",
        "agent_type": "front_desk_sales",
        "business_process": "new_lead_to_qualified_appointment",
        "kpi_candidate": "qualified_conversation_to_appointment",
        "integration_hint": "phone/chat + calendar + CRM",
        "evidence_url": "https://example.com/",
        "fact": FACT,
        "idea": IDEA,
    }
    payload.update(overrides)
    return "agent_offer:" + json.dumps(payload, separators=(",", ":"))


def row(**overrides):
    base = {
        "company": "Example Clinic Inc",
        "website": "https://example.com/",
        "country": "US",
        "source": agent_source(),
        "body": (
            f"Hi Example Clinic team,\n\n{FACT}\n\nOne idea: {IDEA}\n\n"
            f"This is a commercial message.\n{p.POSTAL_PLACEHOLDER}\n\n"
            "Not interested? A quick no is enough.\n\nBest regards,\nAndrew Baeten"
        ),
        "status": "approved",
    }
    base.update(overrides)
    return base


class AgentTargetEvidenceTests(unittest.TestCase):
    def test_agent_offer_is_accepted_by_live_metadata_gate(self):
        self.assertEqual(p.metadata_errors(row(), postal_address=ADDRESS), [])

    def test_unknown_agent_type_is_blocked(self):
        errors = p.metadata_errors(row(source=agent_source(agent_type="general_ai_employee")), postal_address=ADDRESS)
        self.assertTrue(any("six approved" in error for error in errors))

    def test_agent_fact_and_idea_must_be_exactly_present(self):
        errors = p.metadata_errors(row(body=row()["body"].replace(FACT, "Generic praise.")), postal_address=ADDRESS)
        self.assertTrue(any("exact agent_offer fact" in error for error in errors))

    def test_legacy_website_scan_prefix_remains_supported(self):
        legacy = {
            "evidence_url": "https://example.com/",
            "fact": FACT,
            "idea": IDEA,
            "analysis_type": "website",
        }
        parsed = p.parse_evidence_source("website_scan:" + json.dumps(legacy))
        self.assertEqual(parsed["_evidence_kind"], "website_scan")


if __name__ == "__main__":
    unittest.main()