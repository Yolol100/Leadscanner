"""Checkpoint boundaries for the one-time 450 draft review, with no credentials."""
import unittest
from unittest.mock import patch

import review450 as b
import review450_supplement as s


class CheckpointSafety(unittest.TestCase):
    BASE = "a" * 64

    def state(self, *, digest=BASE, count="0", cursor="0", status="pending"):
        return [["key", "value"], ["task", b.TASK],
                ["base_digest", digest], ["next_region_index", cursor],
                ["checked_sites", "0"], ["verified_replacements", count],
                ["status", status], ["updated_at", "not_started"]]

    def test_empty_pool_resumes_first_region(self):
        with patch.object(b, "read", side_effect=[[b.COLS], self.state()]):
            pool, cursor, checked = s.load_checkpoint(object(), self.BASE)
        self.assertEqual((pool, cursor, checked), ([], 0, 0))

    def test_changed_original_batch_blocks_resume(self):
        with patch.object(b, "read", side_effect=[[b.COLS], self.state(digest="b" * 64)]):
            with self.assertRaisesRegex(RuntimeError, "checkpoint_digest_mismatch"):
                s.load_checkpoint(object(), self.BASE)

    def test_missing_private_pool_header_blocks_resume(self):
        with patch.object(b, "read", side_effect=[[["not_a_private_pool"]], self.state()]):
            with self.assertRaisesRegex(RuntimeError, "checkpoint_headers_invalid"):
                s.load_checkpoint(object(), self.BASE)

    def test_count_mismatch_blocks_resume(self):
        with patch.object(b, "read", side_effect=[[b.COLS], self.state(count="1")]):
            with self.assertRaisesRegex(RuntimeError, "checkpoint_state_invalid"):
                s.load_checkpoint(object(), self.BASE)

    def test_invalid_checkpoint_row_blocks_resume(self):
        with patch.object(b, "read", side_effect=[[b.COLS, ["draft-a"]], self.state()]):
            with self.assertRaisesRegex(RuntimeError, "checkpoint_rows_invalid"):
                s.load_checkpoint(object(), self.BASE)

    def test_committed_checkpoint_cannot_be_promoted_again(self):
        with patch.object(b, "read", side_effect=[[b.COLS], self.state(status="committed")]):
            with self.assertRaisesRegex(RuntimeError, "checkpoint_unexpected_committed"):
                s.load_checkpoint(object(), self.BASE)

    def test_store_is_atomic_private_only_and_readback_verified(self):
        expected_state = [["key", "value"], ["task", b.TASK],
                          ["base_digest", self.BASE], ["next_region_index", "2"],
                          ["checked_sites", "18"], ["verified_replacements", "0"],
                          ["status", "partial"], ["updated_at", "2026-10-15"]]
        with patch.object(b, "read", side_effect=[[b.COLS], expected_state]), \
             patch.object(b, "post") as post, patch.object(b, "now", return_value="2026-10-15"):
            s.save_checkpoint(object(), [], self.BASE, 2, 18, "partial")
        post.assert_called_once()
        requests = post.call_args.args[1]
        self.assertEqual([r["updateCells"]["range"]["sheetId"] for r in requests],
                         [s.POOL_ID, s.POOL_STATE_ID])
        self.assertNotIn(b.TAB_ID, [r["updateCells"]["range"]["sheetId"] for r in requests])

    def test_mismatched_private_readback_blocks(self):
        with patch.object(b, "read", return_value=[]), \
             patch.object(b, "post"), patch.object(b, "now", return_value="2026-10-15"):
            with self.assertRaisesRegex(RuntimeError, "checkpoint_readback_failed"):
                s.save_checkpoint(object(), [], self.BASE, 0, 0, "partial")


if __name__ == "__main__":
    unittest.main()
