from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "leads-verified-drafts.yml"


class VerifiedDraftWorkflowTests(unittest.TestCase):
    def test_selector_dependencies_are_installed_before_selection(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        install = "python3 -m pip install --disable-pip-version-check -r requirements.txt"
        selector = "scripts/build_verified_draft_input.py"
        self.assertIn(install, text)
        self.assertIn(selector, text)
        self.assertLess(text.index(install), text.index(selector))

    def test_registry_exclusions_are_bound_into_selector(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("exclude_companies", text)
        self.assertIn("exclude_domains", text)
        self.assertIn("--exclude-company", text)
        self.assertIn("--exclude-domain", text)
        self.assertIn("results/exclude-companies.txt", text)
        self.assertIn("results/exclude-domains.txt", text)

    def test_verified_draft_workflow_stays_review_only(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("scripts/myhost_growth_inventory.py", text)
        self.assertIn("scripts/myhost_draft.py", text)
        self.assertIn("smtp_send=not_available", text)
        self.assertIn("automatic_send=false", text)
        self.assertNotIn("smtplib", text)
        self.assertNotIn("sendmail(", text)
        self.assertNotIn("SMTP(", text)


if __name__ == "__main__":
    unittest.main()
