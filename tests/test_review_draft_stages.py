import unittest

from review_draft_stages import audit_exact_readback, prepare_review_batch, stable_lead_id


class ReviewDraftStagesTests(unittest.TestCase):
    def mail_candidate(self):
        from outreach_stages import generate_mails, choose_value_actions, select_reasons
        candidate = {
            "name_hint": "Acme Fietsen",
            "official_domain": "acmefietsen.nl",
            "official_url": "https://acmefietsen.nl/",
            "public_business_email": "info@acmefietsen.nl",
            "research_status": "ready",
            "evidence_candidates": [
                {"text": "Klanten kunnen online een werkplaatsafspraak aanvragen voor onderhoud.",
                 "source_url": "https://acmefietsen.nl/afspraak",
                 "source_type": "official_site", "page_type": "process"},
                {"text": "Vraag online een offerte aan voor reparatie via ons formulier.",
                 "source_url": "https://acmefietsen.nl/offerte",
                 "source_type": "official_site", "page_type": "process"},
                {"text": "Bestel onderdelen online en kies daarna het gewenste afhaalmoment.",
                 "source_url": "https://acmefietsen.nl/bestellen",
                 "source_type": "official_site", "page_type": "process"},
            ],
        }
        return generate_mails(choose_value_actions(select_reasons({
            "candidates": [candidate],
        })))["candidates"][0]

    def test_unverified_person_source_outside_official_domain_is_rejected(self):
        candidate = self.mail_candidate()
        candidate["contact_person_name"] = "Jan Jansen"
        candidate["contact_name_source_url"] = "https://external.example/contact"
        with self.assertRaisesRegex(ValueError, "review_contact_name_source_not_first_party"):
            prepare_review_batch({"candidates": [candidate]})

    def test_stable_lead_id_is_deterministic(self):
        a = stable_lead_id("https://www.acmefietsen.nl/", "INFO@AcmeFietsen.nl")
        b = stable_lead_id("acmefietsen.nl", "info@acmefietsen.nl")
        self.assertEqual(a, b)
        self.assertRegex(a, r"^growth-[0-9a-f]{20}$")

    def test_forged_green_draft_with_two_points_is_rejected(self):
        candidate = self.mail_candidate()
        candidate["selected_findings"] = candidate["selected_findings"][:2]
        with self.assertRaisesRegex(
            ValueError, "review_requires_three_to_six_distinct_improvements"
        ):
            prepare_review_batch({"candidates": [candidate]})

    def test_content_changed_after_mail_approval_is_rejected(self):
        candidate = self.mail_candidate()
        suggested = candidate["selected_findings"][0]["suggested_improvement"]
        candidate["body"] = candidate["body"].replace(suggested, "ongecontroleerde reclame")
        with self.assertRaisesRegex(
            ValueError, "review_missing_source_backed_improvement"
        ):
            prepare_review_batch({"candidates": [candidate]})

    def test_prepare_review_batch_is_review_only(self):
        result = prepare_review_batch({"candidates": [self.mail_candidate()]})
        self.assertEqual(result["draft_candidate_count"], 1)
        row = result["rows"][0]
        self.assertEqual(row["status"], "review_draft")
        self.assertEqual(row["contact_basis_status"], "review_required")
        self.assertFalse(row["automatic_send"])
        self.assertFalse(result["safety"]["automatic_send"])
        self.assertFalse(result["safety"]["smtp_available"])
        self.assertEqual(result["safety"]["changed_existing_draft_policy"], "reject")

    def test_prepare_rejects_duplicate_domain(self):
        first = self.mail_candidate()
        second = {**self.mail_candidate(), "public_business_email": "sales@acmefietsen.nl"}
        with self.assertRaisesRegex(ValueError, "duplicate_review_draft_identity"):
            prepare_review_batch({"candidates": [first, second]})

    def test_prepare_rejects_parent_subdomain_duplicate(self):
        first = self.mail_candidate()
        second = {
            **self.mail_candidate(),
            "name_hint": "Acme Shop",
            "official_domain": "shop.acmefietsen.nl",
            "official_url": "https://shop.acmefietsen.nl/",
            "public_business_email": "sales@shop.acmefietsen.nl",
        }
        with self.assertRaisesRegex(ValueError, "duplicate_review_draft_identity"):
            prepare_review_batch({"candidates": [first, second]})

    def test_readback_requires_exact_to_subject_body_and_review_status(self):
        batch = prepare_review_batch({"candidates": [self.mail_candidate()]})
        row = batch["rows"][0]
        report = {
            "eligible_count": 1,
            "created_count": 1,
            "existing_count": 0,
            "replaced_count": 0,
            "review_required_count": 1,
            "smtp_send": "not_available",
            "items": [{
                "lead_id": row["lead_id"],
                "to": row["email"],
                "subject": row["subject"],
                "body": row["body"],
                "review_status": "contact-basis",
                "outcome": "created",
            }],
        }
        result = audit_exact_readback(batch, report)
        self.assertEqual(result["status"], "green")
        self.assertEqual(result["draft_count"], 1)
        self.assertEqual(result["registry_rows"][0][6], row["lead_id"])
        self.assertEqual(result["registry_rows"][0][9], "TRUE")

    def test_readback_counts_must_match_item_outcomes(self):
        batch = prepare_review_batch({"candidates": [self.mail_candidate()]})
        row = batch["rows"][0]
        report = {
            "eligible_count": 1,
            "created_count": 0,
            "existing_count": 0,
            "replaced_count": 0,
            "review_required_count": 1,
            "smtp_send": "not_available",
            "items": [{
                "lead_id": row["lead_id"],
                "to": row["email"],
                "subject": row["subject"],
                "body": row["body"],
                "review_status": "contact-basis",
                "outcome": "created",
            }],
        }
        with self.assertRaisesRegex(ValueError, "draft_outcome_count_mismatch"):
            audit_exact_readback(batch, report)

    def test_readback_allows_exact_existing_retry_but_never_replacement(self):
        batch = prepare_review_batch({"candidates": [self.mail_candidate()]})
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
        self.assertEqual(audit_exact_readback(batch, report)["existing_count"], 1)
        report["replaced_count"] = 1
        report["items"][0]["outcome"] = "replaced"
        with self.assertRaisesRegex(ValueError, "replacement_not_allowed"):
            audit_exact_readback(batch, report)


if __name__ == "__main__":
    unittest.main()
