import unittest

from funnel_metrics import build_funnel


class FunnelMetricsTests(unittest.TestCase):
    def test_builds_privacy_safe_reason_breakdown(self):
        result = build_funnel(
            raw={"candidate_count": 10},
            filtered={
                "candidate_count": 8,
                "excluded": [
                    {"reason": "missing_name_or_website"},
                    {"reason": "duplicate_domain_in_discovery"},
                ],
            },
            dedupe={
                "kept_count": 6,
                "excluded": [
                    {"dedupe_match": {"matched_by": ["domain"]}},
                    {"dedupe_match": {"matched_by": ["company", "email"]}},
                ],
            },
            verified={
                "candidate_count": 6,
                "ready_for_research_count": 3,
                "candidates": [
                    {"ready_for_research": True, "contact_status": "verified_official_site"},
                    {"ready_for_research": True, "contact_status": "verified_official_site"},
                    {"ready_for_research": True, "contact_status": "verified_official_site"},
                    {"ready_for_research": False, "contact_status": "hold_no_public_business_email"},
                    {"ready_for_research": False, "contact_status": "hold_identity_not_proven"},
                    {"ready_for_research": False, "contact_status": "hold_no_public_business_email"},
                ],
            },
            research={
                "candidate_count": 3,
                "research_ready_count": 2,
                "candidates": [
                    {"research_status": "ready"},
                    {"research_status": "ready"},
                    {"research_status": "hold_no_first_party_evidence"},
                ],
            },
            reasons={
                "ready_count": 1,
                "candidates": [
                    {"outreach_status": "ready", "signal_type": "appointment"},
                    {"outreach_status": "hold", "outreach_hold_reason": "weak_generic_marketing_signal"},
                ],
            },
            mail={
                "ready_for_human_review_count": 1,
                "candidates": [
                    {"mail_status": "ready_for_human_review"},
                    {"mail_status": "hold", "copy_validation_reasons": ["value_action_not_ready"]},
                ],
            },
        )
        self.assertEqual(result["counts"]["discovery_raw"], 10)
        self.assertEqual(result["drop_reasons"]["dedupe"]["domain"], 1)
        self.assertEqual(result["drop_reasons"]["dedupe"]["company"], 1)
        self.assertEqual(result["drop_reasons"]["verification"]["hold_no_public_business_email"], 2)
        self.assertEqual(result["drop_reasons"]["outreach"]["weak_generic_marketing_signal"], 1)
        self.assertEqual(result["ready_signal_types"], {"appointment": 1})
        self.assertFalse(result["privacy"]["contains_email_addresses"])
        self.assertFalse(result["privacy"]["contains_company_names"])


if __name__ == "__main__":
    unittest.main()
