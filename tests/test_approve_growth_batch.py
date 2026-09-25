from __future__ import annotations

import unittest

from approve_growth_batch import approve_batch, parse_lead_ids


class ApproveGrowthBatchTests(unittest.TestCase):
    def row(self):
        return {
            "lead_id": "growth-0123456789abcdefabcd",
            "company": "Voorbeeld BV",
            "email": "info@voorbeeld.nl",
            "subject_preview": "Korte vraag over online groei",
            "concept_preview": "Hoi Voorbeeld BV, concept.",
            "status": "needs_contact_basis",
            "contact_basis_status": "unverified",
            "excluded_competitor": False,
        }

    def test_exact_lead_id_approval_creates_draft_ready_row(self):
        batch = {"rows": [self.row()]}
        result = approve_batch(batch, {"growth-0123456789abcdefabcd"})
        row = result["rows"][0]
        self.assertEqual(row["status"], "draft_ready")
        self.assertEqual(row["contact_basis_status"], "pass")
        self.assertEqual(row["subject"], row["subject_preview"])
        self.assertEqual(row["body"], row["concept_preview"])
        self.assertEqual(result["explicitly_approved_count"], 1)

    def test_unknown_lead_id_fails(self):
        with self.assertRaises(RuntimeError):
            approve_batch({"rows": [self.row()]}, {"growth-ffffffffffffffffffff"})

    def test_noncanonical_lead_id_fails_closed(self):
        with self.assertRaises(RuntimeError):
            approve_batch({"rows": [self.row()]}, {"lead-0123456789abcdefabcd"})

    def test_competitor_cannot_be_approved(self):
        row = self.row()
        row["excluded_competitor"] = True
        with self.assertRaises(RuntimeError):
            approve_batch({"rows": [row]}, {"growth-0123456789abcdefabcd"})

    def test_parser_accepts_whitespace_commas_and_newlines(self):
        self.assertEqual(
            parse_lead_ids("growth-a, growth-b\ngrowth-c"),
            {"growth-a", "growth-b", "growth-c"},
        )


if __name__ == "__main__":
    unittest.main()
