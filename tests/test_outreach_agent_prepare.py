from __future__ import annotations

import json
import unittest

from outreach_agent_prepare import AUTOMATION_ID, _agent_row, _prepare_eligible, build_copy, build_prepared_row
from outreach_copy_preflight import followup_copy_errors, initial_copy_errors


class OutreachAgentPrepareTests(unittest.TestCase):
    def test_dutch_agent_copy_matches_existing_copy_guardrails_without_website_price(self):
        subject, body, followup_subject, followup_body, delay = build_copy(
            company="Voorbeeld Tandarts",
            country="NL",
            fact="De website van Voorbeeld Tandarts biedt bezoekers een afspraak- of boekingsroute.",
            idea="Een AI Front Desk & Sales Agent kan voor Voorbeeld Tandarts eerste vragen beantwoorden, relevante gegevens verzamelen, leads kwalificeren en een afspraak of menselijke overdracht voorbereiden.",
            agent_type="front_desk_sales",
        )
        self.assertEqual(initial_copy_errors(subject, body), [])
        self.assertEqual(followup_copy_errors(followup_body), [])
        self.assertEqual(followup_subject, "")
        self.assertEqual(delay, 4)
        self.assertIn("AI Front Desk & Sales Agent", body)
        self.assertNotIn("€500", body)
        self.assertNotIn("€750", body)

    def test_us_agent_copy_keeps_commercial_label_and_postal_address(self):
        address = "Example Business, 1 Test Street, New York, NY 10001, USA"
        _, body, _, followup_body, _ = build_copy(
            company="Example Clinic",
            country="US",
            fact="The website of Example Clinic gives visitors an appointment or booking path.",
            idea="An AI Front Desk & Sales Agent can answer first questions for Example Clinic, collect relevant details, qualify the lead and prepare an appointment or human handoff.",
            agent_type="front_desk_sales",
            postal_address=address,
        )
        self.assertIn("commercial message", body.lower())
        self.assertIn(address, body)
        self.assertEqual(followup_copy_errors(followup_body), [])

    def _ready_inputs(self):
        candidate = {
            "candidate_id": "prospect-1", "company": "Voorbeeld Tandarts",
            "website": "https://voorbeeld.nl/", "country": "NL", "status": "qualified",
        }
        qualification = {
            "tier": "A", "status": "qualified", "customer_potential": "8",
            "evidence_url": "https://voorbeeld.nl/", "offer_family": "ai_agent",
            "agent_type": "front_desk_sales", "business_process": "new_lead_to_qualified_appointment",
            "kpi_candidate": "qualified_conversation_to_appointment", "integration_hint": "phone/chat + calendar + CRM",
            "fact": "De website van Voorbeeld Tandarts biedt bezoekers een afspraak- of boekingsroute.",
            "idea": "Een AI Front Desk & Sales Agent kan voor Voorbeeld Tandarts eerste vragen beantwoorden, relevante gegevens verzamelen, leads kwalificeren en een afspraak of menselijke overdracht voorbereiden.",
        }
        contact = {"checked_at": "2026-09-08T15:00:00Z", "email": "info@voorbeeld.nl", "status": "ready"}
        return candidate, qualification, contact

    def test_agent_prepared_row_never_auto_approves_or_sends(self):
        candidate, qualification, contact = self._ready_inputs()
        row = build_prepared_row(candidate, qualification, contact)
        self.assertEqual(row["status"], "prepared")
        self.assertEqual(row["compliance_status"], "manual_review")
        self.assertEqual(row["compliance_basis"], "")
        self.assertTrue(row["source"].startswith("agent_offer:"))
        metadata = json.loads(row["source"].split(":", 1)[1])
        self.assertEqual(metadata["automation"], AUTOMATION_ID)
        self.assertEqual(metadata["agent_type"], "front_desk_sales")
        self.assertTrue(_agent_row(row))

    def test_prepare_eligibility_requires_agent_offer_and_ready_contact(self):
        candidate, qualification, contact = self._ready_inputs()
        self.assertTrue(_prepare_eligible(candidate, qualification, contact))
        qualification["offer_family"] = "website"
        self.assertFalse(_prepare_eligible(candidate, qualification, contact))


if __name__ == "__main__":
    unittest.main()