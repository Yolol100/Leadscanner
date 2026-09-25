from __future__ import annotations

import unittest

from apply_contact_approvals import apply_approvals, parse_approved_emails


class ApprovalTests(unittest.TestCase):
    def test_exact_approved_email_gets_pass(self):
        payload = {
            "candidates": [
                {
                    "public_business_emails": ["sales@example.nl"],
                    "contact_basis_status": "unverified",
                    "excluded_competitor": False,
                }
            ]
        }
        result = apply_approvals(payload, {"sales@example.nl"})
        candidate = result["candidates"][0]
        self.assertEqual(candidate["contact_basis_status"], "pass")
        self.assertEqual(candidate["contact_basis_hint"], "explicit_exact_email_approval")
        self.assertEqual(result["approved_contact_count"], 1)

    def test_public_email_alone_does_not_pass(self):
        payload = {
            "candidates": [
                {
                    "public_business_emails": ["info@example.nl"],
                    "contact_basis_status": "unverified",
                    "excluded_competitor": False,
                }
            ]
        }
        result = apply_approvals(payload, set())
        self.assertEqual(result["candidates"][0]["contact_basis_status"], "unverified")
        self.assertEqual(result["approved_contact_count"], 0)

    def test_competitor_is_always_blocked(self):
        payload = {
            "candidates": [
                {
                    "public_business_emails": ["info@agency.nl"],
                    "excluded_competitor": True,
                }
            ]
        }
        result = apply_approvals(payload, {"info@agency.nl"})
        self.assertEqual(result["candidates"][0]["contact_basis_status"], "blocked")

    def test_parser_accepts_comma_semicolon_newline(self):
        self.assertEqual(
            parse_approved_emails("A@EXAMPLE.NL, b@example.nl;\nc@example.nl"),
            {"a@example.nl", "b@example.nl", "c@example.nl"},
        )


if __name__ == "__main__":
    unittest.main()
