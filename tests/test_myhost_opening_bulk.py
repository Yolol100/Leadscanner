import unittest
from pathlib import Path
from unittest.mock import patch

import myhost_opening_bulk as bulk
from myhost_opening_remediation import validate_request


class OpeningBulkTests(unittest.TestCase):
    def test_450_becomes_five_bounded_shards_of_90(self):
        rows = [{"lead_id": f"growth-{i:020x}"} for i in range(450)]
        shards = bulk._split_rows(rows, 90)
        self.assertEqual([len(shard) for shard in shards], [90, 90, 90, 90, 90])
        self.assertTrue(all(len(shard) <= 100 for shard in shards))

    def test_bulk_request_can_be_450_but_single_run_cannot(self):
        base = {
            "mode": "audit",
            "source_archive_artifact_id": 1,
            "source_artifact_ids": [2],
            "offset": 0,
        }
        self.assertEqual(validate_request({**base, "limit": 450, "orchestrator": True, "shard_size": 90})["limit"], 450)
        with self.assertRaises(ValueError):
            validate_request({**base, "limit": 101})

    def test_audit_uses_one_shared_website_auditor_then_bounded_shard_runs(self):
        rows = [{"lead_id": f"growth-{i:020x}"} for i in range(450)]
        req = {
            "mode": "audit",
            "source_archive_artifact_id": 1,
            "source_artifact_ids": [2],
            "offset": 0,
            "limit": 450,
            "orchestrator": True,
            "shard_size": 90,
        }
        website = [[{"status": "hold", "verified_at": "2026-10-06T16:00:00Z"}] * 90 for _ in range(5)]
        seen = []

        def fake_run(shard_req, source_root, audit=None, precomputed_website_results=None):
            seen.append((shard_req["offset"], shard_req["limit"], len(precomputed_website_results or [])))
            return {
                "mode": "audit", "items": [{"status": "hold"}] * shard_req["limit"],
                "ready_count": 0, "hold_count": shard_req["limit"], "absent_count": 0,
                "changed_count": 0, "already_correct_count": 0, "removed_count": 0,
                "blockers": [], "website_network_rows": 0, "website_reused_rows": shard_req["limit"],
            }

        with patch.object(bulk, "_selected_rows", return_value=rows), \
             patch.object(bulk, "audit_website_shards", return_value=website) as audit_web, \
             patch.object(bulk, "run", side_effect=fake_run):
            report = bulk.run_bulk(req, Path("."))
        audit_web.assert_called_once()
        self.assertEqual(seen, [(0, 90, 90), (90, 90, 90), (180, 90, 90), (270, 90, 90), (360, 90, 90)])
        self.assertEqual(report["audited_count"], 450)
        self.assertEqual(report["shard_count"], 5)


if __name__ == "__main__":
    unittest.main()
