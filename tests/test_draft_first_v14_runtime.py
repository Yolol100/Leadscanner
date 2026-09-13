from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import outreach_daily_draft_first as daily
import outreach_daily_draft_first_retry as daily_retry
import outreach_draft_first_prepare as prepare
import outreach_draft_first_prepare_retry as prepare_retry


class DraftFirstV14RuntimeRegressionTests(unittest.TestCase):
    def test_delayed_readback_never_causes_second_write(self):
        row = {"lead_id": "lead-1", "email": "info@example.com"}
        calls = {"append": 0}

        def append_once(*args, **kwargs):
            calls["append"] += 1

        with patch.object(prepare_retry, "_readback_count", side_effect=[0, 0, 1]), \
             patch.object(prepare_retry, "_append_once", side_effect=append_once), \
             patch.object(prepare_retry.time, "sleep", return_value=None):
            prepare_retry.append_row_retry(object(), "sheet", prepare.QUEUE_SHEET, ["lead_id", "email"], row)
        self.assertEqual(1, calls["append"])

    def test_ambiguous_transport_without_readback_refuses_duplicate_write(self):
        row = {"lead_id": "lead-1", "email": "info@example.com"}
        calls = {"append": 0}

        def ambiguous(*args, **kwargs):
            calls["append"] += 1
            raise OSError("SSL EOF")

        with patch.object(prepare_retry, "_readback_count", return_value=0), \
             patch.object(prepare_retry, "_append_once", side_effect=ambiguous), \
             patch.object(prepare_retry.time, "sleep", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "refusing duplicate write"):
                prepare_retry.append_row_retry(object(), "sheet", prepare.QUEUE_SHEET, ["lead_id", "email"], row)
        self.assertEqual(1, calls["append"])

    def test_runtime_uses_explicit_update_not_logical_table_append(self):
        source = Path("scripts/outreach_draft_first_prepare_retry.py").read_text(encoding="utf-8")
        self.assertIn("values().update(", source)
        self.assertNotIn("values().append(", source)
        self.assertIn("target row", source)
        self.assertNotIn('range=f"\'{sheet}\'!A:ZZ"', source)

    def test_explicit_write_targets_first_row_after_schema_data(self):
        headers = ["lead_id", "email"]
        row = {"lead_id": "lead-2", "email": "two@example.com"}
        service = MagicMock()
        values_api = service.spreadsheets.return_value.values.return_value
        values_api.get.return_value.execute.side_effect = [
            {"values": [["lead_id", "email"], ["lead-1", "one@example.com"], [], ["lead-old", "old@example.com"]]},
            {"values": []},
        ]
        values_api.update.return_value.execute.return_value = {"updatedRange": "OutreachQueue!A5:B5"}

        prepare_retry._append_once(service, "sheet", prepare.QUEUE_SHEET, headers, row)

        kwargs = values_api.update.call_args.kwargs
        self.assertEqual("'OutreachQueue'!A5:B5", kwargs["range"])
        self.assertEqual([["lead-2", "two@example.com"]], kwargs["body"]["values"])
        values_api.append.assert_not_called()

    def test_explicit_write_refuses_occupied_target_row(self):
        headers = ["lead_id", "email"]
        row = {"lead_id": "lead-2", "email": "two@example.com"}
        service = MagicMock()
        values_api = service.spreadsheets.return_value.values.return_value
        values_api.get.return_value.execute.side_effect = [
            {"values": [["lead_id", "email"], ["lead-1", "one@example.com"]]},
            {"values": [["other", "other@example.com"]]},
        ]

        with self.assertRaisesRegex(RuntimeError, "no longer empty"):
            prepare_retry._append_once(service, "sheet", prepare.QUEUE_SHEET, headers, row)
        values_api.update.assert_not_called()
        values_api.append.assert_not_called()

    def test_prepare_mx_missing_is_hard_block_for_explicit_production_run(self):
        candidate = {"candidate_id": "c1", "status": "hold", "country": "US", "website": "https://example.com"}
        qualification = {
            "offer_family": "ai_agent", "agent_type": "quote_intake", "tier": "B",
            "status": "hold", "customer_potential": "6",
        }
        contact = {
            "status": "manual_review", "email": "company@gmail.com", "source_url": "https://example.com/contact",
            "mx_status": "missing", "domain_alignment": "external",
        }
        with patch.object(prepare_retry, "_original_candidate_ok", side_effect=lambda c, q, ct, *, country: ct["mx_status"] != "missing"):
            self.assertFalse(prepare_retry.candidate_ok_draft_first(candidate, qualification, contact, country="US"))

    def test_daily_retry_does_not_normalise_missing_mx(self):
        source = Path("scripts/outreach_daily_draft_first_retry.py").read_text(encoding="utf-8")
        self.assertNotIn("_normalise_draft_mx", source)
        self.assertNotIn('meta["contact_mx_status"] = "unknown"', source)

    def test_verified_qualification_evidence_is_reused_on_official_domain(self):
        candidate = {"website": "https://example.com/"}
        q = {
            "agent_type": "quote_intake",
            "evidence_url": "https://www.example.com/request-a-quote/",
            "fact": "Example invites visitors to request a quote on its website.",
            "idea": "A quote-intake agent could structure those requests before handoff.",
            "business_process": "request_to_complete_intake",
        }
        result = prepare.verified_qualification_personalization(candidate, q)
        self.assertIsNotNone(result)
        self.assertEqual("verified_qualification_evidence", result["personalization_mode"])
        self.assertEqual("quote or intake request", result["anchor"])
        self.assertEqual(q["evidence_url"], result["evidence_url"])

    def test_verified_qualification_evidence_rejects_cross_domain_provenance(self):
        candidate = {"website": "https://example.com/"}
        q = {
            "agent_type": "quote_intake",
            "evidence_url": "https://unrelated.example.net/request-a-quote/",
            "fact": "A quote request exists.",
            "idea": "Automate intake.",
            "business_process": "request_to_complete_intake",
        }
        self.assertIsNone(prepare.verified_qualification_personalization(candidate, q))

    def test_generic_navigation_personalization_is_rejected(self):
        meta = {
            "personalization_anchor": "Skip to content",
            "observation": "Skip to content",
            "value_asset_summary": "A useful workflow.",
            "evidence_url": "https://example.com/",
        }
        ok, reason = daily.meaningful_personalization(meta, "https://example.com/")
        self.assertFalse(ok)
        self.assertIn("generic navigation", reason)

    def test_verified_business_process_personalization_is_accepted(self):
        meta = {
            "personalization_anchor": "quote or intake request",
            "observation": "Example invites visitors to request a quote on its website.",
            "value_asset_summary": "A quote-intake agent could structure those requests before handoff.",
            "evidence_url": "https://example.com/request-a-quote/",
        }
        ok, reason = daily.meaningful_personalization(meta, "https://www.example.com/")
        self.assertTrue(ok, reason)

    def test_workflow_counts_with_retry_wrapper_and_avoids_forced_recheck(self):
        workflow = Path(".github/workflows/daily-agent-drafts-v14.yml").read_text(encoding="utf-8")
        self.assertGreaterEqual(workflow.count("outreach_daily_draft_first_retry.py --count-only"), 3)
        self.assertNotIn("PROSPECT_QUALIFICATION_FORCE_RECHECK=true", workflow)
        self.assertLess(workflow.index("prepare-stock-$cycle.log"), workflow.index("prospect_discovery_retry_runtime.py"))
        self.assertIn("group: daily-draft-first-agent-leads", workflow)
        self.assertIn("cancel-in-progress: true", workflow)


if __name__ == "__main__":
    unittest.main()
