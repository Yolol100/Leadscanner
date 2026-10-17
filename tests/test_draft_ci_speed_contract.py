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

    def test_discovery_still_uses_overture_with_caching(self):
        requirements = (ROOT / "requirements.txt").read_text().lower()
        self.assertIn("overturemaps", requirements)
        workflow = (ROOT / ".github/workflows/fresh-leads.yml").read_text()
        self.assertIn("queue: max", workflow)
        # The heavy Overture dependency belongs to discovery, never the
        # scheduled IMAP/Draft Queue jobs or the metadata-only canary.
        self.assertEqual(workflow.count("cache-dependency-path: requirements.txt"), 3)
        draft, preflight = workflow.split("  auto_first_drafts:", 1)[1].split(
            "  auto_draft_preflight:", 1)
        for job in (draft, preflight):
            self.assertIn("pip install -r requirements-draft.txt", job)
            self.assertIn("cache-dependency-path: requirements-draft.txt", job)
            self.assertNotIn("pip install -r requirements.txt", job)
        self.assertIn("python3 -m unittest discover", workflow)


if __name__ == "__main__":
    unittest.main()
