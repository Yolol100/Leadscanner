"""Offline privacy, source, status and batch regression tests for legacy site research."""
import unittest

import requests
from copy import deepcopy
from unittest.mock import patch

from instantly_historical_site_research import (
    BATCH_SIZE, REVIEW_KEYS, REFRESH_KEYS, _email_and_domain, _fetch_home,
    _save_candidate, _scan_site, draft_for_review,
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

    def test_quoted_site_question_does_not_count_as_second_outreach_cta(self):
        for language, source_text, action in (
            ("nl", "Kunnen klanten online een afspraak aanvragen?", "een voorbeeld voor de afspraakroute"),
            ("en", "Can customers book an appointment online?", "a short example for the booking flow"),
        ):
            with self.subTest(language=language):
                subject, body = draft_for_review(source_text, action, "appointment", language)
                self.assertTrue(subject)
                self.assertIn(source_text, body)
                self.assertEqual(body.count("?"), 2)
                self.assertEqual(body.replace(source_text, "", 1).count("?"), 1)
                self.assertIn("Andrew Baeten", body)

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

    def test_refresh_scans_previous_review_and_keeps_original_copy(self):
        class Session:
            def __enter__(self): return self
            def __exit__(self, *args): return False
        row = deepcopy(ROW)
        row["payload"]["leadscanner_site_research_status"] = "candidate_review_required"
        row["payload"]["leadscanner_site_candidate_body"] = "The earlier proposal must remain."
        with patch("instantly_historical_site_research.requests.Session", return_value=Session()), \
             patch("instantly_historical_site_research._fetch_home", return_value=(HTML, "https://studio-example.org/")), \
             patch("instantly_historical_site_research.safe_fetch_html", return_value=(DETAIL, "https://studio-example.org/afspraak", 200)), \
             patch("instantly_historical_site_research.inspect_lead_language", return_value="nl"):
            result = _scan_site(row, refresh=True)
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(len(result["proposal"]), len(REVIEW_KEYS))
        self.assertEqual(row["payload"]["leadscanner_site_candidate_body"], "The earlier proposal must remain.")
        self.assertEqual(_scan_site(row)["status"], "existing_research_hold")

    def test_refresh_personal_provider_uses_explicit_site_and_exact_contact_proof(self):
        class Session:
            def __enter__(self): return self
            def __exit__(self, *args): return False
        row = deepcopy(ROW)
        row["email"] = "owner@gmail.com"
        row["website"] = "https://studio-example.org/"
        self.assertEqual(_scan_site(row)["status"], "personal_email_domain")
        html = "<title>Studio Example</title><a href='mailto:owner@gmail.com'>Mail eigenaar</a><a href='/afspraak'>Afspraak maken</a>"
        with patch("instantly_historical_site_research.requests.Session", return_value=Session()), \
             patch("instantly_historical_site_research._fetch_home", return_value=(html, "https://studio-example.org/")) as fetch, \
             patch("instantly_historical_site_research.safe_fetch_html", return_value=(DETAIL, "https://studio-example.org/afspraak", 200)), \
             patch("instantly_historical_site_research.inspect_lead_language", return_value="nl"), \
             patch("instantly_historical_site_research.is_public_http_url", return_value=True):
            result = _scan_site(row, refresh=True)
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(result["proposal"]["leadscanner_site_candidate_contact_url"], "https://studio-example.org/")
        self.assertEqual(fetch.call_args[0][1], "studio-example.org")

    def test_refresh_explores_website_without_confirmed_email_but_creates_no_draft(self):
        class Session:
            def __enter__(self): return self
            def __exit__(self, *args): return False
        html = "<title>Studio Example</title><a href='/afspraak'>Afspraak maken</a>"
        with patch("instantly_historical_site_research.requests.Session", return_value=Session()), \
             patch("instantly_historical_site_research._fetch_home", return_value=(html, "https://studio-example.org/")), \
             patch("instantly_historical_site_research.safe_fetch_html", return_value=(DETAIL, "https://studio-example.org/afspraak", 200)) as get:
            result = _scan_site(deepcopy(ROW), refresh=True)
        self.assertEqual(result["status"], "research_only")
        self.assertGreaterEqual(get.call_count, 1)
        self.assertEqual(result["proposal"]["leadscanner_site_candidate_body"], "")
        self.assertEqual(result["proposal"]["leadscanner_site_candidate_subject"], "")
        self.assertEqual(result["proposal"]["leadscanner_site_research_status"], "research_only_contact_unverified")

    def test_refresh_stores_new_version_separately_and_preserves_originals(self):
        old = deepcopy(ROW)
        old["payload"]["leadscanner_site_candidate_body"] = "Do not overwrite old site proposal."
        old["payload"]["leadscanner_site_research_status"] = "candidate_review_required"
        client = FakeClient()
        client.row = deepcopy(old)
        proposal = {
            "leadscanner_site_candidate_findings": "[]",
            "leadscanner_site_candidate_observation": OBSERVATION,
            "leadscanner_site_candidate_value_action": "een korte verbeterroute",
            "leadscanner_site_candidate_subject": "vernieuwde aanpak",
            "leadscanner_site_candidate_body": "Dit is een nieuw, los reviewconcept.",
            "leadscanner_site_candidate_evidence_url": "https://studio-example.org/afspraak",
            "leadscanner_site_candidate_source_type": "official_site",
            "leadscanner_site_candidate_signal_type": "appointment",
            "leadscanner_site_candidate_contact_url": "https://studio-example.org/",
            "leadscanner_site_candidate_official_domain": "studio-example.org",
            "leadscanner_site_candidate_checked_date": "2026-10-12",
            "leadscanner_site_research_status": "candidate_review_required",
        }
        with patch("instantly_historical_site_research._campaigns_still_quiet"), \
             patch("instantly_historical_site_research._source_rows", return_value=[old]):
            report = research_imported_sites_batch(
                client, offset=0, save_candidates=True, refresh=True,
                workers=1, scanner=lambda row: {"status": "candidate", "proposal": proposal},
            )
        self.assertTrue(report["refresh_mode"])
        self.assertEqual(report["saved_candidate_count"], 1)
        self.assertEqual(report["previous_review_candidates_present"], 1)
        self.assertTrue(report["source_list_identity_verified"])
        self.assertNotIn("source_list_id", report)
        self.assertEqual(set(client.next_variables), set(old["payload"]) | set(REFRESH_KEYS))
        self.assertEqual(client.next_variables["leadscanner_site_candidate_body"], "Do not overwrite old site proposal.")
        self.assertEqual(client.next_variables["leadscanner_body"], VALUES["leadscanner_body"])
        self.assertEqual(client.next_variables["leadscanner_site_refresh_body"], "Dit is een nieuw, los reviewconcept.")
        self.assertEqual(client.next_variables["leadscanner_site_refresh_status"], "candidate_review_required")
        self.assertEqual(len(client.calls), 1)
        updated = deepcopy(old)
        updated["payload"] = deepcopy(client.next_variables)
        self.assertEqual(_scan_site(updated, refresh=True)["status"], "existing_refresh_hold")

    def test_refresh_dry_run_writes_nothing_even_for_existing_review(self):
        row = deepcopy(ROW)
        row["payload"]["leadscanner_site_candidate_body"] = "Earlier review"
        with patch("instantly_historical_site_research._campaigns_still_quiet"), \
             patch("instantly_historical_site_research._source_rows", return_value=[row]), \
             patch("instantly_historical_site_research._save_candidate", side_effect=AssertionError("no write")):
            report = research_imported_sites_batch(
                object(), offset=0, workers=1, refresh=True, save_candidates=False,
                scanner=lambda lead: {"status": "existing_refresh_hold"},
            )
        self.assertEqual(report["saved_candidate_count"], 0)
        self.assertEqual(report["holds"]["existing_refresh_hold"], 1)
        self.assertEqual(report["network_checked_count"], 0)
        self.assertEqual(report["previous_review_candidates_present"], 1)
        self.assertFalse(report["automatic_send"])

    def test_refresh_wrong_fields_cannot_change_original_proposal(self):
        client = FakeClient()
        with self.assertRaisesRegex(ValueError, "proposal_fields_invalid"):
            _save_candidate(
                client, client.row, {"leadscanner_site_candidate_body": "wrong target"},
                refresh=True,
            )
        self.assertEqual(client.calls, [])

    def test_refresh_language_mismatch_produces_review_only_new_language(self):
        class Session:
            def __enter__(self): return self
            def __exit__(self, *args): return False
        with patch("instantly_historical_site_research.requests.Session", return_value=Session()), \
             patch("instantly_historical_site_research._fetch_home", return_value=(HTML, "https://studio-example.org/")), \
             patch("instantly_historical_site_research.safe_fetch_html", return_value=(DETAIL, "https://studio-example.org/afspraak", 200)), \
             patch("instantly_historical_site_research.inspect_lead_language", return_value="en"):
            result = _scan_site(deepcopy(ROW), refresh=True)
        self.assertEqual(result["status"], "candidate")
        self.assertTrue(result["language_corrected"])
        self.assertIn("leadscanner_site_candidate_body", result["proposal"])

    def test_only_fixed_error_categories_leave_scanner(self):
        with patch("instantly_historical_site_research._campaigns_still_quiet"), \
             patch("instantly_historical_site_research._source_rows", return_value=[ROW]):
            report = research_imported_sites_batch(
                object(), offset=0, workers=1, refresh=True,
                scanner=lambda row: (_ for _ in ()).throw(
                    requests.Timeout("Sensitive contact details in exception")
                ),
            )
        self.assertEqual(report["scan_exception_categories"], {"network_timeout": 1})
        self.assertEqual(report["holds"], {"site_scan_exception": 1})
        self.assertNotIn("Sensitive", str(report))

    def test_research_only_saved_in_isolated_refresh_fields(self):
        client = FakeClient()
        payload = {key: "" for key in REVIEW_KEYS}
        payload.update({
            "leadscanner_site_candidate_findings": "[]",
            "leadscanner_site_candidate_observation": OBSERVATION,
            "leadscanner_site_candidate_evidence_url": "https://studio-example.org/afspraak",
            "leadscanner_site_candidate_official_domain": "studio-example.org",
            "leadscanner_site_research_status": "research_only_contact_unverified",
        })
        with patch("instantly_historical_site_research._campaigns_still_quiet"), \
             patch("instantly_historical_site_research._source_rows", return_value=[ROW]):
            result = research_imported_sites_batch(
                client, offset=0, workers=1, save_candidates=True, refresh=True,
                scanner=lambda row: {"status": "research_only", "proposal": payload},
            )
        self.assertEqual(result["saved_research_only_count"], 1)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["saved_candidate_count"], 0)
        self.assertEqual(client.next_variables["leadscanner_site_refresh_body"], "")
        self.assertEqual(client.next_variables["leadscanner_site_refresh_status"], "research_only_contact_unverified")
        self.assertEqual(len(client.calls), 1)

    def test_safe_home_recovers_missing_page_but_never_bypasses_forbidden(self):
        with patch("instantly_historical_site_research.is_public_http_url", return_value=True), \
             patch("instantly_historical_site_research.safe_fetch_html", side_effect=[
                 (None, "https://studio-example.org/old", 404),
                 ("<title>Studio Example</title>", "https://studio-example.org/", 200),
             ]) as fetch:
            html, url = _fetch_home(object(), "studio-example.org", "https://studio-example.org/old")
        self.assertTrue(html)
        self.assertEqual(url, "https://studio-example.org/")
        self.assertEqual(fetch.call_count, 2)
        with patch("instantly_historical_site_research.is_public_http_url", return_value=True), \
             patch("instantly_historical_site_research.safe_fetch_html", return_value=(None, "https://studio-example.org/", 403)) as fetch:
            html, url = _fetch_home(object(), "studio-example.org", "")
        self.assertIsNone(html)
        self.assertIsNone(url)
        self.assertEqual(fetch.call_count, 1)

    def test_network_exception_retries_once_and_returns_fixed_private_safe_code(self):
        calls = []
        def scanner(_row):
            calls.append(1)
            raise requests.Timeout("secret email in exception")
        with patch("instantly_historical_site_research._campaigns_still_quiet"), \
             patch("instantly_historical_site_research._source_rows", return_value=[ROW]):
            result = research_imported_sites_batch(object(), offset=0, workers=1, scanner=scanner)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["scan_exception_categories"], {"network_timeout": 1})
        self.assertNotIn("secret", str(result))

    def test_bad_offset_or_source_count_fails_before_provider(self):
        for kwargs in ({"offset": 1}, {"offset": -100}, {"offset": 0, "expected_count": 1127},
                       {"offset": 0, "workers": 101}):
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
