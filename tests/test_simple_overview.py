"""The one-page operator view never exposes recipient details or hides send status."""
import unittest

from simple_overview import render_overview


def manifest(mode="preview", counts=None):
    return {
        "schema_version": "leadscanner-cold-run-manifest/1.0",
        "execution_mode": mode,
        "request": {"preview_copy_mode": "reviewed_mail"},
        "counts": counts or {},
        "safety": {"automatic_send": False, "human_review_required": True},
        "closure": {"automatic_send": False, "status": "preview_ready"},
        "diagnostics": {
            "drop_reasons": {
                "verification": {"recipient_not_confirmed_on_website": 9},
                "outreach": {"no_specific_first_party_signal": 3},
            }
        },
    }


class SimpleOverviewTests(unittest.TestCase):
    def test_preview_uses_only_aggregate_counts(self):
        data = manifest(counts={
            "discovery_after_cheap_filters": 45,
            "dedupe_kept": 24,
            "verified_for_research": 12,
            "research_ready": 9,
            "outreach_reason_ready": 6,
            "review_queue_candidates": 4,
        })
        data["request"]["email"] = "private@somewhere.example"
        out = render_overview(data)
        self.assertIn("Contacten klaar voor beoordeling: **4**", out)
        self.assertIn("Contact niet bevestigd: 9", out)
        self.assertIn("Verzonden:** 0", out)
        self.assertNotIn("private@somewhere", out)

    def test_fact_only_mode_is_not_presented_as_generated_mail(self):
        item = manifest()
        item["request"]["preview_copy_mode"] = "instantly_sequence"
        self.assertIn("Alleen feiten, nog geen e-mailtekst", render_overview(item))
        self.assertNotIn("Persoonlijke conceptmails", render_overview(item))

    def test_staged_and_draft_modes_show_the_correct_non_send_outcome(self):
        stage = manifest("instantly_stage", {"approved_for_instantly": 3, "instantly_staged": 2, "suppressed_after_preview": 1})
        out = render_overview(stage)
        self.assertIn("Klaargezet in Instantly: **2**", out)
        self.assertIn("Campagneactivering staat los", out)
        draft = manifest("draft", {"approved_for_draft": 3, "draft_created": 2, "draft_existing_exact": 1})
        self.assertIn("Concepten opgeslagen: **2**", render_overview(draft))

    def test_false_send_assurance_or_malformed_counts_fail_closed(self):
        item = manifest()
        item["closure"]["automatic_send"] = True
        with self.assertRaisesRegex(ValueError, "overview_requires_no_send_evidence"):
            render_overview(item)
        item = manifest()
        item["counts"] = {"review_queue_candidates": "20"}
        with self.assertRaisesRegex(ValueError, "overview_counts_must_be_nonnegative_integers"):
            render_overview(item)


if __name__ == "__main__":
    unittest.main()
