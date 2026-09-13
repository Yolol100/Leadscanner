from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from prospect_discovery import ParsedPage
from outreach_agent_prepare_v16 import COPY_CONTRACT, _copy_with_value, qualification_evidence_ok
from outreach_site_personalization_v16 import build_personalization


class OutreachV16CopyContractTests(unittest.TestCase):
    def test_phone_skip_and_team_labels_do_not_become_anchor(self):
        page = ParsedPage(
            title="AA Schroefpalen | Fundering met schroefpalen",
            links=[
                ("https://aa.example/offerte", "Offerte aanvragen"),
                ("tel:+31243782888", "024 378 2888"),
                ("https://aa.example/#main", "Skip to content"),
                ("https://aa.example/team", "Ons team"),
            ],
        )
        result = build_personalization(
            page,
            company="AA Schroefpalen",
            agent_type="quote_intake",
            language="nl",
            evidence_url="https://aa.example/",
        )
        self.assertNotIn(result.anchor.casefold(), {"024 378 2888", "skip to content", "ons team"})
        self.assertIn("schroefpalen", result.anchor.casefold())

    def test_v16_copy_is_signal_first_and_short(self):
        with patch.dict(os.environ, {"OUTREACH_CTA_VARIANT": "A", "OUTREACH_SENDER_WEBSITE": "andrewbaeten.nl"}, clear=False):
            subject, body, followup_subject, followup, delay = _copy_with_value(
                company="Voorbeeld Dak",
                country="NL",
                fact='Ik zag op jullie site "Dakrenovatie" naast de route "Offerte aanvragen".',
                value="een kort voorbeeld kan daar eerst ontbrekende aanvraaggegevens uitvragen voordat jullie team de offerte of intake beoordeelt",
                agent_type="quote_intake",
            )
        self.assertEqual(subject, "Offerte aanvragen")
        self.assertTrue(body.startswith("Beste team,"))
        self.assertNotIn("Ik bouw kleine workflows", body)
        self.assertIn("zou dat bijvoorbeeld kunnen betekenen:", body)
        self.assertIn("Zal ik een kort voorbeeld sturen", body)
        self.assertEqual(followup_subject, "")
        self.assertIn("Ik kom hier nog één keer op terug", followup)
        self.assertEqual(delay, 4)
        self.assertLessEqual(len(body.split()), 100)
        self.assertEqual(COPY_CONTRACT, "evidence_personalized_v16")

    def test_low_score_with_real_process_evidence_is_eligible(self):
        candidate = {
            "candidate_id": "lead-1",
            "reason": "customer_potential=5; evidence=contact",
        }
        qualification = {
            "candidate_id": "lead-1",
            "offer_family": "ai_agent",
            "agent_type": "front_desk_sales",
            "agent_opportunity_score": "2",
            "evidence_url": "https://example.nl/contact",
            "fact": "De website stuurt bezoekers naar contact.",
            "idea": "Vang eerste vragen op.",
            "business_process": "new_enquiry_to_qualified_handoff",
            "tier": "C",
            "customer_potential": "5",
            "status": "rejected",
            "reason": "customer_potential=5; agent_opportunity=2; evidence=contact",
        }
        self.assertTrue(qualification_evidence_ok(candidate, qualification, agent_type="front_desk_sales"))

    def test_missing_process_evidence_still_fails_closed(self):
        candidate = {"candidate_id": "lead-2", "reason": ""}
        qualification = {
            "candidate_id": "lead-2",
            "offer_family": "ai_agent",
            "agent_type": "quote_intake",
            "agent_opportunity_score": "0",
            "evidence_url": "https://example.nl/",
            "fact": "",
            "idea": "",
            "business_process": "",
            "reason": "agent_type=none",
        }
        self.assertFalse(qualification_evidence_ok(candidate, qualification, agent_type="quote_intake"))


if __name__ == "__main__":
    unittest.main()
