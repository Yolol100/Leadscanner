from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from prospect_campaign_gate import audit_campaign_gate, normalize_target


class ProspectCampaignGateTests(unittest.TestCase):
    def test_matching_campaign_is_counted_without_mutation(self):
        candidates = [{"candidate_id": "1", "status": "qualified", "reason": "ok"}]
        quals = [{"candidate_id": "1", "status": "qualified", "tier": "A", "agent_type": "front_desk_sales"}]
        stats = audit_campaign_gate(candidates, quals, target_agent_type="front_desk_sales")
        self.assertEqual(stats["matched"], 1)
        self.assertEqual(stats["canonical_candidate_state_mutated"], 0)
        self.assertEqual(candidates[0]["status"], "qualified")

    def test_mismatch_is_audited_without_changing_canonical_candidate(self):
        candidates = [{"candidate_id": "1", "status": "qualified", "reason": "ok"}]
        quals = [{"candidate_id": "1", "status": "qualified", "tier": "A", "agent_type": "commerce"}]
        stats = audit_campaign_gate(candidates, quals, target_agent_type="front_desk_sales")
        self.assertEqual(stats["mismatched"], 1)
        self.assertEqual(candidates[0]["status"], "qualified")

    def test_auto_allowed_for_validation_exploration_only(self):
        self.assertEqual(normalize_target("auto"), "auto")
        with self.assertRaises(ValueError):
            normalize_target("auto", allow_auto=False)

    def test_reactivation_requires_explicit_first_party_campaign_flag(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                normalize_target("lead_reactivation")
        with patch.dict(os.environ, {"AGENT_SALES_FIRST_PARTY_REACTIVATION": "true"}, clear=True):
            self.assertEqual(normalize_target("lead_reactivation"), "lead_reactivation")


if __name__ == "__main__":
    unittest.main()