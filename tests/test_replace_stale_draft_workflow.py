from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "leads-replace-stale-draft.yml"


class ReplaceStaleDraftWorkflowTests(unittest.TestCase):
    def test_replacement_requires_strictly_better_current_recipient(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("email_business_priority", text)
        self.assertIn("new_priority >= old_priority", text)
        self.assertIn("stable_lead_id", text)
        self.assertIn('for field in ("company", "website", "official_domain_hint")', text)

    def test_replacement_proves_new_before_removing_old(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        preflight = "Prove both drafts exist and replacement is exact"
        removal = "Remove only the stale old draft"
        final = "Final replacement readback"
        self.assertIn(preflight, text)
        self.assertIn(removal, text)
        self.assertIn(final, text)
        self.assertLess(text.index(preflight), text.index(removal))
        self.assertLess(text.index(removal), text.index(final))
        self.assertIn("exact_message_matches", text)

    def test_replacement_never_exposes_send_surface(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("automatic_send=false", text)
        self.assertIn("smtp_send=not_available", text)
        self.assertNotIn("smtplib", text)
        self.assertNotIn("sendmail(", text)
        self.assertNotIn("SMTP(", text)


if __name__ == "__main__":
    unittest.main()
