import unittest
from unittest.mock import patch

import outreach_daily_batch_drafts as base
import outreach_daily_batch_drafts_v2 as hardened


class HardenedRoleTests(unittest.TestCase):
    def test_rejects_role_tokens_and_suffixes(self):
        for address in (
            "hr@example.com",
            "herkerhr@example.com",
            "jobs.us@example.com",
            "privacy-office@example.com",
            "recruiting-team@example.com",
        ):
            with self.subTest(address=address):
                self.assertFalse(hardened.hardened_role_is_usable(address))
        self.assertTrue(hardened.hardened_role_is_usable("sales@example.com"))
        self.assertTrue(hardened.hardened_role_is_usable("quotes@example.com"))

    @patch.object(hardened, "_ORIGINAL_CANDIDATE_ERRORS", return_value=[])
    def test_source_country_conflict_fails_closed(self, original):
        errors = hardened.hardened_candidate_errors(
            {"country": "US"},
            agent_type="quote_intake",
            country="US",
            candidate={},
            qualification={},
            contact={},
            source={"country": "CA"},
            lead_statuses=set(),
            suppressed_emails=set(),
            suppressed_domains=set(),
        )
        self.assertIn("prospect source country conflicts with campaign", errors)
        original.assert_called_once()

    @patch.object(hardened, "_ORIGINAL_CANDIDATE_ERRORS", return_value=[])
    def test_matching_source_country_is_clean(self, _original):
        errors = hardened.hardened_candidate_errors(
            {"country": "US"},
            agent_type="quote_intake",
            country="US",
            candidate={},
            qualification={},
            contact={},
            source={"country": "US"},
            lead_statuses=set(),
            suppressed_emails=set(),
            suppressed_domains=set(),
        )
        self.assertEqual(errors, [])

    def test_wrapper_replaces_base_gates_used_by_selection(self):
        self.assertIs(base._role_is_usable, hardened.hardened_role_is_usable)
        self.assertIs(base.candidate_errors, hardened.hardened_candidate_errors)


if __name__ == "__main__":
    unittest.main()
