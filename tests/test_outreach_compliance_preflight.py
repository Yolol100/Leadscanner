import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from outreach_compliance_preflight import (
    COMPLIANCE_BLOCKED,
    COMPLIANCE_NOT_PROVEN,
    COMPLIANCE_PASSED,
    GATE_1,
    GATE_2,
    GATE_3,
    compliance_errors,
    generic_local_part,
)


def base_row(**overrides) -> dict[str, str]:
    row = {
        "country": "NL",
        "email": "partnerships@example.nl",
        "contact_verified": "true",
        "contact_source": "https://example.nl/contact",
        "compliance_status": COMPLIANCE_NOT_PROVEN,
        "compliance_basis": "",
        "compliance_gate_used": "",
        "compliance_evidence": "",
        "compliance_source": "",
        "compliance_checked_at": "",
        "compliance_purpose_match": "false",
        "outreach_allowed": "false",
    }
    row.update(overrides)
    return row


class CompliancePreflightTests(unittest.TestCase):
    def test_generic_info_without_purpose_is_not_proven(self):
        row = base_row(email="info@example.nl")
        self.assertEqual(compliance_errors(row), [])
        self.assertEqual(row["compliance_status"], COMPLIANCE_NOT_PROVEN)
        self.assertTrue(generic_local_part(row["email"]))

    def test_personal_public_email_without_purpose_is_not_proven(self):
        row = base_row(email="jan@example.nl")
        self.assertEqual(compliance_errors(row), [])
        self.assertEqual(row["compliance_status"], COMPLIANCE_NOT_PROVEN)

    def test_gate2_business_proposals_with_matching_purpose_can_pass(self):
        row = base_row(
            compliance_status=COMPLIANCE_PASSED,
            compliance_basis="explicit_designation",
            compliance_gate_used=GATE_2,
            compliance_evidence='Official page states "business proposals: partnerships@example.nl"',
            compliance_source="https://example.nl/partnerships",
            compliance_checked_at="2026-09-18T00:00:00Z",
            compliance_purpose_match="true",
            outreach_allowed="true",
        )
        self.assertEqual(compliance_errors(row), [])

    def test_gate2_press_address_mismatch_fails(self):
        row = base_row(
            email="press@example.nl",
            compliance_status=COMPLIANCE_PASSED,
            compliance_basis="explicit_designation",
            compliance_gate_used=GATE_2,
            compliance_evidence='Official page states "press enquiries"',
            compliance_source="https://example.nl/press",
            compliance_checked_at="2026-09-18T00:00:00Z",
            compliance_purpose_match="false",
            outreach_allowed="true",
        )
        self.assertIn("Gate 2 requires explicit purpose match", compliance_errors(row))

    def test_gate2_sales_address_without_proven_purpose_fails(self):
        row = base_row(
            email="sales@example.nl",
            compliance_status=COMPLIANCE_PASSED,
            compliance_basis="explicit_designation",
            compliance_gate_used=GATE_2,
            compliance_evidence="Official page lists sales enquiries only",
            compliance_source="https://example.nl/contact",
            compliance_checked_at="2026-09-18T00:00:00Z",
            compliance_purpose_match="false",
            outreach_allowed="true",
        )
        self.assertIn("Gate 2 requires explicit purpose match", compliance_errors(row))

    def test_gate1_documented_consent_passes(self):
        row = base_row(
            compliance_status=COMPLIANCE_PASSED,
            compliance_basis="consent",
            compliance_gate_used=GATE_1,
            compliance_evidence="Consent record consent-123",
            compliance_source="first_party_consent_log",
            compliance_checked_at="2026-09-18T00:00:00Z",
            outreach_allowed="true",
        )
        self.assertEqual(compliance_errors(row), [])

    def test_gate3_missing_proof_does_not_pass(self):
        row = base_row(
            compliance_status=COMPLIANCE_PASSED,
            compliance_basis="existing_customer_similar",
            compliance_gate_used=GATE_3,
            compliance_evidence="",
            compliance_source="",
            compliance_checked_at="",
            outreach_allowed="true",
        )
        errors = compliance_errors(row)
        self.assertIn("COMPLIANCE_PASSED requires compliance_evidence", errors)
        self.assertIn("COMPLIANCE_PASSED requires compliance_source", errors)

    def test_gate3_with_documented_proof_passes(self):
        row = base_row(
            compliance_status=COMPLIANCE_PASSED,
            compliance_basis="existing_customer_similar",
            compliance_gate_used=GATE_3,
            compliance_evidence="Customer record plus similar-service and opt-out evidence",
            compliance_source="first_party_customer_record",
            compliance_checked_at="2026-09-18T00:00:00Z",
            outreach_allowed="true",
        )
        self.assertEqual(compliance_errors(row), [])

    def test_verified_email_alone_cannot_pass(self):
        row = base_row(
            compliance_status=COMPLIANCE_PASSED,
            outreach_allowed="true",
        )
        errors = compliance_errors(row)
        self.assertIn("COMPLIANCE_PASSED requires a valid compliance_gate_used", errors)

    def test_missing_contact_verification_blocks_pass(self):
        row = base_row(
            contact_verified="false",
            compliance_status=COMPLIANCE_PASSED,
            compliance_basis="consent",
            compliance_gate_used=GATE_1,
            compliance_evidence="Consent record",
            compliance_source="consent_log",
            compliance_checked_at="2026-09-18T00:00:00Z",
            outreach_allowed="true",
        )
        self.assertIn("contact_verified is not true", compliance_errors(row))

    def test_non_pass_status_cannot_allow_outreach(self):
        for status in (COMPLIANCE_NOT_PROVEN, COMPLIANCE_BLOCKED):
            with self.subTest(status=status):
                errors = compliance_errors(base_row(compliance_status=status, outreach_allowed="true"))
                self.assertIn("outreach_allowed must be false unless compliance is passed", errors)


if __name__ == "__main__":
    unittest.main()
