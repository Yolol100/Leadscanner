from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from outreach_agent_prepare_v2 import build_copy, build_prepared_row
from outreach_copy_preflight import followup_copy_errors, initial_copy_errors


class OutreachAgentPrepareV2Tests(unittest.TestCase):
    def test_nl_human_copy_has_process_subject_no_url_no_ai_pitch(self):
        with patch.dict(os.environ, {"OUTREACH_CTA_VARIANT": "A"}, clear=False):
            subject, body, followup_subject, followup_body, delay = build_copy(
                company="Voorbeeld Tandarts",
                country="NL",
                fact="Op jullie website kunnen bezoekers direct een afspraak maken.",
                idea="legacy AI-labelled value text",
                agent_type="front_desk_sales",
            )
        self.assertEqual(subject, "Afspraken bij Voorbeeld Tandarts")
        self.assertNotIn("AI", subject)
        self.assertNotIn("http", body)
        self.assertNotIn("bounded", body.lower())
        self.assertNotIn("human handoff", body.lower())
        self.assertNotIn("AI-ondersteunde", body)
        self.assertIn("Ik bouw kleine workflows", body)
        self.assertIn("Zal ik een kort voorbeeld sturen", body)
        self.assertIn("Dit is een commercieel bericht.", body)
        self.assertTrue(body.endswith("Andrew Baeten\nandrewbaeten.nl"))
        self.assertEqual(initial_copy_errors(subject, body), [])
        self.assertEqual(followup_copy_errors(followup_body), [])
        self.assertEqual(followup_subject, "")
        self.assertEqual(delay, 4)

    def test_en_quote_copy_is_human_and_us_footer_is_at_signature(self):
        with patch.dict(os.environ, {"OUTREACH_CTA_VARIANT": "A", "OUTREACH_SENDER_WEBSITE": "andrewbaeten.nl"}, clear=False):
            subject, body, _, followup, _ = build_copy(
                company="Example Roofing",
                country="US",
                fact="Your website lets customers request a quote and pricing.",
                idea="An AI Quote & Intake Agent can collect complete request details.",
                agent_type="quote_intake",
                postal_address="private-config-present",
            )
        self.assertEqual(subject, "Quote requests at Example Roofing")
        self.assertIn("customers answer a few focused questions", body)
        self.assertNotIn("AI Quote & Intake Agent", body)
        self.assertNotIn("AI-assisted", body)
        self.assertNotIn("bounded digital agents", body)
        self.assertIn("This is a commercial message.", body)
        self.assertIn("Best regards,\nAndrew Baeten\n{{OUTREACH_POSTAL_ADDRESS}}\nandrewbaeten.nl", body)
        self.assertLess(body.index("This is a commercial message."), body.index("Best regards,"))
        self.assertEqual(initial_copy_errors(subject, body), [])
        self.assertEqual(followup_copy_errors(followup), [])

    def test_cta_b_changes_only_permission_wording(self):
        common = dict(
            company="Voorbeeld Tandarts",
            country="NL",
            fact="Op jullie website kunnen bezoekers direct een afspraak maken.",
            idea="legacy value",
            agent_type="front_desk_sales",
        )
        with patch.dict(os.environ, {"OUTREACH_CTA_VARIANT": "A"}, clear=False):
            a = build_copy(**common)
        with patch.dict(os.environ, {"OUTREACH_CTA_VARIANT": "B"}, clear=False):
            b = build_copy(**common)
        self.assertEqual(a[0], b[0])
        self.assertIn("Zal ik een kort voorbeeld sturen", a[1])
        self.assertIn("Zal ik dat korte voorbeeld", b[1])

    def _ready(self):
        candidate = {
            "candidate_id": "1",
            "company": "Voorbeeld Tandarts",
            "website": "https://voorbeeld.nl/",
            "country": "NL",
            "status": "qualified",
        }
        qualification = {
            "tier": "A",
            "status": "qualified",
            "customer_potential": "8",
            "evidence_url": "https://voorbeeld.nl/afspraak/",
            "offer_family": "ai_agent",
            "agent_type": "front_desk_sales",
            "business_process": "new_lead_to_qualified_appointment",
            "kpi_candidate": "qualified_conversation_to_appointment",
            "integration_hint": "phone/chat + calendar + CRM",
            "fact": "Op jullie website kunnen bezoekers direct een afspraak maken.",
            "idea": "Een AI Front Desk & Sales Agent kan eerste vragen beantwoorden.",
        }
        contact = {"checked_at": "2026-09-08T15:00:00Z", "email": "info@voorbeeld.nl", "status": "ready"}
        return candidate, qualification, contact

    @staticmethod
    def _personalization():
        return SimpleNamespace(
            observation='Ik zag "Sportfysiotherapie" naast de route "Afspraak maken" op je site.',
            value='Rond "Sportfysiotherapie" kan een kort voorbeeld eerst de relevante vraag en gegevens opvangen en daarna aansluiten op je bestaande afspraak- of teamroute',
            evidence_url="https://voorbeeld.nl/afspraak/",
            anchor="Sportfysiotherapie",
            process_label="Afspraak maken",
        )

    def test_payload_contains_evidence_personalization_and_campaign_target(self):
        candidate, qualification, contact = self._ready()
        with patch.dict(os.environ, {"AGENT_SALES_TARGET_TYPE": "front_desk_sales", "OUTREACH_CTA_VARIANT": "A"}, clear=False), patch(
            "outreach_agent_prepare_v2.personalize_from_evidence", return_value=self._personalization()
        ):
            row = build_prepared_row(candidate, qualification, contact)
        meta = json.loads(row["source"].split(":", 1)[1])
        self.assertEqual(meta["campaign_target_agent_type"], "front_desk_sales")
        self.assertEqual(meta["value_asset_type"], "process_flow")
        self.assertEqual(meta["value_asset_status"], "concept_ready")
        self.assertEqual(meta["personalization_anchor"], "Sportfysiotherapie")
        self.assertEqual(meta["personalization_process_label"], "Afspraak maken")
        self.assertEqual(meta["fact"], self._personalization().observation)
        self.assertEqual(meta["value_asset_summary"], self._personalization().value)
        self.assertEqual(meta["cta_variant"], "A")
        self.assertEqual(meta["copy_contract"], "evidence_personalized_v13_5")
        self.assertIn("Sportfysiotherapie", row["body"])
        self.assertNotIn("AI Front Desk", row["body"])

    def test_prepare_blocks_campaign_mismatch_before_personalization(self):
        candidate, qualification, contact = self._ready()
        with patch.dict(os.environ, {"AGENT_SALES_TARGET_TYPE": "commerce", "OUTREACH_CTA_VARIANT": "A"}, clear=False):
            with self.assertRaises(ValueError):
                build_prepared_row(candidate, qualification, contact)

    def test_prepare_blocks_reactivation_without_first_party_personalization_contract(self):
        candidate, qualification, contact = self._ready()
        qualification["agent_type"] = "lead_reactivation"
        with patch.dict(os.environ, {"AGENT_SALES_TARGET_TYPE": "lead_reactivation", "OUTREACH_CTA_VARIANT": "A"}, clear=False):
            with self.assertRaisesRegex(ValueError, "first-party"):
                build_prepared_row(candidate, qualification, contact)


if __name__ == "__main__":
    unittest.main()
