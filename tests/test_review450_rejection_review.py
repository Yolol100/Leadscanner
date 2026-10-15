"""A large source rejection set requires complete explicit private review."""
import unittest
from review450_supplement import require_rejection_review, scope_allowed


class RejectionReviewTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{"website": "https://reviewed-%d.example.org/" % i} for i in range(22)]
        self.domains = {"reviewed-%d.example.org" % i for i in range(22)}

    def test_unreviewed_large_set_still_stops(self):
        with self.assertRaisesRegex(RuntimeError, "requires_review"):
            require_rejection_review(self.rows, set())

    def test_one_missing_review_still_stops(self):
        with self.assertRaisesRegex(RuntimeError, "requires_review"):
            require_rejection_review(self.rows, self.domains - {"reviewed-21.example.org"})

    def test_complete_private_review_allows_replacement_only(self):
        require_rejection_review(self.rows, self.domains)
        self.assertTrue(all(not scope_allowed(row, self.domains) for row in self.rows))

    def test_broad_parent_does_not_stand_in_for_exact_review(self):
        with self.assertRaisesRegex(RuntimeError, "requires_review"):
            require_rejection_review(self.rows, {"example.org"})

    def test_small_original_behavior_is_preserved(self):
        require_rejection_review(self.rows[:20], set())


if __name__ == "__main__":
    unittest.main()
