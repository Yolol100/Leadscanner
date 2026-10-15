"""Synthetic cron watchdog tests. No GitHub token, network or mail."""
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock
import schedule_health as h

UTC = timezone.utc


def run(day="2026-10-19T06:25:00Z", state="success", status="completed",
        event="schedule", branch="main"):
    return {"id": 123, "created_at": day,
            "status": status, "conclusion": state,
            "event": event, "head_branch": branch}


def ok_jobs(target="discover", result="success"):
    return [{"name": target, "status": "completed", "conclusion": result}]


class ScheduleHealthTests(unittest.TestCase):
    def test_not_due_before_new_feature_activation(self):
        now = datetime(2026, 10, 16, 5, tzinfo=UTC)
        out = h.check_all(now, api=Mock(side_effect=AssertionError("No API")))
        self.assertEqual([x["status"] for x in out], ["not_due", "not_due"])

    def test_weekend_does_not_require_an_unplanned_run(self):
        now = datetime(2026, 10, 18, 18, tzinfo=UTC)
        out = h.check_all(now, api=Mock(side_effect=AssertionError("No API")))
        self.assertEqual([x["status"] for x in out], ["not_due", "not_due"])

    def test_missing_monday_discovery_is_detected_after_grace(self):
        now = datetime(2026, 10, 19, 14, tzinfo=UTC)
        got = h.evaluate("fresh-leads.yml", (0,), 6, 23, "discover", now,
                         [], lambda _: ok_jobs())
        self.assertEqual(got["status"], "missed")

    def test_recent_workflow_not_confused_with_previous_week(self):
        now = datetime(2026, 10, 26, 14, tzinfo=UTC)
        got = h.evaluate("fresh-leads.yml", (0,), 6, 23, "discover", now,
                         [run()], lambda _: ok_jobs())
        self.assertEqual(got["status"], "missed")

    def test_latest_success_requires_real_discover_job(self):
        now = datetime(2026, 10, 19, 14, tzinfo=UTC)
        self.assertEqual(h.evaluate("fresh-leads.yml", (0,), 6, 23,
                                    "discover", now, [run()],
                                    lambda _: ok_jobs("test"))["status"],
                         "required_job_not_successful")
        self.assertEqual(h.evaluate("fresh-leads.yml", (0,), 6, 23,
                                    "discover", now, [run()],
                                    lambda _: ok_jobs())["status"], "ok")

    def test_concluded_failure_is_never_accepted_as_green(self):
        now = datetime(2026, 10, 19, 14, tzinfo=UTC)
        got = h.evaluate("fresh-leads.yml", (0,), 6, 23, "discover", now,
                         [run(state="failure")], lambda _: ok_jobs())
        self.assertEqual(got["status"], "failed")

    def test_in_progress_is_reported_not_hidden(self):
        now = datetime(2026, 10, 19, 14, tzinfo=UTC)
        got = h.evaluate("fresh-leads.yml", (0,), 6, 23, "discover", now,
                         [run(status="in_progress",state=None)],
                         lambda _: ok_jobs())
        self.assertEqual(got["status"], "unfinished")

    def test_manual_rerun_does_not_mask_missed_cron(self):
        now = datetime(2026, 10, 19, 14, tzinfo=UTC)
        got = h.evaluate("fresh-leads.yml", (0,), 6, 23, "discover", now,
                         [run(event="workflow_dispatch")], lambda _: ok_jobs())
        self.assertEqual(got["status"], "missed")

    def test_wrong_branch_does_not_count_as_production_success(self):
        now = datetime(2026, 10, 19, 14, tzinfo=UTC)
        got = h.evaluate("fresh-leads.yml", (0,), 6, 23, "discover", now,
                         [run(branch="feature")], lambda _: ok_jobs())
        self.assertEqual(got["status"], "missed")

    def test_weekday_evidence_thursday_after_weekend_handling(self):
        now = datetime(2026, 10, 22, 13, tzinfo=UTC)
        expected = h.evaluate("fast-website-evidence.yml", (0,1,2,3,4),
                              7, 17, "research", now,
                              [run(day="2026-10-22T07:25:00Z")],
                              lambda _: ok_jobs("research"))
        self.assertEqual(expected["status"], "ok")

    def test_grace_window_does_not_invent_missing_run(self):
        now = datetime(2026, 10, 19, 7, tzinfo=UTC)
        self.assertEqual(h.evaluate("fresh-leads.yml", (0,), 6, 23,
                                    "discover", now, [],
                                    lambda _: ok_jobs())["status"],
                         "not_due")

    def test_network_failure_is_not_falsely_successful(self):
        now = datetime(2026, 10, 19, 14, tzinfo=UTC)
        with self.assertRaises(RuntimeError):
            h.check_all(now, api=Mock(side_effect=RuntimeError("offline")))


if __name__ == "__main__":
    unittest.main()
