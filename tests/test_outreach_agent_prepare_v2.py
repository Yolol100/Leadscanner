from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from outreach_agent_prepare_v2 import build_copy, build_prepared_row
from outreach_copy_preflight import initial_copy_errors, followup_copy_errors


class OutreachAgentPrepareV2Tests(unittest.TestCase):
    def test_nl_value_flow_copy_has_process_subject_no_url_no_ai_subject(self):
        with patch.dict(os.environ, {"OUTREACH_CTA_VARIANT": "A"}, clear=False):
            subject, body, followup_subject, followup_body, delay = build_copy(
                company="Voorbeeld Tandarts",
                country="NL",
                fact="De website van Voorbeeld Tandarts biedt bezoekers een afspraak- of boekingsroute.",
                idea="eerste vragen opvangen, kwalificatiepunten uitvragen en daarna een afspraak of menselijke overdracht voorbereiden.",
                agent_type="front_desk_sales",
            )
        self.assertEqual(subject, "Afspraken bij Voorbeeld Tandarts")
        self.assertNotIn("AI", subject)
        self.assertNotIn("http", body)
        self.assertIn("voorbeeldflow", body)
        self.assertEqual(initial_copy_errors(subject, body), [])
        self.assertEqual(followup_copy_errors(followup_body), [])
        self.assertEqual(followup_subject, "")
        self.assertEqual(delay, 4)

    def test_cta_b_changes_only_permission_wording(self):
        common = dict(
            company="Voorbeeld Tandarts",
            country="NL",
            fact="De website van Voorbeeld Tandarts biedt bezoekers een afspraak- of boekingsroute.",
            idea="eerste vragen opvangen, kwalificatiepunten uitvragen en daarna een afspraak of menselijke overdracht voorbereiden.",
            agent_type="front_desk_sales",
        )
        with patch.dict(os.environ, {"OUTREACH_CTA_VARIANT": "A"}, clear=False):
            a = build_copy(**common)
        with patch.dict(os.environ, {"OUTREACH_CTA_VARIANT": "B"}, clear=False):
            b = build_copy(**common)
        self.assertEqual(a[0], b[0])
        self.assertIn("Zal ik", a[1])
        self.assertIn("Mag ik", b[1])

    def _ready(self):
        candidate = {"candidate_id": "1", "company": "Voorbeeld Tandarts", "website": "https://voorbeeld.nl/", "country": "NL", "status": "qualified"}
        qualification = {
            "tier": "A", "status": "qualified", "customer_potential": "8", "evidence_url": "https://voorbeeld.nl/",
            "offer_family": "ai_agent", "agent_type": "front_desk_sales", "business_process": "new_lead_to_qualified_appointment",
            "kpi_candidate": "qualified_conversation_to_appointment", "integration_hint": "phone/chat + calendar + CRM",
            "fact": "De website van Voorbeeld Tandarts biedt bezoekers een afspraak- of boekingsroute.",
            "idea": "eerste vragen opvangen, kwalificatiepunten uitvragen en daarna een afspraak of menselijke overdracht voorbereiden.",
        }
        contact = {"checked_at": "2026-09-08T15:00:00Z", "email": "info@voorbeeld.nl", "status": "ready"}
        return candidate, qualification, contact

    def test_payload_contains_concept_ready_value_asset_and_campaign_target(self):
        candidate, qualification, contact = self._ready()
        with patch.dict(os.environ, {"AGENT_SALES_TARGET_TYPE": "front_desk_sales", "OUTREACH_CTA_VARIANT": "A"}, clear=False):
            row = build_prepared_row(candidate, qualification, contact)
        meta = json.loads(row["source"].split(":", 1)[1])
        self.assertEqual(meta["campaign_target_agent_type"], "front_desk_sales")
        self.assertEqual(meta["value_asset_type"], "process_flow")
        self.assertEqual(meta["value_asset_status"], "concept_ready")
        self.assertEqual(meta["value_asset_summary"], qualification["idea"])
        self.assertEqual(meta["cta_variant"], "A")

    def test_prepare_blocks_campaign_mismatch(self):
        candidate, qualification, contact = self._ready()
        with patch.dict(os.environ, {"AGENT_SALES_TARGET_TYPE": "commerce", "OUTREACH_CTA_VARIANT": "A"}, clear=False):
            with self.assertRaises(ValueError):
                build_prepared_row(candidate, qualification, contact)


if __name__ == "__main__":
    unittest.main()