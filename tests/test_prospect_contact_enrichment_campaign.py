from __future__ import annotations

import unittest

import prospect_contact_enrichment_campaign as c


class CampaignContactFilterTests(unittest.TestCase):
    def setUp(self):
        c._qualification_by_id = {
            "1": {"candidate_id": "1", "status": "qualified", "tier": "A", "agent_type": "front_desk_sales"},
            "2": {"candidate_id": "2", "status": "qualified", "tier": "A", "agent_type": "commerce"},
        }
        c._target_agent_type = "front_desk_sales"

    def test_only_matching_campaign_agent_reaches_contact_research(self):
        rows = [
            {"candidate_id": "1", "status": "qualified", "website": "https://one.test"},
            {"candidate_id": "2", "status": "qualified", "website": "https://two.test"},
        ]
        eligible = c.campaign_eligible_prospects(rows, set(), 10)
        self.assertEqual([row["candidate_id"] for row in eligible], ["1"])

    def test_auto_is_backward_compatible(self):
        c._target_agent_type = "auto"
        rows = [
            {"candidate_id": "1", "status": "qualified", "website": "https://one.test"},
            {"candidate_id": "2", "status": "qualified", "website": "https://two.test"},
        ]
        eligible = c.campaign_eligible_prospects(rows, set(), 10)
        self.assertEqual([row["candidate_id"] for row in eligible], ["1", "2"])


if __name__ == "__main__":
    unittest.main()