import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import myhost_opening_remediation as repair


class OpeningRemediationTests(unittest.TestCase):
    def request(self, mode="audit"):
        value = {
            "mode": mode,
            "source_archive_artifact_id": 1,
            "source_artifact_ids": [2],
            "offset": 0,
            "limit": 1,
        }
        if mode != "audit":
            value["audit_artifact_id"] = 3
        return value

    def test_company_correction_is_bounded(self):
        body = "Hallo,\n\nFeit.\n\nZal ik vrijblijvend een voorbeeld design maken voor Oud?"
        proof = {"old_company_name": "Oud", "company_name": "Nieuw"}
        changed, subject = repair.correct_company_placeholders(body, "Idee voor Oud", proof)
        self.assertIn("voor Nieuw?", changed)
        self.assertEqual(subject, "Idee voor Nieuw")

    def test_apply_reuses_fresh_audit_without_network(self):
        lead_id = "growth-" + "a" * 20
        row = {"lead_id": lead_id, "email": "info@example.nl"}
        website = {
            "status": "ready",
            "verified_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        audit = {"items": [{"lead_id": lead_id, "website": website}]}
        with patch.object(repair, "audit_websites", side_effect=AssertionError("must not refetch")):
            values, stats = repair._resolve_website_results([row], self.request("apply"), audit)
        self.assertEqual(values, [website])
        self.assertEqual(stats["network_rows"], 0)
        self.assertEqual(stats["reused_rows"], 1)

    def test_final_is_mailbox_only(self):
        lead_id = "growth-" + "a" * 20
        row = {"lead_id": lead_id}
        website = {"status": "hold", "verified_at": "2020-01-01T00:00:00Z"}
        audit = {"items": [{"lead_id": lead_id, "website": website}]}
        with patch.object(repair, "audit_websites", side_effect=AssertionError("final must not use network")):
            values, stats = repair._resolve_website_results([row], self.request("final"), audit)
        self.assertEqual(values, [website])
        self.assertTrue(stats["final_mailbox_only"])
        self.assertEqual(stats["network_rows"], 0)

    def test_orchestrated_limit_is_bounded(self):
        req = {
            "mode": "audit",
            "source_archive_artifact_id": 1,
            "source_artifact_ids": [2],
            "offset": 0,
            "limit": 450,
            "orchestrator": True,
            "shard_size": 90,
        }
        self.assertEqual(repair.validate_request(req)["limit"], 450)
        with self.assertRaises(ValueError):
            repair.validate_request({**req, "limit": 501})


if __name__ == "__main__":
    unittest.main()
