from __future__ import annotations

import copy
import json
import py_compile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import outreach_daily_draft_first as daily
import outreach_daily_draft_first_retry as daily_retry
import outreach_draft_first_prepare as prepare
import outreach_draft_first_prepare_retry as prepare_retry
import prospect_agent_qualification_draft_first as qualification
import prospect_discovery_retry_runtime as discovery_retry


class DraftFirstV14Tests(unittest.TestCase):
    def test_v14_scripts_compile(self):
        paths = [
            "scripts/prospect_discovery_retry_runtime.py",
            "scripts/prospect_agent_qualification_draft_first.py",
            "scripts/prospect_contact_enrichment_draft_first.py",
            "scripts/outreach_draft_first_prepare.py",
            "scripts/outreach_draft_first_prepare_retry.py",
            "scripts/outreach_daily_draft_first.py",
            "scripts/outreach_daily_draft_first_retry.py",
        ]
        for path in paths:
            py_compile.compile(path, doraise=True)

    def test_auto_agent_selects_strongest_and_deterministic_tie(self):
        fit = qualification.classify_agent_context_draft_first("request a quote and checkout")
        self.assertEqual("quote_intake", fit.agent_type)
        self.assertEqual(3, fit.score)
        self.assertEqual("commerce", qualification.classify_agent_context_draft_first("checkout cart buy now").agent_type)
        self.assertEqual("customer_support", qualification.classify_agent_context_draft_first("FAQ customer support returns").agent_type)
        self.assertEqual("front_desk_sales", qualification.classify_agent_context_draft_first("book appointment online").agent_type)
        self.assertEqual("review_concierge", qualification.classify_agent_context_draft_first("customer reviews testimonials").agent_type)
        self.assertEqual("", qualification.classify_agent_context_draft_first("newsletter returning customers").agent_type)

    def test_a_and_b_are_draft_eligible_but_c_and_reactivation_are_not(self):
        base = {
            "offer_family": "ai_agent",
            "agent_type": "quote_intake",
            "tier": "B",
            "status": "hold",
            "customer_potential": "6",
        }
        self.assertTrue(prepare.qualification_ok(base))
        a = dict(base, tier="A", status="qualified", customer_potential="8")
        self.assertTrue(prepare.qualification_ok(a))
        self.assertFalse(prepare.qualification_ok(dict(base, tier="C", customer_potential="5")))
        self.assertFalse(prepare.qualification_ok(dict(base, agent_type="lead_reactivation")))

    def test_role_safety_blocks_non_sales_mailboxes(self):
        for address in (
            "noreply@example.com", "legal@example.com", "hr@example.com", "jobs@example.com",
            "billing@example.com", "privacy@example.com", "postmaster@example.com", "media@example.com",
        ):
            self.assertFalse(prepare.role_safe(address), address)
        self.assertTrue(prepare.role_safe("info@example.com"))
        self.assertTrue(prepare.role_safe("sales@example.com"))

    def test_official_external_contact_and_mx_unknown_are_review_eligible(self):
        candidate = {"candidate_id": "c1", "status": "hold", "country": "US", "website": "https://example.com"}
        q = {
            "offer_family": "ai_agent", "agent_type": "quote_intake", "tier": "B",
            "status": "hold", "customer_potential": "6",
        }
        contact = {
            "status": "manual_review", "email": "company@gmail.com", "source_url": "https://example.com/contact",
            "mx_status": "unknown", "domain_alignment": "external",
        }
        self.assertTrue(prepare.candidate_ok(candidate, q, contact, country="US"))
        self.assertFalse(prepare.candidate_ok(candidate, q, dict(contact, mx_status="missing"), country="US"))
        self.assertFalse(prepare.candidate_ok(candidate, q, dict(contact, source_url="https://directory.example/contact"), country="US"))

    def _queue_row(self, lead_id="lead-1", website="https://example.com", address="info@example.com"):
        meta = {
            "automation": daily.AUTOMATION_ID,
            "copy_contract": daily.COPY_CONTRACT,
            "primary_agent_type": "quote_intake",
            "draft_fit": "B",
            "customer_potential": 6,
            "email_source_url": "https://example.com/contact",
            "contact_mx_status": "unknown",
            "evidence_url": "https://example.com/request-a-quote",
            "observation": "The site offers a quote request form for custom work.",
            "value_asset_summary": "A quote intake workflow could collect the required details before handoff.",
            "personalization_anchor": "custom quote request",
        }
        return {
            "lead_id": lead_id,
            "company": "Example Co",
            "website": website,
            "email": address,
            "subject": "Quote requests at Example Co",
            "body": "I noticed your quote request flow. A short intake workflow could collect the required details before your team reviews them. Would it be useful if I sent a short example? Not interested? A quick no is enough. This is a commercial message.",
            "country": "US",
            "status": "manual_review",
            "compliance_status": "manual_review",
            "source": "agent_offer:" + json.dumps(meta),
        }

    def test_daily_gate_accepts_b_then_blocks_suppression_and_duplicates(self):
        row = self._queue_row()
        with patch.object(daily, "initial_copy_errors", return_value=[]):
            accepted, rejected = daily.eligible([row], [], country="US")
            self.assertEqual(1, len(accepted))
            self.assertFalse(rejected)

            accepted, rejected = daily.eligible([row], [{"email": "info@example.com", "domain": ""}], country="US")
            self.assertEqual([], accepted)
            self.assertIn("lead-1", rejected)
            self.assertIn("suppressed", rejected["lead-1"])

            second = self._queue_row("lead-2", "https://example.com/services", "sales@example.com")
            accepted, rejected = daily.eligible([row, second], [], country="US")
            self.assertEqual(1, len(accepted))
            self.assertIn("lead-2", rejected)
            self.assertIn("duplicate domain in batch", rejected["lead-2"])

    def test_stale_copy_contract_is_rejected(self):
        row = self._queue_row()
        meta = json.loads(row["source"].split(":", 1)[1])
        meta["copy_contract"] = "old-contract"
        row["source"] = "agent_offer:" + json.dumps(meta)
        with patch.object(daily, "initial_copy_errors", return_value=[]):
            accepted, rejected = daily.eligible([row], [], country="US")
        self.assertEqual([], accepted)
        self.assertIn("draft-first metadata missing/stale", rejected["lead-1"])

    def test_discovery_read_retry_recovers_from_ssl_eof(self):
        calls = {"read": 0}

        def flaky_get_values(service, spreadsheet_id, range_name):
            calls["read"] += 1
            if calls["read"] == 1:
                raise OSError("SSL EOF")
            return [["candidate_id"], ["candidate-1"]]

        with patch.object(discovery_retry.legacy, "get_values", side_effect=flaky_get_values), \
             patch.object(discovery_retry.time, "sleep", return_value=None):
            ids = discovery_retry._existing_ids(object(), "sheet", "ProspectCandidates!A:Z")
        self.assertEqual(2, calls["read"])
        self.assertIn("candidate-1", ids)

    def test_discovery_retry_reconciles_ambiguous_success_without_duplicate(self):
        state = [["candidate_id"]]
        calls = {"append": 0}

        def fake_get_values(service, spreadsheet_id, range_name):
            return copy.deepcopy(state)

        def ambiguous_append(service, spreadsheet_id, range_name, rows):
            calls["append"] += 1
            state.extend([[row[0]] for row in rows])
            raise OSError("SSL EOF")

        with patch.object(discovery_retry.legacy, "get_values", side_effect=fake_get_values), \
             patch.object(discovery_retry, "_original_append_rows", side_effect=ambiguous_append), \
             patch.object(discovery_retry.time, "sleep", return_value=None):
            discovery_retry.append_rows_retry(object(), "sheet", "ProspectCandidates!A:Z", [["candidate-1", "x"]])
        self.assertEqual(1, calls["append"])
        self.assertEqual(1, sum(1 for row in state if row and row[0] == "candidate-1"))

    def test_prepare_read_retry_recovers_from_ssl_eof(self):
        calls = {"read": 0}

        def flaky_load(service, spreadsheet_id, sheet, headers):
            calls["read"] += 1
            if calls["read"] == 1:
                raise OSError("SSL EOF")
            return []

        with patch.object(prepare_retry, "_original_load", side_effect=flaky_load), \
             patch.object(prepare_retry.time, "sleep", return_value=None):
            rows = prepare_retry.load_retry(object(), "sheet", prepare.QUEUE_SHEET, ["lead_id"])
        self.assertEqual([], rows)
        self.assertEqual(2, calls["read"])

    def test_prepare_retry_reconciles_ambiguous_success_without_duplicate(self):
        state = []
        row = {"lead_id": "lead-1", "email": "info@example.com"}
        calls = {"append": 0}

        def fake_load(service, spreadsheet_id, sheet, headers):
            return copy.deepcopy(state)

        def ambiguous_append(service, spreadsheet_id, sheet, headers, desired):
            calls["append"] += 1
            state.append(dict(desired))
            raise OSError("connection reset")

        with patch.object(prepare_retry, "_original_load", side_effect=fake_load), \
             patch.object(prepare_retry, "_append_once", side_effect=ambiguous_append), \
             patch.object(prepare_retry.time, "sleep", return_value=None):
            prepare_retry.append_row_retry(object(), "sheet", prepare.QUEUE_SHEET, ["lead_id", "email"], row)
        self.assertEqual(1, calls["append"])
        self.assertEqual(1, len(state))

    def test_post_imap_status_retry_is_idempotent_for_transport_failure(self):
        calls = {"mark": 0}

        def flaky_mark(service, spreadsheet_id, selected):
            calls["mark"] += 1
            if calls["mark"] == 1:
                raise OSError("SSL EOF")

        with patch.object(daily_retry, "_original_mark_concepts", side_effect=flaky_mark), \
             patch.object(daily_retry.time, "sleep", return_value=None):
            daily_retry.mark_concepts_retry(object(), "sheet", [object()])
        self.assertEqual(2, calls["mark"])

    def test_workflow_has_source_pin_tests_retry_paths_and_no_smtp_sender(self):
        workflow = Path(".github/workflows/daily-agent-drafts-v14.yml").read_text(encoding="utf-8")
        self.assertIn("EXPECTED_SOURCE_SET_VERSION: 14.0.3-draft-recovery", workflow)
        self.assertIn("test_draft_first_v14*.py", workflow)
        self.assertIn("outreach_draft_first_prepare_retry.py", workflow)
        self.assertIn("outreach_daily_draft_first_retry.py", workflow)
        self.assertIn("receipt_ids == selected_ids", workflow)
        for path in (
            "scripts/outreach_daily_draft_first.py",
            "scripts/outreach_daily_draft_first_retry.py",
            "scripts/outreach_draft_first_prepare.py",
            "scripts/outreach_draft_first_prepare_retry.py",
        ):
            text = Path(path).read_text(encoding="utf-8").casefold()
            self.assertNotIn("import smtplib", text)
            self.assertNotIn(".sendmail(", text)


if __name__ == "__main__":
    unittest.main()
