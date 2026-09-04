import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import outreach_campaign_policy as p


class OutreachCampaignPolicyTests(unittest.TestCase):
    def test_natural_pacing_reduces_run_to_one(self):
        decision = p.decide_policy(
            now=datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc),
            timezone_name="Europe/Amsterdam",
            mode="live",
            daily_limit=20,
            max_sends_per_run=5,
            natural_pacing=True,
            campaign_start_date=None,
            campaign_end_date=None,
            slow_ramp_enabled=False,
            ramp_start_date=None,
            ramp_start_limit=2,
            ramp_increment_per_day=2,
        )
        self.assertEqual(decision.effective_max_sends_per_run, 1)
        self.assertEqual(decision.effective_daily_limit, 20)
        self.assertEqual(decision.effective_mode, "live")

    def test_slow_ramp_matches_two_per_day_growth(self):
        decision = p.decide_policy(
            now=datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc),
            timezone_name="Europe/Amsterdam",
            mode="live",
            daily_limit=30,
            max_sends_per_run=2,
            natural_pacing=False,
            campaign_start_date=None,
            campaign_end_date=None,
            slow_ramp_enabled=True,
            ramp_start_date=date(2026, 9, 4),
            ramp_start_limit=2,
            ramp_increment_per_day=2,
        )
        self.assertEqual(decision.ramp_day, 4)
        self.assertEqual(decision.effective_daily_limit, 8)

    def test_slow_ramp_never_exceeds_configured_daily_limit(self):
        decision = p.decide_policy(
            now=datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc),
            timezone_name="Europe/Amsterdam",
            mode="live",
            daily_limit=20,
            max_sends_per_run=2,
            natural_pacing=False,
            campaign_start_date=None,
            campaign_end_date=None,
            slow_ramp_enabled=True,
            ramp_start_date=date(2026, 9, 1),
            ramp_start_limit=2,
            ramp_increment_per_day=2,
        )
        self.assertEqual(decision.effective_daily_limit, 20)

    def test_future_campaign_fails_closed_for_live_but_keeps_validation(self):
        decision = p.decide_policy(
            now=datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc),
            timezone_name="Europe/Amsterdam",
            mode="live",
            daily_limit=20,
            max_sends_per_run=2,
            natural_pacing=False,
            campaign_start_date=date(2026, 9, 10),
            campaign_end_date=None,
            slow_ramp_enabled=False,
            ramp_start_date=None,
            ramp_start_limit=2,
            ramp_increment_per_day=2,
        )
        self.assertFalse(decision.send_allowed)
        self.assertEqual(decision.reason, "campaign_not_started")
        self.assertEqual(decision.effective_mode, "validate")

    def test_ended_campaign_fails_closed_for_live(self):
        decision = p.decide_policy(
            now=datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc),
            timezone_name="Europe/Amsterdam",
            mode="live",
            daily_limit=20,
            max_sends_per_run=2,
            natural_pacing=False,
            campaign_start_date=None,
            campaign_end_date=date(2026, 9, 9),
            slow_ramp_enabled=False,
            ramp_start_date=None,
            ramp_start_limit=2,
            ramp_increment_per_day=2,
        )
        self.assertFalse(decision.send_allowed)
        self.assertEqual(decision.reason, "campaign_ended")
        self.assertEqual(decision.effective_mode, "validate")

    def test_invalid_boolean_is_rejected(self):
        with self.assertRaises(ValueError):
            p.parse_bool("maybe", name="TEST_FLAG")

    def test_slow_ramp_requires_explicit_start_date(self):
        with self.assertRaises(ValueError):
            p.decide_policy(
                now=datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc),
                timezone_name="Europe/Amsterdam",
                mode="live",
                daily_limit=20,
                max_sends_per_run=2,
                natural_pacing=False,
                campaign_start_date=None,
                campaign_end_date=None,
                slow_ramp_enabled=True,
                ramp_start_date=None,
                ramp_start_limit=2,
                ramp_increment_per_day=2,
            )


if __name__ == "__main__":
    unittest.main()
