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

    def test_existing_queue_id_is_never_refreshed(self):
        self.assertFalse(self.check(queued=["lead-1"]))

    def test_existing_concept_domain_is_not_new(self):
        self.assertFalse(self.check(statuses={"example.com": {"concept"}}))

    def test_b_tier_and_wrong_country_fail_closed(self):
        self.qualification["tier"] = "B"
        self.assertFalse(self.check())
        self.qualification["tier"] = "A"
        self.candidate["country"] = "CA"
        self.assertFalse(self.check())


if __name__ == "__main__":
    unittest.main()
