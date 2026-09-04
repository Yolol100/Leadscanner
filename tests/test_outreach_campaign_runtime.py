import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import outreach_campaign_runtime as r


class OutreachCampaignRuntimeTests(unittest.TestCase):
    def test_sequence_rows_replace_legacy_counting_for_same_lead(self):
        queue = [
            {
                "lead_id": "lead-1",
                "sent_at": "2026-09-04T08:00:00Z",
                "followup_sent_at": "2026-09-04T09:00:00Z",
                "sender_mailbox_id": "m1",
            },
            {
                "lead_id": "lead-2",
                "sent_at": "2026-09-04T08:30:00Z",
                "sender_mailbox_id": "m2",
            },
        ]
        sequence = [
            {"lead_id":"lead-1","step_number":"1","status":"sent","sent_at":"2026-09-04T08:00:00Z","sender_mailbox_id":"m1"},
            {"lead_id":"lead-1","step_number":"2","status":"sent","sent_at":"2026-09-04T09:00:00Z","sender_mailbox_id":"m1"},
            {"lead_id":"lead-1","step_number":"3","status":"sent","sent_at":"2026-09-04T10:00:00Z","sender_mailbox_id":"m1"},
        ]
        events = r.transport_events(queue, sequence)
        self.assertEqual(len(events), 4)
        self.assertEqual(sum(1 for event in events if event[2] == "lead-1"), 3)

    def test_new_lead_count_only_counts_stage_one(self):
        now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
        events = [
            (datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc), "m1", "a", 1),
            (datetime(2026, 9, 4, 9, 0, tzinfo=timezone.utc), "m1", "a", 2),
            (datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc), "m2", "b", 1),
        ]
        self.assertEqual(r.count_initials_today(events, now, "Europe/Amsterdam"), 2)
        self.assertEqual(r.count_events_today(events, now, "Europe/Amsterdam"), 3)

    def test_default_order_prioritizes_followups(self):
        initial = r.Candidate(0, {"lead_id": "a"}, "legacy", 1)
        follow = r.Candidate(1, {"lead_id": "b"}, "legacy", 2)
        ordered = sorted([initial, follow], key=lambda item: r._candidate_sort_key(item, False))
        self.assertEqual([item.stage for item in ordered], [2, 1])

    def test_optional_order_prioritizes_new_leads(self):
        initial = r.Candidate(0, {"lead_id": "a"}, "legacy", 1)
        follow = r.Candidate(1, {"lead_id": "b"}, "legacy", 2)
        ordered = sorted([follow, initial], key=lambda item: r._candidate_sort_key(item, True))
        self.assertEqual([item.stage for item in ordered], [1, 2])


if __name__ == "__main__":
    unittest.main()
