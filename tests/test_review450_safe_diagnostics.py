"""Public diagnostic codes must not reveal prospect or credential details."""
import unittest
from review450_supplement import safe_reason


class SafeScopeDiagnostics(unittest.TestCase):
    def test_fixed_failure_codes_are_visible(self):
        self.assertEqual(safe_reason(RuntimeError("too_many_scope_issues_requires_review")),
                         "too_many_scope_issues_requires_review")
        self.assertEqual(safe_reason(RuntimeError("lead_history_duplicate_identity")),
                         "lead_history_duplicate_identity")

    def test_unknown_exception_text_is_never_visible(self):
        secret = "customer@example.invalid private draft and access token"
        self.assertEqual(safe_reason(RuntimeError(secret)),
                         "private_scope_or_source_or_readback")
        self.assertEqual(safe_reason(ValueError(secret)), "ValueError")
        self.assertNotIn(secret, safe_reason(KeyError(secret)))

    def test_whitelist_is_exact_not_substring(self):
        self.assertEqual(safe_reason(RuntimeError("duplicate_business customer@example.invalid")),
                         "private_scope_or_source_or_readback")


if __name__ == "__main__":
    unittest.main()
