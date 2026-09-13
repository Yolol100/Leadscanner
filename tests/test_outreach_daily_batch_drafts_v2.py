import json
import unittest
from unittest.mock import patch

import outreach_daily_batch_drafts as base
import outreach_daily_batch_drafts_v2 as hardened


class _FakeResponse:
    def __init__(self, status):
        self.status = status


class _FakeTransientError(RuntimeError):
    def __init__(self, status=429, message="quota exceeded"):
        super().__init__(message)
        self.resp = _FakeResponse(status)


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

    def _b_draft_evidence(self):
        queue = {
            "country": "NL",
            "website": "https://example.com/",
            "email": "sales@external-mail.example",
            "source": "agent_offer:" + json.dumps({
                "qualification_tier": "B",
                "customer_potential": "7",
            }),
        }
        candidate = {
            "status": "hold",
            "website": "https://example.com/",
        }
        qualification = {
            "tier": "B",
            "status": "hold",
            "customer_potential": "7",
        }
        contact = {
            "status": "manual_review",
            "mx_status": "present",
            "email": "sales@external-mail.example",
            "source_url": "https://example.com/contact/",
            "domain_alignment": "external_domain",
        }
        return queue, candidate, qualification, contact

    def test_b_hold_and_official_external_contact_remove_only_obsolete_draft_errors(self):
        queue, candidate, qualification, contact = self._b_draft_evidence()
        obsolete = [
            "candidate is not qualified",
            "qualification status is not qualified",
            "qualification tier is not A",
            "customer potential is below A threshold",
            "queue metadata does not prove A-tier qualification",
            "recipient domain is not aligned to official website",
            "contact is not ready",
            "contact domain alignment is not proven",
        ]
        with patch.object(hardened, "_ORIGINAL_CANDIDATE_ERRORS", return_value=obsolete):
            errors = hardened.hardened_candidate_errors(
                queue,
                agent_type="quote_intake",
                country="NL",
                candidate=candidate,
                qualification=qualification,
                contact=contact,
                source={"country": "NL"},
                lead_statuses={"gevonden"},
                suppressed_emails=set(),
                suppressed_domains=set(),
            )
        self.assertEqual(errors, [])

    def test_missing_mx_and_third_party_source_remain_blocked(self):
        queue, candidate, qualification, contact = self._b_draft_evidence()
        contact["mx_status"] = "missing"
        contact["source_url"] = "https://directory.example.net/company"
        original_errors = [
            "candidate is not qualified",
            "qualification status is not qualified",
            "qualification tier is not A",
            "customer potential is below A threshold",
            "queue metadata does not prove A-tier qualification",
            "recipient domain is not aligned to official website",
            "contact is not ready",
            "contact domain alignment is not proven",
            "contact MX presence is not proven",
            "contact source is not on the official site",
        ]
        with patch.object(hardened, "_ORIGINAL_CANDIDATE_ERRORS", return_value=original_errors):
            errors = hardened.hardened_candidate_errors(
                queue,
                agent_type="quote_intake",
                country="NL",
                candidate=candidate,
                qualification=qualification,
                contact=contact,
                source={"country": "NL"},
                lead_statuses={"gevonden"},
                suppressed_emails=set(),
                suppressed_domains=set(),
            )
        self.assertIn("contact MX presence is not proven", errors)
        self.assertIn("contact source is not on the official site", errors)

    def test_suppression_and_role_safety_are_never_relaxed(self):
        queue, candidate, qualification, contact = self._b_draft_evidence()
        protected = [
            "recipient or domain is suppressed",
            "recipient mailbox role is not suitable for cold business outreach",
        ]
        with patch.object(hardened, "_ORIGINAL_CANDIDATE_ERRORS", return_value=protected):
            errors = hardened.hardened_candidate_errors(
                queue,
                agent_type="quote_intake",
                country="NL",
                candidate=candidate,
                qualification=qualification,
                contact=contact,
                source={"country": "NL"},
                lead_statuses={"gevonden"},
                suppressed_emails={"sales@external-mail.example"},
                suppressed_domains=set(),
            )
        self.assertEqual(errors, protected)

    def test_transient_sheets_load_retries_then_succeeds(self):
        expected = ([], [], [], [], [], [], [])
        with patch.object(
            hardened,
            "_ORIGINAL_LOAD_STATE",
            side_effect=[_FakeTransientError(429), expected],
        ) as loader, patch.object(hardened.time, "sleep") as sleeper:
            result = hardened._retrying_load_state(object(), "sheet", max_attempts=3)
        self.assertEqual(result, expected)
        self.assertEqual(loader.call_count, 2)
        sleeper.assert_called_once_with(5)

    def test_contract_error_does_not_retry(self):
        failure = RuntimeError("ProspectSources headers do not match the active runtime contract")
        with patch.object(hardened, "_ORIGINAL_LOAD_STATE", side_effect=failure) as loader, patch.object(
            hardened.time, "sleep"
        ) as sleeper:
            with self.assertRaisesRegex(RuntimeError, "headers do not match"):
                hardened._retrying_load_state(object(), "sheet", max_attempts=3)
        loader.assert_called_once()
        sleeper.assert_not_called()

    def test_wrapper_scopes_base_gates_to_v2_selection(self):
        self.assertIs(base._role_is_usable, hardened._ORIGINAL_ROLE_IS_USABLE)
        self.assertIs(base.candidate_errors, hardened._ORIGINAL_CANDIDATE_ERRORS)
        self.assertIs(base._load_state, hardened._ORIGINAL_LOAD_STATE)
        seen = {}

        def probe():
            seen["role"] = base._role_is_usable
            seen["errors"] = base.candidate_errors
            seen["load_state"] = base._load_state
            return 7

        result = hardened._with_hardened_gates(probe)
        self.assertEqual(result, 7)
        self.assertIs(seen["role"], hardened.hardened_role_is_usable)
        self.assertIs(seen["errors"], hardened.hardened_candidate_errors)
        self.assertIs(seen["load_state"], hardened._retrying_load_state)
        self.assertIs(base._role_is_usable, hardened._ORIGINAL_ROLE_IS_USABLE)
        self.assertIs(base.candidate_errors, hardened._ORIGINAL_CANDIDATE_ERRORS)
        self.assertIs(base._load_state, hardened._ORIGINAL_LOAD_STATE)


if __name__ == "__main__":
    unittest.main()
