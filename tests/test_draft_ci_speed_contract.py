"""Offline checks for the Draft-only performance boundaries."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WorkflowSpeedContract(unittest.TestCase):
    def test_draft_jobs_queue_instead_of_canceling_pending_runs(self):
        workflow = (ROOT / ".github/workflows/myhost-draft.yml").read_text()
        self.assertIn("group: leadscanner-myhost-draft", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("queue: max", workflow)

    def test_replacement_job_uses_only_mailbox_dependencies(self):
        workflow = (ROOT / ".github/workflows/sync450-openings.yml").read_text()
        job = workflow.split("  conversation-replacement:", 1)[1]
        self.assertIn("cache-dependency-path: requirements-draft.txt", job)
        self.assertIn("pip install -r requirements-draft.txt", job)
        self.assertNotIn("pip install -r requirements.txt", job)
        self.assertIn("group: leadscanner-myhost-draft", job)
        self.assertIn("cancel-in-progress: false", job)

    def test_draft_dependencies_exclude_the_discovery_engine(self):
        requirements = (ROOT / "requirements-draft.txt").read_text().lower()
        self.assertIn("google-auth", requirements)
        self.assertIn("requests", requirements)
        self.assertNotIn("overturemaps", requirements)
        workflow = (ROOT / ".github/workflows/myhost-draft.yml").read_text()
        self.assertIn("pip install -r requirements-draft.txt", workflow)
        self.assertIn("cache-dependency-path: requirements-draft.txt", workflow)

    def test_discovery_has_only_explicit_manual_execution(self):
        requirements = (ROOT / "requirements.txt").read_text().lower()
        self.assertIn("overturemaps", requirements)
        workflow = (ROOT / ".github/workflows/fresh-leads.yml").read_text()
        # CI still runs on main pushes and pull requests.
        self.assertIn("  push:", workflow)
        self.assertIn("  pull_request:", workflow)
        self.assertIn("  workflow_dispatch:", workflow)
        self.assertIn("python3 -m unittest discover", workflow)
        self.assertEqual(workflow.count("cache-dependency-path: requirements.txt"), 3)
        self.assertIn("group: leads-private-candidates", workflow)
        self.assertIn("queue: max", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        for forbidden in (
            "  schedule:", "auto_first_drafts:", "auto_draft_preflight:",
            "LEADS_DISCOVERY_ONLY:", "LEADS_PREFLIGHT_ONLY:",
            "LEADS_AUTODRAFT_PREFLIGHT_ONLY:",
            "github.event_name == 'schedule'",
            "requirements-draft.txt", "OUTREACH_MAIL_PASSWORD",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, workflow)

    def test_no_active_workflow_reinstates_the_discontinued_cron(self):
        workflows = ROOT / ".github/workflows"
        self.assertFalse((workflows / "lead-schedule-health.yml").exists())
        for path in workflows.glob("*.yml"):
            with self.subTest(workflow=path.name):
                text = path.read_text()
                self.assertNotIn("\n  schedule:", text)


if __name__ == "__main__":
    unittest.main()
