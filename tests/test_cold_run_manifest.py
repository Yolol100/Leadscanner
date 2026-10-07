import unittest

from cold_run_manifest import build_manifest


def base_inputs():
    return {
        "request": {
            "region": "Rotterdam",
            "keywords": ["fietsenmaker"],
            "target_candidates": 100,
            "verify_limit": 40,
            "radius_km": 8,
        },
        "filtered": {"candidate_count": 18},
        "dedupe": {"kept_count": 14},
        "verified": {"ready_for_research_count": 8},
        "research": {"research_ready_count": 6},
        "reasons": {"ready_count": 4},
        "values": {"ready_count": 4},
        "mail": {"ready_for_human_review_count": 3},
        "draft_batch": {"draft_candidate_count": 3},
    }


class ColdRunManifestTests(unittest.TestCase):
    def test_preview_is_mutation_free(self):
        result = build_manifest(mode="preview", **base_inputs())
        self.assertEqual(result["execution_mode"], "preview")
        self.assertEqual(result["closure"]["status"], "preview_ready")
        self.assertFalse(result["closure"]["mailbox_mutation"])
        self.assertFalse(result["closure"]["registry_mutation"])
        self.assertFalse(result["closure"]["automatic_send"])
        self.assertEqual(result["counts"]["review_draft_candidates"], 3)
        self.assertEqual(result["counts"]["draft_created"], 0)

    def test_preview_rejects_mutation_results(self):
        with self.assertRaisesRegex(ValueError, "preview_must_not_include_mutation_results"):
            build_manifest(
                mode="preview",
                draft_readback={"status": "green"},
                **base_inputs(),
            )

    def test_draft_mode_requires_green_closure_for_nonempty_batch(self):
        with self.assertRaisesRegex(ValueError, "green_mailbox_readback"):
            build_manifest(mode="draft", **base_inputs())

        kwargs = base_inputs()
        kwargs["draft_readback"] = {
            "status": "green",
            "created_count": 2,
            "existing_count": 1,
        }
        with self.assertRaisesRegex(ValueError, "green_registry_update"):
            build_manifest(mode="draft", **kwargs)

    def test_draft_mode_reports_exact_closed_counts(self):
        kwargs = base_inputs()
        kwargs["draft_readback"] = {
            "status": "green",
            "created_count": 2,
            "existing_count": 1,
        }
        kwargs["registry_update"] = {
            "status": "green",
            "appended_count": 2,
            "already_present_count": 1,
            "exact_readback": True,
        }
        result = build_manifest(mode="draft", **kwargs)
        self.assertEqual(result["closure"]["status"], "closed")
        self.assertTrue(result["closure"]["mailbox_mutation"])
        self.assertTrue(result["closure"]["registry_mutation"])
        self.assertEqual(result["counts"]["draft_created"], 2)
        self.assertEqual(result["counts"]["draft_existing_exact"], 1)
        self.assertEqual(result["counts"]["registry_appended"], 2)
        self.assertEqual(result["counts"]["registry_already_present"], 1)
        self.assertFalse(result["safety"]["automatic_send"])

    def test_draft_manifest_rejects_incoherent_mailbox_or_registry_counts(self):
        kwargs = base_inputs()
        kwargs["draft_readback"] = {
            "status": "green",
            "created_count": 1,
            "existing_count": 0,
        }
        kwargs["registry_update"] = {
            "status": "green",
            "appended_count": 3,
            "already_present_count": 0,
            "exact_readback": True,
        }
        with self.assertRaisesRegex(ValueError, "mailbox_count_mismatch"):
            build_manifest(mode="draft", **kwargs)

        kwargs["draft_readback"] = {
            "status": "green",
            "created_count": 2,
            "existing_count": 1,
        }
        kwargs["registry_update"] = {
            "status": "green",
            "appended_count": 1,
            "already_present_count": 0,
            "exact_readback": True,
        }
        with self.assertRaisesRegex(ValueError, "registry_count_mismatch"):
            build_manifest(mode="draft", **kwargs)

    def test_manifest_reports_review_and_operator_approval_counts(self):
        kwargs = base_inputs()
        kwargs["review_queue"] = {"review_candidate_count": 5}
        kwargs["approved_batch"] = {
            "approval": {
                "approved_count": 2,
                "rejected_by_operator_count": 3,
            }
        }
        kwargs["draft_batch"] = {"draft_candidate_count": 2}
        kwargs["draft_readback"] = {
            "status": "green",
            "created_count": 2,
            "existing_count": 0,
        }
        kwargs["registry_update"] = {
            "status": "green",
            "appended_count": 2,
            "already_present_count": 0,
            "exact_readback": True,
        }
        result = build_manifest(mode="draft", **kwargs)
        self.assertEqual(result["counts"]["review_queue_candidates"], 5)
        self.assertEqual(result["counts"]["approved_for_draft"], 2)
        self.assertEqual(result["counts"]["operator_rejected"], 3)

    def test_draft_manifest_carries_source_preview_provenance_and_revalidation(self):
        kwargs = base_inputs()
        kwargs["review_queue"] = {"review_candidate_count": 5}
        kwargs["approved_batch"] = {
            "approval": {
                "approved_count": 3,
                "rejected_by_operator_count": 2,
            }
        }
        kwargs["revalidation"] = {
            "suppressed_after_preview_count": 1,
        }
        kwargs["source_preview_snapshot"] = {
            "preview_id": "preview-1234567890abcdef12345678",
            "source": {
                "run_id": 999,
                "head_sha": "a" * 40,
            },
        }
        kwargs["draft_batch"] = {"draft_candidate_count": 2}
        kwargs["draft_readback"] = {
            "status": "green",
            "created_count": 2,
            "existing_count": 0,
        }
        kwargs["registry_update"] = {
            "status": "green",
            "appended_count": 2,
            "already_present_count": 0,
            "exact_readback": True,
        }
        result = build_manifest(mode="draft", **kwargs)
        self.assertEqual(result["counts"]["approved_for_draft"], 3)
        self.assertEqual(result["counts"]["suppressed_after_preview"], 1)
        self.assertEqual(result["counts"]["review_draft_candidates"], 2)
        self.assertEqual(result["provenance"]["source_preview_run_id"], 999)
        self.assertEqual(
            result["provenance"]["source_preview_id"],
            "preview-1234567890abcdef12345678",
        )

    def test_manifest_includes_quality_and_coverage_diagnostics(self):
        kwargs = base_inputs()
        kwargs["funnel"] = {
            "drop_reasons": {
                "outreach": {"weak_generic_marketing_signal": 2},
            },
            "ready_signal_types": {"appointment": 1},
        }
        kwargs["coverage"] = {
            "source_status": "sufficient",
            "operational_pool_status": "sufficient",
            "second_source_decision": "second_source_not_needed",
        }
        result = build_manifest(mode="preview", **kwargs)
        self.assertEqual(
            result["diagnostics"]["drop_reasons"]["outreach"]["weak_generic_marketing_signal"],
            2,
        )
        self.assertEqual(result["diagnostics"]["ready_signal_types"], {"appointment": 1})
        self.assertEqual(result["diagnostics"]["coverage_source_status"], "sufficient")
        self.assertEqual(
            result["diagnostics"]["second_source_decision"],
            "second_source_not_needed",
        )

    def test_zero_draft_draft_mode_can_close_without_external_mutation(self):
        kwargs = base_inputs()
        kwargs["draft_batch"] = {"draft_candidate_count": 0}
        result = build_manifest(mode="draft", **kwargs)
        self.assertEqual(result["closure"]["status"], "closed")
        self.assertFalse(result["closure"]["mailbox_mutation"])
        self.assertFalse(result["closure"]["registry_mutation"])


if __name__ == "__main__":
    unittest.main()
