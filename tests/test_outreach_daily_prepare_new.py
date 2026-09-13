import unittest

import outreach_daily_prepare_new as daily_new


class DailyPrepareNewTests(unittest.TestCase):
    def setUp(self):
        self.candidate = {
            "candidate_id": "lead-1",
            "website": "https://example.com/",
            "country": "US",
            "status": "qualified",
        }
        self.qualification = {
            "candidate_id": "lead-1",
            "status": "qualified",
            "tier": "A",
            "offer_family": "ai_agent",
            "agent_type": "quote_intake",
            "customer_potential": "8",
        }
        self.contact = {
            "candidate_id": "lead-1",
            "status": "ready",
            "email": "info@example.com",
            "source_url": "https://example.com/contact/",
            "domain_alignment": "aligned",
            "mx_status": "present",
        }

    def check(self, *, queued=None, statuses=None):
        return daily_new.eligible(
            self.candidate,
            self.qualification,
            self.contact,
            agent_type="quote_intake",
            country="US",
            queued_ids=set(queued or []),
            lead_statuses=statuses or {},
        )

    def test_new_a_ready_candidate_is_eligible(self):
        self.assertTrue(self.check())

    def test_new_b_hold_candidate_is_eligible_for_manual_review_draft(self):
        self.candidate["status"] = "hold"
        self.qualification["status"] = "hold"
        self.qualification["tier"] = "B"
        self.qualification["customer_potential"] = "7"
        self.assertTrue(self.check())

    def test_official_external_business_contact_with_mx_is_eligible(self):
        self.contact["status"] = "manual_review"
        self.contact["email"] = "sales@external-mail.example"
        self.contact["domain_alignment"] = "external_domain"
        self.assertTrue(self.check())

    def test_external_contact_without_official_source_or_mx_fails_closed(self):
        self.contact["status"] = "manual_review"
        self.contact["domain_alignment"] = "external_domain"
        self.contact["source_url"] = "https://directory.example.net/company"
        self.assertFalse(self.check())
        self.contact["source_url"] = "https://example.com/contact/"
        self.contact["mx_status"] = "unknown"
        self.assertFalse(self.check())

    def test_existing_queue_id_is_never_refreshed(self):
        self.assertFalse(self.check(queued=["lead-1"]))

    def test_existing_concept_domain_is_not_new(self):
        self.assertFalse(self.check(statuses={"example.com": {"concept"}}))

    def test_wrong_country_and_c_tier_fail_closed(self):
        self.candidate["country"] = "CA"
        self.assertFalse(self.check())
        self.candidate["country"] = "US"
        self.candidate["status"] = "rejected"
        self.qualification["status"] = "rejected"
        self.qualification["tier"] = "C"
        self.qualification["customer_potential"] = "5"
        self.assertFalse(self.check())


if __name__ == "__main__":
    unittest.main()
