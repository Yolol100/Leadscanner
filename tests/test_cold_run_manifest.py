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

    def test_zero_draft_draft_mode_can_close_without_external_mutation(self):
        kwargs = base_inputs()
        kwargs["draft_batch"] = {"draft_candidate_count": 0}
        result = build_manifest(mode="draft", **kwargs)
        self.assertEqual(result["closure"]["status"], "closed")
        self.assertFalse(result["closure"]["mailbox_mutation"])
        self.assertFalse(result["closure"]["registry_mutation"])


if __name__ == "__main__":
    unittest.main()
