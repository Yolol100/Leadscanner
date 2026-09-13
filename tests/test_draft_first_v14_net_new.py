from __future__ import annotations

import json
import os
import py_compile
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import outreach_daily_draft_first as daily
import outreach_daily_draft_first_retry as daily_retry
import outreach_draft_first_baseline as baseline


class DraftFirstV14NetNewTests(unittest.TestCase):
    def _candidate(self, lead_id: str, website: str, email: str):
        return daily.base.Candidate(
            lead_id=lead_id,
            company=lead_id,
            website=website,
            email=email,
            subject="Idea",
            body="Body",
            country="NL",
            anchor="quote intake",
            score=8,
        )

    def test_baseline_script_compiles(self):
        py_compile.compile("scripts/outreach_draft_first_baseline.py", doraise=True)

    def test_net_new_filter_excludes_pre_run_id_domain_and_email(self):
        old_id = self._candidate("lead-old", "https://fresh-id.example", "id@fresh-id.example")
        old_domain = self._candidate("lead-domain", "https://old.example", "domain@fresh.example")
        old_email = self._candidate("lead-email", "https://fresh-email.example", "known@example.net")
        fresh = self._candidate("lead-fresh", "https://fresh.example", "hello@fresh.example")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "baseline.json"
            path.write_text(
                json.dumps({
                    "lead_ids": ["lead-old"],
                    "domains": ["old.example"],
                    "emails": ["known@example.net"],
                }),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {
                "DRAFT_FIRST_BASELINE_FILE": str(path),
                "DRAFT_FIRST_REQUIRE_NET_NEW": "true",
            }, clear=False):
                accepted, rejected = daily_retry._filter_net_new(
                    [old_id, old_domain, old_email, fresh], {}
                )
        self.assertEqual(["lead-fresh"], [item.lead_id for item in accepted])
        self.assertIn("not net-new versus pre-run baseline", rejected["lead-old"])
        self.assertIn("not net-new versus pre-run baseline", rejected["lead-domain"])
        self.assertIn("not net-new versus pre-run baseline", rejected["lead-email"])

    def test_required_baseline_missing_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "missing.json")
            with patch.dict(os.environ, {
                "DRAFT_FIRST_BASELINE_FILE": missing,
                "DRAFT_FIRST_REQUIRE_NET_NEW": "true",
            }, clear=False):
                with self.assertRaises(RuntimeError):
                    daily_retry._load_net_new_baseline()

    def test_capture_combines_queue_prospect_contact_and_lead_history(self):
        rows = {
            "OutreachQueue": [{"lead_id": "queue-1", "website": "https://queue.example", "email": "queue@example.com"}],
            "ProspectCandidates": [{"candidate_id": "prospect-1", "website": "https://prospect.example"}],
            "ContactCandidates": [{"candidate_id": "contact-1", "website": "https://contact.example", "email": "contact@example.com"}],
            "Leadlijst": [{"Website": "https://history.example", "E-mail": "history@example.com"}],
        }

        def fake_rows(service, spreadsheet_id, sheet):
            return rows[sheet]

        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "baseline.json")
            with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": "{}"}, clear=False), \
                 patch.object(baseline, "build_sheets_service", return_value=object()), \
                 patch.object(baseline, "_rows", side_effect=fake_rows):
                result = baseline.capture(spreadsheet_id="sheet", output=output)
        self.assertTrue({"queue-1", "prospect-1", "contact-1"}.issubset(set(result["lead_ids"])))
        self.assertTrue({"queue.example", "prospect.example", "contact.example", "history.example"}.issubset(set(result["domains"])))
        self.assertTrue({"queue@example.com", "contact@example.com", "history@example.com"}.issubset(set(result["emails"])))

    def test_workflow_requires_baseline_and_exact_net_new_closure(self):
        workflow = Path(".github/workflows/daily-agent-drafts-v14.yml").read_text(encoding="utf-8")
        self.assertIn("Capture pre-run net-new baseline", workflow)
        self.assertIn("outreach_draft_first_baseline.py --output daily-draft-baseline.json", workflow)
        self.assertIn("DRAFT_FIRST_BASELINE_FILE: daily-draft-baseline.json", workflow)
        self.assertIn("DRAFT_FIRST_REQUIRE_NET_NEW: 'true'", workflow)
        self.assertIn("selected_ids.isdisjoint(baseline_ids)", workflow)
        self.assertIn("selected_hosts.isdisjoint(baseline_hosts)", workflow)
        self.assertIn("selected_emails.isdisjoint(baseline_emails)", workflow)
        self.assertIn("net_new=1 readback=1 receipt_match=1 smtp_send=not_invoked", workflow)
        self.assertIn("daily-draft-baseline.json", workflow)

    def test_baseline_and_retry_paths_have_no_smtp_sender(self):
        for path in (
            "scripts/outreach_draft_first_baseline.py",
            "scripts/outreach_daily_draft_first_retry.py",
        ):
            text = Path(path).read_text(encoding="utf-8").casefold()
            self.assertNotIn("import smtplib", text)
            self.assertNotIn(".sendmail(", text)


if __name__ == "__main__":
    unittest.main()
