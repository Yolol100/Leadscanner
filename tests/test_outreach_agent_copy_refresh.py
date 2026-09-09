from __future__ import annotations

import json
import unittest

from outreach_agent_copy_refresh import merge_refreshed_copy


class CopyRefreshTests(unittest.TestCase):
    def base(self, contract: str):
        return {
            "lead_id": "prospect-1",
            "company": "Example Co",
            "website": "https://example.com/",
            "email": "sales@example.com",
            "status": "manual_review",
            "compliance_status": "approved",
            "compliance_basis": "other_verified_basis",
            "opt_out_mode": "reply_optout",
            "stage": "1",
            "sender_mailbox_id": "primary",
            "sender_email": "info@andrewbaeten.nl",
            "source": "agent_offer:" + json.dumps({"agent_type": "quote_intake", "copy_contract": contract}),
        }

    def test_refresh_preserves_independent_gates_and_promotes_copy_contract_only(self):
        old = self.base("human_v13_4")
        old.update({"subject": "old", "body": "old body", "last_error": "stale"})
        new = self.base("evidence_personalized_v13_5")
        new.update({"subject": "new", "body": "new body", "followup_body": "new followup", "verification_status": "official_site_ready"})
        merged = merge_refreshed_copy(old, new)
        self.assertEqual(merged["subject"], "new")
        self.assertEqual(merged["body"], "new body")
        self.assertEqual(merged["status"], "manual_review")
        self.assertEqual(merged["compliance_status"], "approved")
        self.assertEqual(merged["compliance_basis"], "other_verified_basis")
        self.assertEqual(merged["last_error"], "")

    def test_refresh_blocks_agent_switch(self):
        old = self.base("human_v13_4")
        new = self.base("evidence_personalized_v13_5")
        new["source"] = "agent_offer:" + json.dumps({"agent_type": "commerce", "copy_contract": "evidence_personalized_v13_5"})
        with self.assertRaises(RuntimeError):
            merge_refreshed_copy(old, new)

    def test_refresh_blocks_terminal_row(self):
        old = self.base("human_v13_4")
        old["sent_at"] = "2026-09-09T10:00:00Z"
        new = self.base("evidence_personalized_v13_5")
        with self.assertRaises(RuntimeError):
            merge_refreshed_copy(old, new)


if __name__ == "__main__":
    unittest.main()
