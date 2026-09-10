from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

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

    def test_append_runtime_is_schema_bounded_and_not_insert_rows(self):
        source = Path("scripts/outreach_draft_first_prepare_retry.py").read_text(encoding="utf-8")
        self.assertIn("A:{last_col}", source)
        self.assertIn('insertDataOption="OVERWRITE"', source)
        self.assertNotIn('range=f"\'{sheet}\'!A:ZZ"', source)

    def test_prepare_mx_missing_is_review_evidence_not_hard_block(self):
        candidate = {"candidate_id": "c1", "status": "hold", "country": "US", "website": "https://example.com"}
        qualification = {
            "offer_family": "ai_agent", "agent_type": "quote_intake", "tier": "B",
            "status": "hold", "customer_potential": "6",
        }
        contact = {
            "status": "manual_review", "email": "company@gmail.com", "source_url": "https://example.com/contact",
            "mx_status": "missing", "domain_alignment": "external",
        }
        with patch.object(prepare_retry, "_original_candidate_ok", side_effect=lambda c, q, ct, *, country: ct["mx_status"] == "unknown"):
            self.assertTrue(prepare_retry.candidate_ok_draft_first(candidate, qualification, contact, country="US"))

    def test_daily_mx_missing_normalises_only_runtime_evidence(self):
        meta = {
            "automation": "agent_sales_draft_first_v14",
            "copy_contract": "draft_first_v14",
            "contact_mx_status": "missing",
        }
        row = {"lead_id": "lead-1", "source": "agent_offer:" + json.dumps(meta)}
        out = daily_retry._normalise_draft_mx(copy.deepcopy(row))
        parsed = json.loads(out["source"].split(":", 1)[1])
        self.assertEqual("unknown", parsed["contact_mx_status"])
        self.assertEqual(row["lead_id"], out["lead_id"])

    def test_workflow_counts_with_retry_wrapper_and_avoids_forced_recheck(self):
        workflow = Path(".github/workflows/daily-agent-drafts-v14.yml").read_text(encoding="utf-8")
        self.assertGreaterEqual(workflow.count("outreach_daily_draft_first_retry.py --count-only"), 3)
        self.assertNotIn("PROSPECT_QUALIFICATION_FORCE_RECHECK=true", workflow)
        self.assertLess(workflow.index("prepare-stock-$cycle.log"), workflow.index("prospect_discovery_retry_runtime.py"))


if __name__ == "__main__":
    unittest.main()
