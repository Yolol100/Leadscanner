"""Read-only GitHub Actions schedule watchdog; no lead or mailbox access.

A failed job or a missed schedule becomes a failing Actions check. It never
reruns discoveries automatically, writes a public issue or sends email.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen

UTC = timezone.utc
START = datetime(2026, 10, 16, tzinfo=UTC)
GRACE = timedelta(hours=5)
REPO = "Yolol100/Leadscanner"
# Name, UTC weekday (Mon=0), expected time, and required job.
SCHEDULES = (
    ("fresh-leads.yml", (0,), 6, 23, "discover"),
    ("fast-website-evidence.yml", (0, 1, 2, 3, 4), 7, 17, "research"),
)


def _moment(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def _latest_due(now, days, hour, minute):
    for delta in range(9):
        d = (now - timedelta(days=delta)).date()
        if d.weekday() not in days:
            continue
        planned = datetime(d.year, d.month, d.day, hour, minute, tzinfo=UTC)
        if planned + GRACE <= now:
            return planned
    return None


def evaluate(name, days, hour, minute, required_job, now, runs, jobs_for_run):
    """Pure decision routine; statuses only, never secrets or prospect fields."""
    due = _latest_due(now, days, hour, minute)
    if due is None or due < START:
        return {"workflow": name, "status": "not_due"}
    eligible = [r for r in runs
                if r.get("event") == "schedule" and
                r.get("head_branch") == "main" and
                r.get("created_at") and
                due - timedelta(minutes=5) <= _moment(r["created_at"]) <= now]
    if not eligible:
        return {"workflow": name, "status": "missed"}
    latest = max(eligible, key=lambda r: _moment(r["created_at"]))
    # Scheduled Actions can lag; do not claim successful health while running.
    if latest.get("status") != "completed":
        return {"workflow": name, "status": "unfinished"}
    if latest.get("conclusion") != "success":
        return {"workflow": name, "status": "failed"}
    jobs = jobs_for_run(latest["id"])
    if not any(j.get("name") == required_job and
               j.get("status") == "completed" and
               j.get("conclusion") == "success" for j in jobs):
        return {"workflow": name, "status": "required_job_not_successful"}
    return {"workflow": name, "status": "ok"}


def _api(path, token):
    req = Request("https://api.github.com/repos/" + REPO + path,
                  headers={"Authorization": "Bearer " + token,
                           "Accept": "application/vnd.github+json",
                           "X-GitHub-Api-Version": "2022-11-28",
                           "User-Agent": "leadscanner-readonly-schedule-health"})
    with urlopen(req, timeout=25) as response:
        return json.load(response)


def check_all(now=None, api=None):
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("timezone-aware UTC timestamp required")
    now = now.astimezone(UTC)
    if api is None:
        token = os.getenv("GITHUB_TOKEN", "")
        if not token:
            raise RuntimeError("schedule_watch_token_missing")
        api = lambda path: _api(path, token)
    result = []
    for name, days, hour, minute, target in SCHEDULES:
        if _latest_due(now, days, hour, minute) is None or (
                _latest_due(now, days, hour, minute) < START):
            result.append({"workflow": name, "status": "not_due"})
            continue
        pathname = quote(name, safe="")
        runs = api("/actions/workflows/" + pathname +
                   "/runs?event=schedule&per_page=20").get("workflow_runs", [])
        cache = {}
        def jobs(run_id):
            if run_id not in cache:
                cache[run_id] = api("/actions/runs/" + str(run_id) +
                                    "/jobs?per_page=100").get("jobs", [])
            return cache[run_id]
        result.append(evaluate(name, days, hour, minute, target, now,
                               runs, jobs))
    return result


def main():
    try:
        checks = check_all()
        # No company names, emails, credentials, URLs from sources or mail copy.
        print(json.dumps({"checks": checks}, sort_keys=True))
        return 0 if all(x["status"] in ("ok", "not_due") for x in checks) else 1
    except Exception:
        print('{"status":"watchdog_unavailable"}')
        return 1


if __name__ == "__main__":
    sys.exit(main())
