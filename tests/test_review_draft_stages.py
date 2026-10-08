import unittest

from review_draft_stages import audit_exact_readback, prepare_review_batch, stable_lead_id


class ReviewDraftStagesTests(unittest.TestCase):
    def mail_candidate(self):
        return {
            "name_hint": "Acme Fietsen",
            "official_domain": "acmefietsen.nl",
            "official_url": "https://acmefietsen.nl/",
            "public_business_email": "info@acmefietsen.nl",
            "subject": "idee voor jullie afspraakroute",
            "body": "Hallo,\n\nKorte gecontroleerde mail.\n\nGroet,\nAndrew",
            "mail_status": "ready_for_human_review",
            "copy_validation_status": "green",
            "automatic_send": False,
            "verified_observation": "Klanten kunnen online een afspraak aanvragen.",
            "verified_observation_source_url": "https://acmefietsen.nl/afspraak",
            "verified_observation_source_type": "official_site",
            "signal_type": "appointment",
            "value_first_action": "een korte voorbeeldvariant voor de afspraakroute",
        }

    def test_sequence_facts_review_requires_official_site_and_no_email_copy(self):
        candidate = self.mail_candidate()
        candidate.update({
            "review_mode": "instantly_sequence",
            "mail_status": "ready_for_sequence_review",
            "copy_validation_status": "not_applicable",
            "subject": None,
            "body": None,
            "outreach_status": "ready",
            "value_action_status": "proposed",
        })
        batch = prepare_review_batch({"candidates": [candidate]})
        self.assertEqual(batch["sequence_facts_review_count"], 1)
        self.assertEqual(batch["review_draft_count"], 0)
        row = batch["rows"][0]
        self.assertEqual(row["status"], "sequence_facts_review")
        self.assertEqual(row["subject"], "")
        self.assertEqual(row["body"], "")
        self.assertEqual(row["review_mode"], "instantly_sequence")
        with self.assertRaisesRegex(ValueError, "sequence_facts_cannot_be_stored_as_mailbox_drafts"):
            audit_exact_readback(batch, {"items": []})

    def test_sequence_facts_reject_cross_domain_and_fake_copy(self):
        candidate = self.mail_candidate()
        candidate.update({
            "review_mode": "instantly_sequence",
            "mail_status": "ready_for_sequence_review",
            "copy_validation_status": "not_applicable",
            "subject": None,
            "body": None,
            "outreach_status": "ready",
            "value_action_status": "proposed",
            "verified_observation_source_url": "https://unrelated.example/afspraak",
        })
        with self.assertRaisesRegex(ValueError, "sequence_facts_require_verified_official_site_evidence"):
            prepare_review_batch({"candidates": [candidate]})
        candidate["verified_observation_source_url"] = "https://acmefietsen.nl/afspraak"
        candidate["body"] = "unapproved generated mail"
        with self.assertRaisesRegex(ValueError, "sequence_facts_require_verified_official_site_evidence"):
            prepare_review_batch({"candidates": [candidate]})

    def test_stable_lead_id_is_deterministic(self):
        a = stable_lead_id("https://www.acmefietsen.nl/", "INFO@AcmeFietsen.nl")
        b = stable_lead_id("acmefietsen.nl", "info@acmefietsen.nl")
        self.assertEqual(a, b)
        self.assertRegex(a, r"^growth-[0-9a-f]{20}$")

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
