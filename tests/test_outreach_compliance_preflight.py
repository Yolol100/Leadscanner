import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from outreach_compliance_preflight import compliance_errors


def row(country: str, basis: str) -> dict[str, str]:
    return {"country": country, "compliance_basis": basis}


class CompliancePreflightTests(unittest.TestCase):
    def test_nl_consent_allowed(self):
        self.assertEqual(compliance_errors(row("Nederland", "consent")), [])

    def test_nl_existing_customer_allowed(self):
        self.assertEqual(compliance_errors(row("NL", "existing_customer_similar")), [])

    def test_nl_other_basis_blocked(self):
        self.assertTrue(compliance_errors(row("Nederland", "other_verified_basis")))

    def test_decorated_eea_country_variants_block_other_basis(self):
        for country in (
            "The Netherlands",
            "Netherlands (NL)",
            "Nederland (NL)",
            "NL / Nederland",
            "Belgium (BE)",
            "Deutschland (DE)",
        ):
            with self.subTest(country=country):
                self.assertTrue(compliance_errors(row(country, "other_verified_basis")))

    def test_decorated_eea_country_variants_allow_consent(self):
        for country in ("Netherlands (NL)", "Belgium (BE)", "Deutschland (DE)"):
            with self.subTest(country=country):
                self.assertEqual(compliance_errors(row(country, "consent")), [])

    def test_missing_country_blocked(self):
        self.assertTrue(compliance_errors(row("", "consent")))

    def test_missing_basis_blocked(self):
        self.assertTrue(compliance_errors(row("United States", "")))

    def test_non_eea_verified_basis_allowed(self):
        self.assertEqual(compliance_errors(row("United States", "other_verified_basis")), [])


if __name__ == "__main__":
    unittest.main()
