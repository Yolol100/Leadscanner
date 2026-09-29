from __future__ import annotations

import unittest

from myhost_final_audit import audit_rows


class FinalAuditTests(unittest.TestCase):
    def config(self):
        return {"monthly_price_eur": {"min": 250, "max": 500}}

    def row(self, company: str, email: str, domain: str, lead_id: str):
        observation = f"{company} dienstverlening"
        body = (
            "Goedendag,\n\n"
            f"Op jullie website staat “{observation}”. Met één compact Groeiabonnement help ik bedrijven hun online aanpak doorlopend verbeteren.\n\n"
            "• Website/webshop verbeteren of nieuw maken waar nodig\n"
            "• Zoekbaarheid verbeteren\n"
            "• Social content verzorgen\n"
            "• Geschikte terugkerende processen waar haalbaar deels automatiseren\n"
            "• Hosting overnemen/beheren\n"
            "• Ik als vast contactpersoon\n\n"
            "€250–€500 per maand, afhankelijk van wat jullie nodig hebben.\n\n"
            f"Zal ik vrijblijvend een voorbeeld design maken voor {company}? Dan kunnen jullie eerst bekijken of de richting interessant is.\n\n"
            "Geen interesse? Laat het gerust weten, dan houd ik het hierbij.\n\n"
            "Groet,\nAndrew"
        )
        return {
            "lead_id": lead_id,
            "company": company,
            "website": f"https://{domain}/",
            "official_domain_hint": domain,
            "product_id": "growth_subscription",
            "language": "nl",
            "language_source": "html_lang",
            "monthly_price_min_eur": 250,
            "monthly_price_max_eur": 500,
            "excluded_competitor": False,
            "exclusion_reason": None,
            "contact_basis_status": "review_required",
            "contact_basis_hint": "public_email_review_required",
            "email_source_urls": [f"https://{domain}/contact"],
            "email_source_types": ["official_site"],
            "email_source_refs": [f"https://{domain}/contact"],
            "verified_observation": observation,
            "verified_observation_source_url": f"https://{domain}/",
            "verified_observation_source_type": "official_site",
            "status": "review_draft",
            "email": email,
            "subject": f"Idee voor {company}",
            "body": body,
        }

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


if __name__ == "__main__":
    unittest.main()
