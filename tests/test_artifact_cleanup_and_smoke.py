"""Offline regression tests for one-time artifact privacy cleanup and preview."""
import unittest
from unittest.mock import patch

from cleanup_sensitive_artifacts import REPOSITORY, cleanup, is_explicit_aggregate, list_all, should_delete
from synthetic_preview_smoke import run_smoke


def artifact(ident, name):
    return {"id": ident, "name": name}


class ArtifactCleanupTests(unittest.TestCase):
    def test_preserve_only_explicitly_aggregate_formats(self):
        self.assertFalse(should_delete("site-research-0-123456789"))
        self.assertFalse(should_delete("instantly-sync-123456789"))
        for name in (
            "leads-cold-preview-12345", "leads-cold-draft-12345",
            "leads-cold-instantly_stage-12345", "instantly-control-12345",
            "legacy-outreach-review", "mailbox-archive", "prospect-list",
            "email-test", "", "campaign-report",
        ):
            with self.subTest(name=name):
                self.assertTrue(should_delete(name))

    def test_delete_only_planned_sensitive_and_verify_clean_readback(self):
        initial = [
            artifact(1, "leads-cold-preview-123"),
            artifact(2, "instantly-control-456"),
            artifact(3, "site-research-0-789"),
            artifact(4, "instantly-sync-333"),
        ]
        remaining = initial[2:]
        with patch("cleanup_sensitive_artifacts.list_all", side_effect=[initial, remaining]) as readback, \
             patch("cleanup_sensitive_artifacts._api") as api:
            result = cleanup("fake-test-token", repository=REPOSITORY)
        self.assertEqual(result["status"], "green")
        self.assertEqual(result["deleted"], 2)
        self.assertEqual(result["remaining_suspected_sensitive"], 0)
        self.assertEqual(result["aggregate_only_artifacts_preserved"], 2)
        self.assertEqual(result["unclassified_artifacts_remaining"], 0)
        self.assertEqual(readback.call_count, 2)
        self.assertEqual([call.args[0] for call in api.call_args_list], ["DELETE", "DELETE"])

    def test_unknown_old_outputs_are_purged_not_assumed_safe(self):
        unknown = artifact(25, "neutral-build-output")
        with patch("cleanup_sensitive_artifacts.list_all", side_effect=[[unknown], []]), \
             patch("cleanup_sensitive_artifacts._api") as api:
            result = cleanup("dummy", repository=REPOSITORY)
        self.assertEqual(result["remaining_suspected_sensitive"], 0)
        self.assertEqual(result["aggregate_only_artifacts_preserved"], 0)
        self.assertEqual(result["unclassified_artifacts_remaining"], 0)
        self.assertEqual(result["deleted"], 1)
        self.assertTrue(should_delete(unknown["name"]))
        self.assertFalse(is_explicit_aggregate(unknown["name"]))
        api.assert_called_once()

    def test_dry_run_has_no_mutation(self):
        planned = [artifact(7, "leads-cold-preview-5678")]
        with patch("cleanup_sensitive_artifacts.list_all", return_value=planned), \
             patch("cleanup_sensitive_artifacts._api", side_effect=AssertionError("no writes")):
            result = cleanup("dummy", repository=REPOSITORY, dry_run=True)
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(result["sensitive_candidates"], 1)

    def test_cleanup_fails_closed_on_new_sensitive_artifact(self):
        item = artifact(1, "mailbox-review-old")
        with patch("cleanup_sensitive_artifacts.list_all", side_effect=[[item], [item]]), \
             patch("cleanup_sensitive_artifacts._api"):
            with self.assertRaisesRegex(RuntimeError, "postdelete_risk_remains"):
                cleanup("dummy", repository=REPOSITORY)

    def test_mismatched_repository_or_missing_token_never_deletes(self):
        with patch("cleanup_sensitive_artifacts.list_all", side_effect=AssertionError("no fetch")):
            for args in [("", REPOSITORY), ("dummy", "different/repo")]:
                with self.subTest(args=args), self.assertRaisesRegex(RuntimeError, "identity_or_auth_missing"):
                    cleanup(args[0], repository=args[1])

    def test_incomplete_listing_is_rejected(self):
        with patch("cleanup_sensitive_artifacts._api", side_effect=[
            {"total_count": 2, "artifacts": [artifact(1, "x")]},
            {"total_count": 2, "artifacts": []},
        ]):
            with self.assertRaisesRegex(RuntimeError, "listing_incomplete"):
                list_all("dummy")


class SyntheticPreviewTests(unittest.TestCase):
    def test_real_offline_preview_pipeline_and_both_review_modes(self):
        result = run_smoke()
        self.assertEqual(result["status"], "green")
        self.assertEqual(result["ranked_findings"], 5)
        self.assertEqual(result["review_candidates"], 1)
        self.assertTrue(result["verified_snapshot"])
        self.assertTrue(result["stale_approval_rejected"])
        self.assertTrue(result["fact_only_mode_verified"])
        self.assertEqual(result["network_calls"], 0)
        self.assertEqual(result["campaign_mutations"], 0)
        self.assertEqual(result["mailbox_mutations"], 0)
        self.assertFalse(result["automatic_send"])


if __name__ == "__main__":
    unittest.main()
