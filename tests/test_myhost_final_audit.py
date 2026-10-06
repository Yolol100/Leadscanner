from __future__ import annotations

import unittest

from myhost_final_audit import audit_rows
from prepare_growth_batch import prepare_batch


class FinalAuditTests(unittest.TestCase):
    def config(self):
        return {"monthly_price_eur": {"min": 250, "max": 500}}

    def row(self, company: str, email: str, domain: str, lead_id: str):
        _ = lead_id
        contact = {
            "name_hint": company,
            "website_hint": f"https://{domain}/",
            "official_domain_hint": domain,
            "category_hint": "legal_service",
            "public_business_emails": [email],
            "email_source_urls": [f"https://{domain}/contact"],
            "email_source_types": ["official_site"],
            "email_source_refs": [f"https://{domain}/contact"],
            "verified_observation": (
                f"{company} biedt advies en zakelijke dienstverlening aan klanten"
            ),
            "verified_observation_source_url": f"https://{domain}/",
            "verified_observation_source_type": "official_site",
            "language": "nl",
            "language_source": "html_lang",
            "excluded_competitor": False,
            "contact_basis_status": "review_required",
            "contact_basis_hint": "public_email_review_required",
        }
        return prepare_batch(
            {"candidates": [contact]},
            self.config(),
            draft_limit=1,
        )["rows"][0]

    def test_shared_brand_name_is_allowed_when_domain_email_and_lead_are_unique(self):
        base = self.row("Voorbeeld BV", "a@example.nl", "a.nl", "growth-0123456789abcdefabcd")
        other = self.row("Voorbeeld BV", "b@example.nl", "b.nl", "growth-1123456789abcdefabcd")
        batch1 = {"rows": [base], "safety": {"automatic_send": False}}
        batch2 = {"rows": [other], "safety": {"automatic_send": False}}

        def report(row):
            return {
                "eligible_count": 1,
                "created_count": 1,
                "existing_count": 0,
                "replaced_count": 0,
                "review_required_count": 1,
                "smtp_send": "not_available",
                "items": [
                    {
                        "lead_id": row["lead_id"],
                        "to": row["email"],
                        "subject": row["subject"],
                        "body": row["body"],
                        "review_status": "contact-basis",
                        "outcome": "created",
                    }
                ],
            }

        _, failures, metrics = audit_rows(
            [batch1, batch2], [report(base), report(other)], self.config()
        )
        self.assertFalse(any("duplicate_company" in failure for failure in failures))
        self.assertFalse(any("duplicate_domain" in failure for failure in failures))
        self.assertFalse(any("duplicate_email" in failure for failure in failures))
        self.assertFalse(any("duplicate_lead_id" in failure for failure in failures))
        self.assertEqual(metrics["requested_total"], 2)
        self.assertEqual(metrics["unique_companies"], 1)
        self.assertEqual(metrics["company_name_collision_groups"], 1)
        self.assertEqual(metrics["company_name_collision_rows"], 2)

    def test_mixed_batch_sizes_use_report_eligible_counts(self):
        report100 = {
            "eligible_count": 100,
            "created_count": 100,
            "existing_count": 0,
            "replaced_count": 0,
            "review_required_count": 100,
            "smtp_send": "not_available",
            "items": [],
        }
        report34 = {
            "eligible_count": 34,
            "created_count": 34,
            "existing_count": 0,
            "replaced_count": 0,
            "review_required_count": 34,
            "smtp_send": "not_available",
            "items": [],
        }
        batch100 = {"rows": [], "safety": {"automatic_send": False}}
        batch34 = {"rows": [], "safety": {"automatic_send": False}}
        _, failures, metrics = audit_rows(
            [batch100, batch34], [report100, report34], self.config()
        )
        self.assertEqual(metrics["requested_total"], 134)
        self.assertTrue(any("expected 100 canonical review_draft rows" in failure for failure in failures))
        self.assertTrue(any("expected 34 canonical review_draft rows" in failure for failure in failures))

    def test_no_automatic_send_is_required(self):
        batch = {"rows": [], "safety": {"automatic_send": True}}
        report = {
            "eligible_count": 75,
            "created_count": 75,
            "existing_count": 0,
            "replaced_count": 0,
            "review_required_count": 75,
            "smtp_send": "not_available",
            "items": [],
        }
        _, failures, _ = audit_rows([batch, batch], [report, report], self.config())
        self.assertTrue(any("automatic_send" in failure for failure in failures))


    def test_final_audit_accepts_mixed_existing_and_replaced_rewrite_outcomes(self):
        contact = {
            "name_hint": "Voorbeeld Fysiotherapie",
            "website_hint": "https://voorbeeld.nl/",
            "official_domain_hint": "voorbeeld.nl",
            "category_hint": "physical_medicine_and_rehabilitation",
            "public_business_emails": ["info@voorbeeld.nl"],
            "email_source_urls": ["https://voorbeeld.nl/contact"],
            "email_source_types": ["official_site"],
            "email_source_refs": ["https://voorbeeld.nl/contact"],
            "verified_observation": "Wij bieden fysiotherapie in Utrecht.",
            "verified_observation_source_url": "https://voorbeeld.nl/",
            "verified_observation_source_type": "official_site",
            "language": "nl",
            "language_source": "html_lang",
            "excluded_competitor": False,
            "contact_basis_status": "review_required",
            "contact_basis_hint": "public_email_review_required",
        }
        batch = prepare_batch({"candidates": [contact]}, self.config(), draft_limit=1)
        row = batch["rows"][0]
        report = {
            "eligible_count": 1,
            "created_count": 0,
            "existing_count": 1,
            "replaced_count": 0,
            "review_required_count": 1,
            "smtp_send": "not_available",
            "items": [{
                "lead_id": row["lead_id"],
                "to": row["email"],
                "subject": row["subject"],
                "body": row["body"],
                "review_status": "contact-basis",
                "outcome": "existing",
            }],
        }
        rows, failures, _ = audit_rows([batch], [report], self.config())
        self.assertEqual(len(rows), 1)
        self.assertEqual(failures, [])

if __name__ == "__main__":
    unittest.main()

