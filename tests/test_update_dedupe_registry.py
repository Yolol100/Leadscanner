import unittest

from update_dedupe_registry import (
    HEADERS,
    exact_rows_present,
    plan_registry_update,
    update_registry,
)


class RegistryUpdateTests(unittest.TestCase):
    def readback(self, rows):
        return {
            "status": "green",
            "automatic_send": False,
            "draft_count": len(rows),
            "registry_headers": HEADERS,
            "registry_rows": rows,
        }

    def row(self, *, company="Acme Fietsen", domain="acmefietsen.nl", email="info@acmefietsen.nl", lead_id="growth-aaaaaaaaaaaaaaaaaaaa"):
        return [
            company,
            f"https://{domain}/",
            domain,
            email,
            "concept",
            "concept",
            lead_id,
            "",
            "cold_pipeline_review_draft",
            "TRUE",
        ]

    def test_new_row_is_planned_for_append(self):
        current = [HEADERS, self.row(company="Bestaand", domain="bestaand.nl", email="info@bestaand.nl", lead_id="growth-bbbbbbbbbbbbbbbbbbbb")]
        expected = self.row()
        plan = plan_registry_update(self.readback([expected]), current)
        self.assertEqual(plan["append_count"], 1)
        self.assertEqual(plan["existing_count"], 0)
        self.assertEqual(plan["append_rows"], [expected])

    def test_existing_domain_is_not_appended_twice(self):
        expected = self.row()
        current = [HEADERS, expected]
        plan = plan_registry_update(self.readback([expected]), current)
        self.assertEqual(plan["append_count"], 0)
        self.assertEqual(plan["existing_count"], 1)

    def test_existing_email_is_not_appended_twice(self):
        existing = self.row(company="Ander Label", domain="ander.nl", email="info@acmefietsen.nl", lead_id="growth-bbbbbbbbbbbbbbbbbbbb")
        expected = self.row()
        plan = plan_registry_update(self.readback([expected]), [HEADERS, existing])
        self.assertEqual(plan["append_count"], 0)
        self.assertEqual(plan["existing_count"], 1)

    def test_company_identity_matches_accent_tolerant_preflight_rules(self):
        existing = self.row(
            company="Café Fietsen B.V.",
            domain="ander.nl",
            email="other@ander.nl",
            lead_id="growth-bbbbbbbbbbbbbbbbbbbb",
        )
        expected = self.row(
            company="Cafe Fietsen BV",
            domain="nieuw.nl",
            email="new@nieuw.nl",
            lead_id="growth-cccccccccccccccccccc",
        )
        plan = plan_registry_update(self.readback([expected]), [HEADERS, existing])
        self.assertEqual(plan["append_count"], 0)
        self.assertEqual(plan["existing_count"], 1)

    def test_subdomain_identity_matches_preflight_domain_rules(self):
        existing = self.row(
            company="Ander Label",
            domain="shop.acmefietsen.nl",
            email="other@shop.acmefietsen.nl",
            lead_id="growth-bbbbbbbbbbbbbbbbbbbb",
        )
        expected = self.row(
            company="Nieuw Label",
            domain="acmefietsen.nl",
            email="new@acmefietsen.nl",
            lead_id="growth-cccccccccccccccccccc",
        )
        plan = plan_registry_update(self.readback([expected]), [HEADERS, existing])
        self.assertEqual(plan["append_count"], 0)
        self.assertEqual(plan["existing_count"], 1)

    def test_existing_identity_without_suppression_fails_closed(self):
        existing = self.row()
        existing[9] = "FALSE"
        expected = self.row()
        with self.assertRaisesRegex(ValueError, "identity_exists_without_suppression"):
            plan_registry_update(self.readback([expected]), [HEADERS, existing])

    def test_registry_requires_true_suppression_flag(self):
        expected = self.row()
        expected[9] = "FALSE"
        with self.assertRaisesRegex(ValueError, "must_suppress"):
            plan_registry_update(self.readback([expected]), [HEADERS])

    def test_exact_readback_requires_full_appended_row(self):
        expected = self.row()
        self.assertTrue(exact_rows_present([expected], [HEADERS, expected]))
        changed = list(expected)
        changed[4] = "sent"
        self.assertFalse(exact_rows_present([expected], [HEADERS, changed]))

    def test_zero_draft_still_validates_readback_contract(self):
        invalid_status = self.readback([])
        invalid_status["status"] = "red"
        with self.assertRaisesRegex(ValueError, "readback_must_be_green"):
            update_registry(invalid_status, spreadsheet_id="sheet", sheet_name="tab")

        inconsistent = self.readback([self.row()])
        inconsistent["draft_count"] = 0
        with self.assertRaisesRegex(ValueError, "registry_intent_count_mismatch"):
            update_registry(inconsistent, spreadsheet_id="sheet", sheet_name="tab")

    def test_bad_live_headers_fail_closed(self):
        expected = self.row()
        with self.assertRaisesRegex(ValueError, "live_registry_headers_mismatch"):
            plan_registry_update(self.readback([expected]), [["company", "domain"]])


if __name__ == "__main__":
    unittest.main()
