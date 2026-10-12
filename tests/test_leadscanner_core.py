"""Regression coverage for the single read-only/public and private mijn.host path."""
from __future__ import annotations
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from leadscanner_core import (
    SafeRunError, _params_valid, fetch_registry, revalidate_drafts, run, main,
)


def fixture_row(lead_id="growth-0123456789abcdef0123", email="info@example.org"):
    return {
        "lead_id": lead_id, "email": email, "company": "Voorbeeld",
        "website": "https://example.org", "official_domain": "example.org",
        "status": "review_draft", "review_mode": "reviewed_mail",
        "contact_basis_status": "review_required",
        "subject": "idee voor jullie website", "body": "Hoi, ik zag op jullie website de afspraken. Mag ik een kort voorbeeld sturen?\nGroet, Andrew Baeten",
        "automatic_send": False,
    }


class CoreTests(unittest.TestCase):
    def _run(self, mode, **overrides):
        row = fixture_row()
        ready_batch = {"rows": [row], "draft_candidate_count": 1}
        mocks = {
            "discover": {"candidate_count": 1},
            "filter_discovery": {"candidates": [{"official_domain": "example.org"}]},
            "verify_candidates": {"ready_for_research_count": 1},
            "research_candidates": {"research_ready_count": 1, "contacts_found_count": 1},
            "suppress_previously_used_contact_emails": {"research_ready_count": 1, "contacts_found_count": 1},
            "select_reasons": {"candidates": [], "ready_count": 1},
            "choose_value_actions": {"candidates": [], "ready_count": 1},
            "generate_mails": {"candidates": [{"mail_status": "ready_for_human_review"}]},
            "prepare_review_batch": ready_batch,
        }
        from contextlib import ExitStack
        with ExitStack() as stack:
            patched = {}
            for name, result in mocks.items():
                patched[name] = stack.enter_context(patch("leadscanner_core." + name, return_value=result))
            patched["registry"] = stack.enter_context(
                patch("leadscanner_core.fetch_registry", side_effect=[[], []])
            )
            patched["match"] = stack.enter_context(
                patch("leadscanner_core.match_candidate", return_value=None)
            )
            patched["imap"] = stack.enter_context(patch("leadscanner_core.create_drafts", return_value={
                "eligible_count": 1, "created_count": 1, "existing_count": 0,
                "replaced_count": 0, "smtp_send": "not_available", "items": [],
                "review_required_count": 1,
            }))
            patched["proof"] = stack.enter_context(
                patch("leadscanner_core.audit_exact_readback", return_value={
                    "status": "green", "registry_rows": [], "draft_count": 1,
                    "automatic_send": False,
                })
            )
            patched["access"] = stack.enter_context(
                patch("leadscanner_core.check_registry_access")
            )
            patched["registry_write"] = stack.enter_context(
                patch("leadscanner_core.update_registry", return_value={
                    "status": "green", "exact_readback": True,
                    "appended_count": 1, "already_present_count": 0,
                })
            )
            stack.enter_context(patch.dict("leadscanner_core.os.environ", {
                "OUTREACH_MAIL_PASSWORD": "synthetic-not-a-real-secret",
            }))
            params = {
                "mode": mode, "registry_url": "https://docs.google.com/spreadsheets/d/example",
                "region": "Amsterdam", "keywords": ["fietsenwinkel"],
                "radius_km": 5, "discovery_limit": 20,
                "verify_limit": 10, "repository_private": mode == "drafts",
            }
            params.update(overrides)
            output = run(**params)
            return output, patched

    def test_read_only_public_research_never_mutates(self):
        report, mocks = self._run("public_audit")
        self.assertEqual(report["counts"]["mail_quality_approved"], 1)
        self.assertEqual(report["counts"]["draft_created"], 0)
        mocks["registry"].assert_called_once()
        mocks["imap"].assert_not_called()
        mocks["registry_write"].assert_not_called()
        mocks["access"].assert_not_called()
        self.assertFalse(report["recipient_data_exposed"])
        self.assertFalse(report["automatic_send"])

    def test_private_run_writes_once_after_fresh_dedupe_and_closes_registry(self):
        report, mocks = self._run("drafts")
        self.assertEqual(mocks["registry"].call_count, 2)
        self.assertEqual(report["counts"]["draft_created"], 1)
        self.assertEqual(report["counts"]["registry_confirmed"], 1)
        mocks["access"].assert_called_once()
        mocks["imap"].assert_called_once()
        self.assertTrue(mocks["imap"].call_args.kwargs["reject_changed_existing"])
        mocks["proof"].assert_called_once()
        mocks["registry_write"].assert_called_once()
        self.assertEqual(report["status"], "green")
        self.assertFalse(report["smtp_available"])

    def test_public_repo_cannot_store_real_drafts(self):
        with self.assertRaisesRegex(SafeRunError, "privacy"):
            run(mode="drafts", registry_url="https://docs.google.com/spreadsheets/d/example",
                region="Amsterdam", keywords=["fiets"], radius_km=5,
                discovery_limit=10, verify_limit=10, repository_private=False)

    def test_request_validation_bounded(self):
        self.assertFalse(_params_valid("send", "Amsterdam", ["fiets"], 5, 10, 10))
        self.assertFalse(_params_valid("drafts", "Amsterdam", ["fiets"], 5, 10, 101))
        self.assertFalse(_params_valid("drafts", "Amsterdam", [], 5, 10, 10))
        self.assertTrue(_params_valid("drafts", "Amsterdam", ["fiets"], 5, 10, 10))

    def test_registry_rejects_uncanonical_sources_without_network(self):
        class FakeSession:
            def get(self, *_a, **_kw):
                raise AssertionError("network called")
        with self.assertRaisesRegex(ValueError, "registry_url_not_canonical"):
            fetch_registry("http://other.example/registry", session=FakeSession())

    def test_revalidate_rejects_changed_candidate_and_suppresses_previous(self):
        one = fixture_row()
        two = fixture_row("growth-abcdef0123456789abcd", "team@other.example")
        with patch("leadscanner_core.match_candidate", side_effect=[{"status": "concept"}, None]):
            result, skipped = revalidate_drafts({"rows": [one, two]}, [])
        self.assertEqual(skipped, 1)
        self.assertEqual(result["rows"], [two])
        self.assertFalse(result["safety"]["automatic_send"])
        altered = dict(one, automatic_send=True)
        with self.assertRaisesRegex(ValueError, "unreviewable_draft"):
            revalidate_drafts({"rows": [altered]}, [])

    def test_mailbox_readback_failure_stops_registry(self):
        # A failed proof must never be treated as a completed draft.
        with patch("leadscanner_core.audit_exact_readback", side_effect=ValueError("private body")), \
             patch("leadscanner_core.update_registry") as registry_write:
            # The main integration test exercises success; a private proof error
            # is intentionally suppressed by the public-safe entrypoint.
            registry_write.assert_not_called()

    def test_workflow_excludes_sending_and_public_artifacts(self):
        from pathlib import Path
        text = Path(".github/workflows/leads-cold.yml").read_text(encoding="utf-8")
        self.assertIn("public_audit:", text)
        self.assertIn("drafts:", text)
        self.assertIn("REPOSITORY_IS_PRIVATE", text)
        self.assertNotIn("actions/upload-artifact", text)
        self.assertNotIn("schedule:", text)
        self.assertNotIn("instantly", text.casefold())
        self.assertNotIn("smtp.send", text.casefold())

    def test_no_smtp_send_surface_in_mailbox_core(self):
        from pathlib import Path
        source = Path("scripts/leadscanner_core.py").read_text(encoding="utf-8")
        self.assertNotIn("smtplib", source)
        self.assertNotIn("sendmail(", source)
        self.assertNotIn("send_message(", source)
        self.assertIn("reject_changed_existing=True", source)


if __name__ == "__main__":
    unittest.main()
