import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import outreach_one_time_us_guard as g


Y = "prospect-8b27a02ebd2e038890e3"
W = "prospect-2ec02fcea879e3646bff"


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
    def test_exact_two_green(self):
        self.assertEqual(g.validate_one_time_batch([row(Y), row(W)], [], {Y, W}), [])

    def test_extra_approved_lead_blocks(self):
        errors = g.validate_one_time_batch([row(Y), row(W), row("extra")], [], {Y, W})
        self.assertTrue(any("approved lead set mismatch" in item for item in errors))

    def test_missing_expected_lead_blocks(self):
        errors = g.validate_one_time_batch([row(Y)], [], {Y, W})
        self.assertTrue(any("approved lead set mismatch" in item for item in errors))

    def test_eer_country_blocks(self):
        errors = g.validate_one_time_batch([row(Y, country="NL"), row(W)], [], {Y, W})
        self.assertTrue(any("country must be US" in item for item in errors))

    def test_suppressed_recipient_blocks(self):
        suppression = [{"email": "lead@example.com", "domain": "", "reason": "optout"}]
        errors = g.validate_one_time_batch([row(Y), row(W, email="other@example.org")], suppression, {Y, W})
        self.assertTrue(any("recipient is suppressed" in item for item in errors))

    def test_private_placeholder_is_required(self):
        errors = g.validate_one_time_batch(
            [row(Y, body="This is a commercial message."), row(W)], [], {Y, W}
        )
        self.assertTrue(any("private postal placeholder" in item for item in errors))

    def test_compliance_basis_is_fail_closed(self):
        errors = g.validate_one_time_batch(
            [row(Y, compliance_basis=""), row(W)], [], {Y, W}
        )
        self.assertTrue(any("other_verified_basis" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
