import unittest

from refill_planner import dedupe_candidate_hints, plan_refill


class RefillPlannerTests(unittest.TestCase):
    def base_state(self):
        return {
            "requested_eligible_count": 100,
            "eligible_count": 40,
            "evaluated_count": 80,
            "attempt": 2,
            "max_attempts": 10,
            "elapsed_seconds": 900,
            "time_budget_seconds": 7200,
            "previous_batch_size": 50,
            "source_exhausted": False,
            "candidate_hints": [],
            "seen_candidates": [],
        }

    def test_refill_uses_observed_yield_and_stays_bounded(self):
        result = plan_refill(self.base_state())
        self.assertEqual(result["status"], "refill")
        self.assertEqual(result["next_action"], "discover_more_candidates")
        self.assertEqual(result["next_discovery_count"], 100)
        self.assertFalse(result["safety"]["gates_relaxed_to_hit_target"])
        self.assertFalse(result["safety"]["draftqueue_write"])
        self.assertFalse(result["safety"]["email_send"])

    def test_complete_stops_without_refill(self):
        state = self.base_state()
        state["eligible_count"] = 100
        result = plan_refill(state)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["next_discovery_count"], 0)

    def test_source_exhaustion_stops_without_relaxing_gates(self):
        state = self.base_state()
        state["source_exhausted"] = True
        result = plan_refill(state)
        self.assertEqual(result["status"], "source_exhausted")
        self.assertEqual(result["next_action"], "stop")
        self.assertFalse(result["safety"]["gates_relaxed_to_hit_target"])

    def test_time_and_attempt_caps_fail_closed(self):
        state = self.base_state()
        state["elapsed_seconds"] = 7200
        self.assertEqual(plan_refill(state)["status"], "time_exhausted")

        state = self.base_state()
        state["attempt"] = 10
        self.assertEqual(plan_refill(state)["status"], "attempt_exhausted")

    def test_cross_batch_domain_dedupe_and_contact_field_stripping(self):
        seen = [
            {
                "overture_id": "old-id",
                "official_domain": "https://www.same.example/contact",
                "verified_company_name": "Same BV",
            }
        ]
        hints = [
            {
                "overture_id": "new-id",
                "name_hint": "Same branch",
                "website_hint": "https://same.example/",
                "emails": ["must-not-leak@example.test"],
                "phones": ["+31100000000"],
            },
            {
                "overture_id": "fresh-id",
                "name_hint": "Fresh company",
                "website_hint": "https://fresh.example/",
                "emails": ["must-not-leak@example.test"],
                "socials": ["https://social.example/test"],
            },
        ]
        result = dedupe_candidate_hints(hints, seen)
        self.assertEqual(result["unique_count"], 1)
        self.assertEqual(result["dropped_duplicate_count"], 1)
        serialized = str(result["unique_candidates"])
        self.assertNotIn("must-not-leak@example.test", serialized)
        self.assertNotIn("+31100000000", serialized)
        self.assertNotIn("social.example", serialized)
        self.assertEqual(
            result["unique_candidates"][0]["identity_status"],
            "needs_leads_verification",
        )

    def test_same_domain_inside_one_batch_is_deduplicated(self):
        hints = [
            {
                "overture_id": "one",
                "website_hint": "https://www.example.test/location-a",
                "name_hint": "Location A",
            },
            {
                "overture_id": "two",
                "website_hint": "https://example.test/location-b",
                "name_hint": "Location B",
            },
        ]
        result = dedupe_candidate_hints(hints, [])
        self.assertEqual(result["unique_count"], 1)
        self.assertEqual(result["dropped_duplicate_count"], 1)

    def test_new_unique_batch_is_returned_for_leads_owner_evaluation(self):
        state = self.base_state()
        state["candidate_hints"] = [
            {
                "overture_id": "fresh-id",
                "website_hint": "https://fresh.example/",
                "name_hint": "Fresh company",
            }
        ]
        result = plan_refill(state)
        self.assertEqual(result["status"], "evaluate_batch")
        self.assertEqual(
            result["next_action"],
            "leads_verify_identity_and_run_existing_gates",
        )
        self.assertEqual(result["unique_candidate_count"], 1)
        self.assertEqual(result["next_discovery_count"], 0)

    def test_invalid_bounds_are_blocked(self):
        state = self.base_state()
        state["requested_eligible_count"] = 101
        with self.assertRaises(ValueError):
            plan_refill(state)

        state = self.base_state()
        state["candidate_hints"] = [{"overture_id": str(i)} for i in range(101)]
        with self.assertRaises(ValueError):
            plan_refill(state)


if __name__ == "__main__":
    unittest.main()
