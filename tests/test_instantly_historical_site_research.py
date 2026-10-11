"""Offline privacy, source, status and batch regression tests for legacy site research."""
import unittest
from copy import deepcopy
from unittest.mock import patch

from instantly_historical_site_research import (
    BATCH_SIZE, _email_and_domain, _fetch_home, _save_candidate, _scan_site,
    draft_for_review,
    research_imported_sites_batch,
)

LID = "24deb187-59e0-43b5-86b8-fe37a7b21e2a"
EMAIL = "info@studio-example.org"
ID = "11111111-1111-1111-1111-111111111111"
VALUES = {
    "leadscanner_import_origin": "myhost_drafts",
    "leadscanner_contact_basis": "review_required",
    "leadscanner_subject": "idee voor jullie afspraakroute",
    "leadscanner_body": "Dit is een vooraf beoordeelde conceptmail.",
}
ROW = {"id": ID, "email": EMAIL, "list_id": LID, "campaign": None, "payload": VALUES}
OBSERVATION = "Klanten kunnen online een afspraak aanvragen voor onderhoud of reparatie."
HTML = (
    "<html><title>Studio Example</title><a href='mailto:info@studio-example.org'>Contact</a>"
    "<a href='/afspraak'>Afspraak aanvragen</a></html>"
)
DETAIL = "<html>" + OBSERVATION + "</html>"


class FakeClient:
    def __init__(self):
        self.row = deepcopy(ROW)
        self.calls = []
        self.next_variables = None

    def get_lead(self, lead_id):
        result = deepcopy(self.row)
        if self.next_variables is not None:
            result["payload"] = deepcopy(self.next_variables)
        return result

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, deepcopy(kwargs)))
        if method != "PATCH" or path != "/leads/" + ID:
            raise AssertionError("unexpected provider operation")
        self.next_variables = kwargs["json"]["custom_variables"]
        return {}


class Tests(unittest.TestCase):
    def test_email_domain_is_only_a_hint(self):
        self.assertEqual(_email_and_domain(ROW), (EMAIL, "studio-example.org"))
        self.assertIsNone(_email_and_domain(dict(ROW, email="wrong-address")))

    def test_no_website_contact_proof_keeps_record_held(self):
        class Session:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        with patch("instantly_historical_site_research.requests.Session", return_value=Session()), \
             patch("instantly_historical_site_research._fetch_home", return_value=("<html>No published email</html>", "https://studio-example.org/")):
            result = _scan_site(deepcopy(ROW))
        self.assertEqual(result, {"status": "recipient_not_confirmed_on_website"})

    def test_verified_contact_and_process_yields_only_review_candidate(self):
        class Session:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        with patch("instantly_historical_site_research.requests.Session", return_value=Session()), \
             patch("instantly_historical_site_research._fetch_home", return_value=(HTML, "https://studio-example.org/")), \
             patch("instantly_historical_site_research.safe_fetch_html", return_value=(DETAIL, "https://studio-example.org/afspraak", 200)), \
             patch("instantly_historical_site_research.inspect_lead_language", return_value="nl"):
            actual = _scan_site(deepcopy(ROW))
        self.assertEqual(actual["status"], "candidate")
        proposal = actual["proposal"]
        self.assertEqual(proposal["leadscanner_site_candidate_source_type"], "official_site")
        self.assertEqual(proposal["leadscanner_site_candidate_contact_url"], "https://studio-example.org/")
        self.assertIn(OBSERVATION, proposal["leadscanner_site_candidate_observation"])
        self.assertIn("afspraakroute", proposal["leadscanner_site_candidate_value_action"])
        self.assertEqual(proposal["leadscanner_site_research_status"], "candidate_review_required")
        self.assertIn(OBSERVATION, proposal["leadscanner_site_candidate_body"])
        self.assertNotEqual(VALUES["leadscanner_body"], proposal["leadscanner_site_candidate_body"])
        self.assertNotIn("leadscanner_contact_basis", proposal)
        self.assertNotIn("leadscanner_observation", proposal)
        self.assertNotIn("leadscanner_body", proposal)

    def test_draft_for_review_in_two_languages_is_specific(self):
        cases = (
            ('nl', 'afspraakroute', 'een korte voorbeeldvariant voor de afspraakroute'),
            ('en', 'booking flow', 'a short example for the booking flow'),
        )
        for language, label, action in cases:
            with self.subTest(language=language):
                subject, body = draft_for_review(OBSERVATION, action, 'appointment', language)
                self.assertTrue(subject)
                self.assertIn(OBSERVATION, body)
                self.assertIn(action, body)
                self.assertEqual(body.count('?'), 1)
                self.assertIn('Andrew Baeten', body)
                self.assertNotIn('{{', body)
                self.assertLessEqual(len(body.split()), 125)
                self.assertNotIn('have already', body.lower())

    def test_draft_rejects_missing_or_untrusted_inputs(self):
        self.assertEqual(draft_for_review(OBSERVATION, 'example', 'appointment', 'unknown'), ('', ''))
        self.assertEqual(draft_for_review(OBSERVATION, '{{hack}}', 'appointment', 'nl'), ('', ''))
    def test_language_mismatch_is_held(self):
        class Session:
            def __enter__(self): return self
            def __exit__(self, *args): return False
        with patch("instantly_historical_site_research.requests.Session", return_value=Session()), \
             patch("instantly_historical_site_research._fetch_home", return_value=(HTML, "https://studio-example.org/")), \
             patch("instantly_historical_site_research.safe_fetch_html", return_value=(DETAIL, "https://studio-example.org/afspraak", 200)), \
             patch("instantly_historical_site_research.inspect_lead_language", return_value="en"):
            result = _scan_site(deepcopy(ROW))
        self.assertEqual(result["status"], "observation_language_mismatch")

    def test_personal_domain_and_existing_research_are_not_fetched(self):
        row = deepcopy(ROW)
        row["email"] = "team@gmail.com"
        with patch("instantly_historical_site_research.requests.Session", side_effect=AssertionError("no fetch")):
            self.assertEqual(_scan_site(row)["status"], "personal_email_domain")
            row = deepcopy(ROW)
            row["payload"]["leadscanner_site_research_status"] = "candidate_review_required"
            self.assertEqual(_scan_site(row)["status"], "existing_research_hold")

    def test_exact_lead_update_preserves_copy_consent_and_source(self):
        client = FakeClient()
        proposal = {"leadscanner_site_candidate_observation": OBSERVATION}
        _save_candidate(client, client.row, proposal, sleep_fn=lambda _: None)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][:2], ("PATCH", "/leads/" + ID))
        values = client.next_variables
        for k in VALUES:
            self.assertEqual(values[k], VALUES[k])
        self.assertEqual(values["leadscanner_contact_basis"], "review_required")
        self.assertNotIn("leadscanner_observation", values)

    def test_changed_lead_prewrite_blocks_patch(self):
        client = FakeClient()
        old = deepcopy(client.row)
        client.row["payload"]["leadscanner_body"] = "New content"
        with self.assertRaisesRegex(RuntimeError, "prewrite_variables_changed"):
            _save_candidate(client, old, {"leadscanner_site_candidate_observation": OBSERVATION})
        self.assertEqual(client.calls, [])

    def test_dry_run_batch_is_100_and_never_writes(self):
        base_rows = [deepcopy(ROW) for _ in range(100)]
        for i, row in enumerate(base_rows):
            row["id"] = f"{i + 1:08x}-0000-0000-0000-000000000000"
        with patch("instantly_historical_site_research._campaigns_still_quiet"), \
             patch("instantly_historical_site_research._source_rows", return_value=base_rows), \
             patch("instantly_historical_site_research._save_candidate", side_effect=AssertionError("no write")):
            report = research_imported_sites_batch(
                object(), offset=0, save_candidates=False, workers=1,
                scanner=lambda row: {"status": "unreachable_website"},
            )
        self.assertEqual(report["batch_size"], BATCH_SIZE)
        self.assertEqual(report["holds"]["unreachable_website"], 100)
        self.assertEqual(report["saved_candidate_count"], 0)
        self.assertFalse(report["automatic_send"])
        self.assertFalse(report["prospect_addresses_or_evidence_in_public_result"])
        self.assertNotIn(EMAIL, str(report))

    def test_save_candidates_uses_review_only_fields(self):
        client = FakeClient()
        rows = [deepcopy(ROW)]
        proposal = {
            "leadscanner_site_candidate_observation": OBSERVATION,
            "leadscanner_site_candidate_value_action": "een voorbeeld voor de afspraakroute",
            "leadscanner_site_candidate_subject": "idee voor jullie afspraakroute",
            "leadscanner_site_candidate_body": "Hoi, test.",
            "leadscanner_site_candidate_evidence_url": "https://studio-example.org/afspraak",
            "leadscanner_site_candidate_source_type": "official_site",
            "leadscanner_site_candidate_signal_type": "appointment",
            "leadscanner_site_candidate_contact_url": "https://studio-example.org/",
            "leadscanner_site_candidate_official_domain": "studio-example.org",
            "leadscanner_site_candidate_checked_date": "2026-10-11",
            "leadscanner_site_research_status": "candidate_review_required",
        }
        with patch("instantly_historical_site_research._campaigns_still_quiet"), \
             patch("instantly_historical_site_research._source_rows", return_value=rows):
            report = research_imported_sites_batch(
                client, offset=0, save_candidates=True, workers=1,
                scanner=lambda row: {"status": "candidate", "proposal": proposal},
            )
        self.assertEqual(report["saved_candidate_count"], 1)
        self.assertEqual(report["contact_basis_changes"], 0)
        self.assertEqual(report["live_merge_field_changes"], 0)
        self.assertEqual(len(client.calls), 1)

    def test_bad_offset_or_source_count_fails_before_provider(self):
        for kwargs in ({"offset": 1}, {"offset": -100}, {"offset": 0, "expected_count": 1127},
                       {"offset": 0, "workers": 7}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                research_imported_sites_batch(object(), **kwargs)
        with patch("instantly_historical_site_research._campaigns_still_quiet"), \
             patch("instantly_historical_site_research._source_rows", return_value=[ROW]):
            with self.assertRaises(ValueError):
                research_imported_sites_batch(object(), offset=100)

    def test_scanner_exception_is_aggregate_only(self):
        with patch("instantly_historical_site_research._campaigns_still_quiet"), \
             patch("instantly_historical_site_research._source_rows", return_value=[ROW]):
            report = research_imported_sites_batch(
                object(), offset=0, workers=1,
                scanner=lambda row: (_ for _ in ()).throw(RuntimeError("private recipient info@example.org")),
            )
        self.assertEqual(report["holds"]["site_scan_exception"], 1)
        self.assertNotIn("info@example.org", str(report))


if __name__ == "__main__":
    unittest.main()
