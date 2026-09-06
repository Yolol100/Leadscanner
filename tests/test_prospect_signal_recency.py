from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from prospect_signal_recency import active_signal_score, signal_is_fresh


class ProspectSignalRecencyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)

    def row(self, **overrides):
        data = {
            "candidate_id": "prospect-1",
            "detected_at": (self.now - timedelta(days=5)).isoformat(),
            "evidence_date": "",
            "strength": "2",
            "status": "active",
        }
        data.update(overrides)
        return data

    def test_recent_active_signal_counts(self):
        self.assertEqual(active_signal_score("prospect-1", [self.row()], now=self.now), 2)

    def test_stale_active_signal_does_not_count(self):
        stale = self.row(detected_at=(self.now - timedelta(days=31)).isoformat())
        self.assertFalse(signal_is_fresh(stale, now=self.now))
        self.assertEqual(active_signal_score("prospect-1", [stale], now=self.now), 0)

    def test_evidence_date_takes_priority_over_detection_time(self):
        row = self.row(
            detected_at=(self.now - timedelta(days=1)).isoformat(),
            evidence_date=(self.now - timedelta(days=40)).isoformat(),
        )
        self.assertEqual(active_signal_score("prospect-1", [row], now=self.now), 0)

    def test_invalid_or_future_signal_is_fail_closed(self):
        invalid = self.row(detected_at="not-a-date")
        future = self.row(detected_at=(self.now + timedelta(days=2)).isoformat())
        self.assertEqual(active_signal_score("prospect-1", [invalid, future], now=self.now), 0)

    def test_strength_is_bounded(self):
        self.assertEqual(active_signal_score("prospect-1", [self.row(strength="99")], now=self.now), 2)


if __name__ == "__main__":
    unittest.main()
