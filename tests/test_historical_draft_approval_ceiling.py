"""No historical IMAP write can exceed the 53 auditable approvals."""
import unittest
from unittest.mock import patch

from _once_historical_site_redraft import (
    AUDITED_REVIEW_CEILINGS, BATCH_SIZE, EXPECTED, run,
)


class HistoricalReviewCeilingTests(unittest.TestCase):
    def test_exact_twelve_windows_and_fifty_three_approved_limit(self):
        self.assertEqual(set(AUDITED_REVIEW_CEILINGS), set(range(0, EXPECTED, BATCH_SIZE)))
        self.assertEqual(sum(AUDITED_REVIEW_CEILINGS.values()), 53)
        self.assertEqual(AUDITED_REVIEW_CEILINGS[1000], 8)
        self.assertEqual(AUDITED_REVIEW_CEILINGS[1100], 3)
        self.assertEqual(AUDITED_REVIEW_CEILINGS[0], 0)

    def test_unapproved_extra_candidate_fails_before_any_imap_contact(self):
        history = {"status": "historical_v2_suppression"}
        with patch("_once_historical_site_redraft.read_source",
                   return_value=([], 0)), \
             patch("_once_historical_site_redraft.fetch_registry",
                   return_value=[history]), \
             patch("_once_historical_site_redraft.build_batch",
                   return_value=(
                       {"counts": {"ready_for_review": 2}},
                       {"rows": [{"status": "review_draft"}] * 2},
                   )), \
             patch("myhost_draft.create_drafts",
                   side_effect=AssertionError("IMAP must never be called")) as imap:
            with self.assertRaisesRegex(RuntimeError, "historical_approved_count_exceeded"):
                run(100, "drafts")
            imap.assert_not_called()

    def test_zero_approved_batch_does_not_create_new_drafts(self):
        history = {"status": "historical_v2_suppression"}
        with patch("_once_historical_site_redraft.read_source",
                   return_value=([], 0)), \
             patch("_once_historical_site_redraft.fetch_registry",
                   return_value=[history]), \
             patch("_once_historical_site_redraft.build_batch",
                   return_value=(
                       {"counts": {"ready_for_review": 0}},
                       {"rows": []},
                   )), \
             patch("myhost_draft.create_drafts",
                   side_effect=AssertionError("IMAP must not be called")) as imap:
            result = run(0, "drafts")
            self.assertEqual(result["drafts_created"], 0)
            imap.assert_not_called()

    def test_more_review_rows_than_report_also_cannot_write(self):
        history = {"status": "historical_v2_suppression"}
        with patch("_once_historical_site_redraft.read_source",
                   return_value=([], 0)), \
             patch("_once_historical_site_redraft.fetch_registry",
                   return_value=[history]), \
             patch("_once_historical_site_redraft.build_batch",
                   return_value=(
                       {"counts": {"ready_for_review": 1}},
                       {"rows": [{"status": "review_draft"}] * 2},
                   )), \
             patch("myhost_draft.create_drafts",
                   side_effect=AssertionError("IMAP must never be called")) as imap:
            with self.assertRaisesRegex(RuntimeError, "historical_approved_count_exceeded"):
                run(100, "drafts")
            imap.assert_not_called()


if __name__ == "__main__":
    unittest.main()
