import unittest

from update_dedupe_registry import (
    HEADERS,
    exact_rows_present,
    plan_registry_update,
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

    def test_bad_live_headers_fail_closed(self):
        expected = self.row()
        with self.assertRaisesRegex(ValueError, "live_registry_headers_mismatch"):
            plan_registry_update(self.readback([expected]), [["company", "domain"]])


if __name__ == "__main__":
    unittest.main()
