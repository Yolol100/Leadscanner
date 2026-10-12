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
    def _run(self, mode, *, proof_error=False, registry_error=False, **overrides):
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
                patch("leadscanner_core.audit_exact_readback",
                      side_effect=RuntimeError("private readback contains sensitive details") if proof_error else None,
                      return_value={
                          "status": "green", "registry_rows": [], "draft_count": 1,
                          "automatic_send": False,
                      })
            )
            patched["access"] = stack.enter_context(
                patch("leadscanner_core.check_registry_access")
            )
            patched["registry_write"] = stack.enter_context(
                patch("leadscanner_core.update_registry",
                      side_effect=RuntimeError("private registry failure body") if registry_error else None,
                      return_value={
                          "status": "green", "exact_readback": True,
                          "appended_count": 1, "already_present_count": 0,
                      })
            )
            stack.enter_context(patch.dict("leadscanner_core.os.environ", {
                "OUTREACH_MAIL_PASSWORD": "synthetic-not-a-real-secret",
            }))
            params = {
                "mode": mode,
                "region": "Amsterdam", "keywords": ["fietsenwinkel"],
                "radius_km": 5, "discovery_limit": 20,
                "verify_limit": 10, "repository_private": mode == "drafts",
            }
            params.update(overrides)
            self.last_mocks = patched
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

    def test_untrusted_run_cannot_store_real_drafts(self):
        with self.assertRaisesRegex(SafeRunError, "trusted_manual_run_required"):
            run(mode="drafts",
                region="Amsterdam", keywords=["fiets"], radius_km=5,
                discovery_limit=10, verify_limit=10, repository_private=False)

    def test_public_repo_manual_main_secret_runner_can_prepare_drafts(self):
        with patch.dict("leadscanner_core.os.environ", {
            "LEADSCANNER_TRUSTED_MAIN_DRAFTS": "true",
        }):
            report, mocks = self._run("drafts", repository_private=False)
        self.assertEqual(report["counts"]["registry_confirmed"], 1)
        mocks["imap"].assert_called_once()
        self.assertEqual(report["automatic_send"], False)

    def test_request_validation_bounded(self):
        self.assertFalse(_params_valid("send", "Amsterdam", ["fiets"], 5, 10, 10))
        self.assertFalse(_params_valid("drafts", "Amsterdam", ["fiets"], 5, 10, 101))
        self.assertFalse(_params_valid("drafts", "Amsterdam", [], 5, 10, 10))
        self.assertTrue(_params_valid("drafts", "Amsterdam", ["fiets"], 5, 10, 10))

    def test_registry_uses_private_vault_based_historical_v2(self):
        live_rows = [
            ["company", "website", "domain", "emails", "status", "history",
             "lead_ids", "last_event_at", "sources", "exclude_from_new_leads"],
            ["Example", "https://example.org", "example.org",
             "info@example.org", "concept", "draft", "", "", "historic", "TRUE"],
        ]
        from historical_v2 import row_for_match
        synthetic = row_for_match({
            "emails": set(), "official": set(), "corporate": set(),
            "count": 1128, "official_count": 914, "corporate_count": 146,
        }, b"separate-private-key")
        with patch("leadscanner_core._authorized_session", return_value=(object(), "service-account")) as auth, \
             patch("leadscanner_core.read_live_values", return_value=live_rows) as read, \
             patch("leadscanner_core.read_production_state", return_value=synthetic) as historical:
            exclusions = fetch_registry()
        self.assertEqual(len(exclusions), 2)
        self.assertIn("example.org", exclusions[0]["identity"]["domains"])
        self.assertEqual(exclusions[1]["status"], "historical_v2_suppression")
        auth.assert_called_once_with(read_only=True)
        read.assert_called_once()
        historical.assert_called_once()
        self.assertNotIn("email", str(exclusions[0]["status"]))

    def test_missing_or_invalid_private_vault_holds_all_new_discovery(self):
        ordinary = [
            ["company", "website", "domain", "emails", "status", "history",
             "lead_ids", "last_event_at", "sources", "exclude_from_new_leads"],
            ["Old", "https://example.nl", "example.nl",
             "info@example.nl", "sent", "", "", "", "archive", "TRUE"],
        ]
        with patch("leadscanner_core._authorized_session", return_value=(object(), "service-account")), \
             patch("leadscanner_core.read_live_values", return_value=ordinary), \
             patch("leadscanner_core.read_production_state",
                   side_effect=RuntimeError("historical_v2_vault_unavailable_or_modified")), \
             patch("leadscanner_core.discover") as discover:
            with self.assertRaisesRegex(RuntimeError, "historical_v2_vault_unavailable"):
                fetch_registry()
        discover.assert_not_called()

    def test_authenticated_registry_missing_permission_fails_closed(self):
        with patch("leadscanner_core._authorized_session",
                   side_effect=RuntimeError("missing authorized service account")):
            with self.assertRaisesRegex(RuntimeError, "missing authorized"):
                fetch_registry()

    def test_within_batch_shared_email_or_domain_is_skipped(self):
        a = fixture_row()
        b = fixture_row("growth-abcdef0123456789abcd", "info@example.org")
        with patch("leadscanner_core.match_candidate", return_value=None):
            ready, skipped = revalidate_drafts({"rows": [a, b]}, [])
        self.assertEqual(skipped, 1)
        self.assertEqual([row["lead_id"] for row in ready["rows"]], [a["lead_id"]])

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
        with self.assertRaisesRegex(SafeRunError, "myhost_readback"):
            self._run("drafts", proof_error=True)
        self.last_mocks["registry_write"].assert_not_called()

    def test_registry_failure_is_not_reported_as_success(self):
        with self.assertRaisesRegex(SafeRunError, "registry_closure"):
            self._run("drafts", registry_error=True)
        self.last_mocks["proof"].assert_called_once()

    def test_private_provider_errors_never_appear_in_public_cli_output(self):
        from sys import argv
        buffer = io.StringIO()
        with patch("sys.argv", ["leadscanner_core.py", "--mode", "public_audit"]), \
             patch("leadscanner_core.run", side_effect=RuntimeError("private-recipient@example.org")), \
             redirect_stdout(buffer):
            result = main()
        self.assertEqual(result, 1)
        self.assertIn('"failed_stage": "bootstrap"', buffer.getvalue())
        self.assertNotIn("private-recipient", buffer.getvalue())

    def test_no_live_pipeline_reads_public_registry_csv(self):
        from pathlib import Path
        workflow = Path(".github/workflows/leads-cold.yml").read_text(encoding="utf-8")
        core = Path("scripts/leadscanner_core.py").read_text(encoding="utf-8")
        self.assertNotIn("DEDUPE_REGISTRY_CSV_URL", workflow + core)
        self.assertNotIn("export?format=csv", workflow + core)
        self.assertIn("_authorized_session(read_only=True)", core)
        self.assertIn("LEAD_REGISTRY_SERVICE_ACCOUNT_JSON", workflow)

    def test_missing_credentials_do_not_access_external_registry(self):
        with patch("leadscanner_core._authorized_session",
                   side_effect=RuntimeError("no account")):
            with self.assertRaises(RuntimeError):
                fetch_registry()
    def test_workflow_excludes_sending_and_public_artifacts(self):
        from pathlib import Path
        text = Path(".github/workflows/leads-cold.yml").read_text(encoding="utf-8")
        self.assertIn("public_audit:", text)
        self.assertIn("drafts:", text)
        self.assertIn("LEADSCANNER_TRUSTED_MAIN_DRAFTS", text)
        self.assertIn("refs/heads/main", text)
        self.assertIn("workflow_dispatch", text)
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
