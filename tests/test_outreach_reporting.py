import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import outreach_reporting as r


class OutreachReportingTests(unittest.TestCase):
    def test_reply_is_attributed_to_latest_sent_variant_before_reply(self):
        queue = [{"lead_id":"lead-1","status":"replied","reply_at":"2026-09-04T11:00:00Z"}]
        sequence = [
            {"lead_id":"lead-1","sequence_id":"seq","sequence_version":"1","step_number":"1","variant_id":"A","status":"sent","sent_at":"2026-09-04T08:00:00Z"},
            {"lead_id":"lead-1","sequence_id":"seq","sequence_version":"1","step_number":"2","variant_id":"B","status":"sent","sent_at":"2026-09-04T10:00:00Z"},
        ]
        rows = r.build_variant_rows(queue, sequence, generated_at=datetime(2026,9,4,12,0,tzinfo=timezone.utc), min_samples=5)
        by_variant = {(row["step_number"], row["variant_id"]): row for row in rows}
        self.assertEqual(by_variant[("1","A")]["replies_attributed"], "0")
        self.assertEqual(by_variant[("2","B")]["replies_attributed"], "1")

    def test_variant_recommendation_is_advisory(self):
        queue, sequence = [], []
        for i in range(10):
            lead=f"a-{i}"; sequence.append({"lead_id":lead,"sequence_id":"seq","sequence_version":"1","step_number":"1","variant_id":"A","status":"sent","sent_at":"2026-09-04T08:00:00Z"}); queue.append({"lead_id":lead,"status":"replied" if i<4 else "sent","reply_at":"2026-09-04T09:00:00Z" if i<4 else ""})
        for i in range(10):
            lead=f"b-{i}"; sequence.append({"lead_id":lead,"sequence_id":"seq","sequence_version":"1","step_number":"1","variant_id":"B","status":"sent","sent_at":"2026-09-04T08:00:00Z"}); queue.append({"lead_id":lead,"status":"sent","reply_at":""})
        rows = r.build_variant_rows(queue, sequence, generated_at=datetime(2026,9,4,12,0,tzinfo=timezone.utc), min_samples=5)
        by_variant = {row["variant_id"]: row for row in rows}
        self.assertEqual(by_variant["A"]["recommendation"], "leader")
        self.assertEqual(by_variant["B"]["recommendation"], "review")
        self.assertIn("owner review", by_variant["B"]["note"])

    def test_mailbox_health_does_not_claim_warmup_health(self):
        queue = [{"lead_id":"lead-1","sender_mailbox_id":"m1","sender_email":"a@example.com","sent_at":"2026-09-04T08:00:00Z","status":"sent"}]
        rows = r.build_mailbox_health_rows(queue, [], generated_at=datetime(2026,9,4,12,0,tzinfo=timezone.utc), timezone_name="Europe/Amsterdam")
        self.assertEqual(rows[0]["state"], "insufficient_data")
        self.assertIn("not a warmup", rows[0]["note"])


if __name__ == "__main__": unittest.main()
