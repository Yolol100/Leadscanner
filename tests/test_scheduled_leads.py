"""No-network tests for scheduled lead-region rotation and campaign stopping."""
import contextlib
from datetime import date, timedelta
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from scheduled_region_rotation import REGIONS, REGIONS_PER_DAY, scheduled_regions
from test_verified_fill_100 import hint, approved
import verified_fill


class ScheduledLeadTests(unittest.TestCase):
    def test_eight_days_cover_unique_regions_without_adjacent_overlap(self):
        self.assertEqual(len(REGIONS), 64)
        self.assertEqual(len(set(REGIONS)), 64)
        start = date(2024, 1, 2)
        batches = [scheduled_regions(start + timedelta(days=n)) for n in range(8)]
        self.assertTrue(all(len(group) == REGIONS_PER_DAY for group in batches))
        self.assertEqual(len(set(name for group in batches for name in group)), 64)
        self.assertEqual(set(scheduled_regions(start)),
                         set(scheduled_regions(start + timedelta(days=8))))
        self.assertNotEqual(scheduled_regions(start),
                            scheduled_regions(start + timedelta(days=8)))
        self.assertEqual(scheduled_regions(start),
                         scheduled_regions(start + timedelta(days=64)))

    def test_auto_region_still_checks_suppression_before_discovery(self):
        calls = []
        def registry():
            calls.append("registry")
            return []
        def discoverer(**kwargs):
            calls.append(kwargs["region"])
            return {"candidates": [hint(len(calls))]}
        with patch.object(verified_fill, "scheduled_regions",
                          return_value=("Delft", "Breda")):
            result = verified_fill.fill_verified(
                "auto", ["vakbedrijven"], 25, target=2,
                discoverer=discoverer, verifier=approved, load_registry=registry)
        self.assertEqual(calls, ["registry", "Delft", "Breda"])
        self.assertEqual(result["counts"]["approved"], 2)
        self.assertEqual(result["emails_sent"], 0)

    def test_scheduled_run_stops_without_websites_at_goal(self):
        with patch.dict(os.environ, {
                "GITHUB_EVENT_NAME": "schedule",
                "LEAD_CAMPAIGN_SINCE_UTC": "2024-01-01T00:00:00Z",
                "LEAD_CAMPAIGN_GOAL": "100"}, clear=True), \
             patch("lead_campaign_counter.remaining", return_value=0), \
             patch.object(verified_fill, "fill_verified") as fetch:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(verified_fill._single(), 0)
        fetch.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["status"], "goal_reached")

    def test_scheduled_missing_goal_configuration_fails_closed(self):
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule"}, clear=True), \
             patch.object(verified_fill, "fill_verified") as fetch:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(verified_fill._single(), 1)
        fetch.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["status"], "blocked")

    def test_scheduled_partial_success_is_not_marked_as_python_failure(self):
        result = {
            "approved": [], "complete": False,
            "counts": {"approved": 0, "sites_checked": 240},
            "timings": {"total_s": 0.0},
        }
        with patch.dict(os.environ, {
                "GITHUB_EVENT_NAME": "schedule",
                "LEAD_CAMPAIGN_SINCE_UTC": "2024-01-01T00:00:00Z",
                "LEAD_CAMPAIGN_GOAL": "100",
                "REGION": "auto", "KEYWORDS": "vakbedrijven", "RADIUS": "25",
            }, clear=True), \
             patch("lead_campaign_counter.remaining", return_value=73), \
             patch.object(verified_fill, "fill_verified", return_value=result) as fetch:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(verified_fill._single(), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "partial")
        self.assertEqual(fetch.call_args.kwargs["target"], 73)
        self.assertEqual(fetch.call_args.kwargs["max_site_checks"], 240)

    def test_workflow_retains_manual_mode_and_adds_schedule(self):
        config = (Path(__file__).resolve().parents[1] /
                  ".github/workflows/fresh-leads.yml").read_text(encoding="utf-8")
        self.assertIn("  schedule:\n    - cron: '17 4 * * *'", config)
        self.assertIn("  workflow_dispatch:", config)
        self.assertIn("LEAD_CAMPAIGN_SINCE_UTC: ${{ vars.LEAD_CAMPAIGN_SINCE_UTC }}", config)
        self.assertIn("LEAD_CAMPAIGN_GOAL: ${{ vars.LEAD_CAMPAIGN_GOAL }}", config)
        self.assertIn("github.event_name == 'schedule'", config)
        self.assertIn("'auto' || inputs.region", config)


if __name__ == "__main__":
    unittest.main()
