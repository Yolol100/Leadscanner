import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import outreach_one_time_us_guard as g


Y = "fixture-alpha"
T = "fixture-beta"
W = "fixture-gamma"
EXPECTED = {Y, T, W}


def row(lead_id, email="lead@example.com", **overrides):
    base = {
        "lead_id": lead_id,
        "email": email,
        "country": "US",
        "compliance_status": "approved",
        "compliance_basis": "other_verified_basis",
        "opt_out_mode": "reply_optout",
        "status": "approved",
        "body": f"This is a commercial message.\n{g.POSTAL_PLACEHOLDER}",
    }
    base.update(overrides)
    return base


class OneTimeUsOutreachGuardTests(unittest.TestCase):
    def test_empty_cohort_is_not_green(self):
        self.assertTrue(g.validate_one_time_batch([], [], set()))

    def test_duplicate_identity_blocks_in_both_row_orders(self):
        invalid = row(Y, compliance_status="manual_review")
        for rows in [[invalid, row(Y), row(T), row(W)], [row(Y), invalid, row(T), row(W)]]:
            self.assertTrue(any("duplicate queue identity" in e for e in g.validate_one_time_batch(rows, [], EXPECTED)))

    def test_approved_row_without_identity_blocks(self):
        self.assertTrue(g.validate_one_time_batch([row(Y), row(T), row(W), row("")], [], EXPECTED))

    def test_exact_three_green(self):
        self.assertEqual(g.validate_one_time_batch([row(Y), row(T), row(W)], [], EXPECTED), [])

    def test_partial_progress_green(self):
        self.assertEqual(
            g.validate_one_time_batch(
                [row(Y, status="sent"), row(T), row(W)], [], EXPECTED
            ),
            [],
        )

    def test_completed_suppressed_member_does_not_block_remaining(self):
        suppression = [{"email": "lead@example.com", "domain": "", "reason": "optout"}]
        self.assertEqual(
            g.validate_one_time_batch(
                [
                    row(Y, status="sent"),
                    row(T, email="tytek@example.org"),
                    row(W, email="whm@example.org"),
                ],
                suppression,
                EXPECTED,
            ),
            [],
        )

    def test_extra_approved_lead_blocks(self):
        errors = g.validate_one_time_batch(
            [row(Y), row(T), row(W), row("extra")], [], EXPECTED
        )
        self.assertTrue(any("approved lead set mismatch" in item for item in errors))

    def test_missing_expected_lead_blocks(self):
        errors = g.validate_one_time_batch([row(Y), row(W)], [], EXPECTED)
        self.assertTrue(any("missing queue row" in item for item in errors))

    def test_unsupported_expected_status_blocks(self):
        errors = g.validate_one_time_batch(
            [row(Y, status="prepared"), row(T), row(W)], [], EXPECTED
        )
        self.assertTrue(any("unsupported campaign status" in item for item in errors))

    def test_eer_country_blocks(self):
        errors = g.validate_one_time_batch(
            [row(Y, country="NL"), row(T), row(W)], [], EXPECTED
        )
        self.assertTrue(any("country must be US" in item for item in errors))

    def test_suppressed_approved_recipient_blocks(self):
        suppression = [{"email": "lead@example.com", "domain": "", "reason": "optout"}]
        errors = g.validate_one_time_batch(
            [row(Y), row(T, email="tytek@example.org"), row(W, email="whm@example.org")],
            suppression,
            EXPECTED,
        )
        self.assertTrue(any("recipient is suppressed" in item for item in errors))

    def test_private_placeholder_is_required(self):
        errors = g.validate_one_time_batch(
            [row(Y, body="This is a commercial message."), row(T), row(W)], [], EXPECTED
        )
        self.assertTrue(any("private postal placeholder" in item for item in errors))

    def test_compliance_basis_is_fail_closed(self):
        errors = g.validate_one_time_batch(
            [row(Y, compliance_basis=""), row(T), row(W)], [], EXPECTED
        )
        self.assertTrue(any("other_verified_basis" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
