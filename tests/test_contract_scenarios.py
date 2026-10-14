"""Synthetic privacy, deduplication and input-boundary scenarios: no external I/O."""
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from dedupe_preflight import (
    candidate_identity, domains_match, load_registry_values, match_candidate,
    normalize_company, normalize_domain, normalize_email,
)
from new_leads import main, run, safe_hint, select_candidates
from trigger_request import resolve_request

HEADERS = [
    "company", "website", "domain", "emails", "status", "history",
    "lead_ids", "last_event_at", "sources", "exclude_from_new_leads",
]

def registry(status="sent", exclude="TRUE", domain="known.example.net"):
    return load_registry_values([HEADERS, [
        "Known Company BV", "https://" + domain, domain,
        "info@" + domain, status, "", "known-id", "", "", exclude,
    ]])

class InputBoundaryScenarios(unittest.TestCase):
    def test_malformed_or_unsafe_urls_are_rejected(self):
        invalid = [
            "", "example.org", "ftp://example.org", "file:///etc/passwd",
            "http://localhost", "http://127.0.0.1", "http://10.0.0.1",
            "http://169.254.0.1", "http://192.168.1.1",
            "http://[::1]", "http://example.local", "http://foo.internal",
            "https://www.example.test", "https://foo.example",
            "https://alice:password@example.org", "https://example.org:8080",
            "https://example.org/\nX-Injected: yes",
            "https://example.org/\rBcc: someone",
            "https://example.org/\tunsafe",
            "https://example.org/\x00hidden",
            "https://example.org/hello world",
            "https://company.invalid",
        ]
        for value in invalid:
            with self.subTest(value=repr(value)):
                self.assertEqual(safe_hint(value), "")

    def test_legitimate_web_hints_remain_accepted(self):
        valid = [
            "https://company.example.org/", "http://bedrijf.nl/contact",
            "https://shop.example.org/?ref=ok", "https://example.org:443/",
            "http://example.org:80/",
        ]
        for value in valid:
            with self.subTest(value=value):
                self.assertEqual(safe_hint(value), value)

    def test_invalid_discovery_contract_fails_closed(self):
        for raw in ({}, None, {"candidates": None}, {"candidates": {}}):
            with self.subTest(raw=raw):
                with self.assertRaises((TypeError, ValueError)):
                    select_candidates(raw, registry(), 2)

    def test_candidate_boundaries(self):
        for limit in (0, -1, 101, 1000):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    select_candidates({"candidates": []}, registry(), limit)
        self.assertEqual(select_candidates({"candidates": []}, registry(), 1)["counts"]["new_unverified_hints"], 0)

    def test_invalid_rows_are_suppressed_from_hints(self):
        rows = [
            "not a record", None, {}, {"name_hint": "Acme BV"},
            {"name_hint": "Acme BV", "website_hint": "http://localhost"},
            {"name_hint": "A" * 161, "website_hint": "https://too-long.example.org"},
        ]
        result = select_candidates({"candidates": rows}, registry(), 100)
        self.assertEqual(result["counts"]["invalid"], len(rows))
        self.assertEqual(result["candidates"], [])

    def test_company_label_does_not_imply_legal_form_or_send(self):
        r = select_candidates({"candidates": [
            {"name_hint": "Unverified Services B.V.", "website_hint": "https://unverified.example.org"},
        ]}, registry(), 2)
        self.assertEqual(r["counts"]["verified_new_leads"], 0)
        self.assertEqual(r["candidates"][0]["status"], "requires_official_site_verification")
        for key in ("legal_form", "email", "contact_basis", "approved", "send_ready"):
            self.assertNotIn(key, r["candidates"][0])
        self.assertEqual(r["emails_sent"], 0)
        self.assertEqual(r["mailbox_writes"], 0)

class SuppressionScenarios(unittest.TestCase):
    def test_all_previous_contact_statuses_block_even_without_flag(self):
        states = ("concept", "draft", "review_draft", "sent", "replied", "reply",
                  "bounce", "bounced", "opt_out", "optout", "unsubscribed",
                  "suppressed", "do_not_contact")
        for status in states:
            with self.subTest(status=status):
                self.assertIsNotNone(match_candidate(
                    {"website_hint": "https://known.example.net/contact"},
                    registry(status, "FALSE")
                ))

    def test_uncontacted_false_does_not_block_everyone(self):
        raw = [HEADERS,
               ["Uncontacted", "https://fresh.example.org", "fresh.example.org",
                "", "uncontacted", "", "", "", "", "FALSE"],
               ["Must Keep", "https://known.example.net", "known.example.net",
                "info@known.example.net", "sent", "", "", "", "", "TRUE"]]
        r = load_registry_values(raw)
        self.assertIsNone(match_candidate({"website_hint": "https://fresh.example.org"}, r))

    def test_company_unicode_spacing_equivalence(self):
        equivalents = ("Café B.V.", "CAFE BV", "Café B-V", "Café   b.v.")
        for a in equivalents:
            with self.subTest(a=a):
                self.assertEqual(normalize_company(a), "cafebv")

    def test_email_and_lead_id_case_insensitive(self):
        old = registry()
        for hint in (
            {"email": "INFO@KNOWN.EXAMPLE.NET"},
            {"lead_id": "KNOWN-ID"},
            {"name_hint": "KNOWN COMPANY B.V."},
            {"website_hint": "https://sub.known.example.net/about"},
        ):
            with self.subTest(hint=hint):
                self.assertIsNotNone(match_candidate(hint, old))

    def test_lookalike_domains_do_not_match(self):
        for lookalike in ("known-example.net", "evilkown.example.net",
                          "known.example.net.evil.org", "different.example.net"):
            with self.subTest(lookalike=lookalike):
                self.assertFalse(domains_match(lookalike, "known.example.net"))

    def test_subdomain_and_parent_domains_in_same_batch_are_duplicates(self):
        r = select_candidates({"candidates": [
            {"name_hint": "Fictieve Shipping BV", "website_hint": "https://shipping.example.org"},
            {"name_hint": "Fictieve Shipping Store BV", "website_hint": "https://store.shipping.example.org"},
        ]}, registry(), 10)
        self.assertEqual(r["counts"]["new_unverified_hints"], 1)
        self.assertEqual(r["counts"]["duplicate"], 1)

    def test_exact_website_and_case_duplicate(self):
        r = select_candidates({"candidates": [
            {"name_hint": "Sample One", "website_hint": "https://www.sample.example.org"},
            {"name_hint": "Sample One", "website_hint": "https://sample.example.org/about"},
        ]}, registry(), 5)
        self.assertEqual(r["counts"]["duplicate"], 1)

    def test_discovery_email_and_overture_id_hints_are_suppressed(self):
        for hint in (
            {"name_hint": "Foreign Name", "website_hint": "https://fresh.example.org",
             "discovery_email_candidates": [{"email": "info@known.example.net"}]},
            {"name_hint": "Foreign Name", "website_hint": "https://fresh.example.org",
             "overture_id": "KNOWN-ID"},
        ):
            with self.subTest(hint=hint):
                r = select_candidates({"candidates": [hint]}, registry(), 5)
                self.assertEqual(r["counts"]["previously_used"], 1)
                self.assertEqual(r["candidates"], [])

    def test_not_accepted_if_registry_cannot_load(self):
        with patch("new_leads.load_suppressions", side_effect=RuntimeError("no registry")), \
             patch("new_leads.discover") as fetch:
            with self.assertRaises(RuntimeError):
                run("Leiden", ["web"], 8, 5)
            fetch.assert_not_called()

class OutputPrivacyScenarios(unittest.TestCase):
    def test_stdout_contains_only_anonymous_summary(self):
        result = {
            "counts": {"scanned": 1, "new_unverified_hints": 1},
            "candidates": [{"company": "Secret Company", "website_hint": "https://secret.example.org"}],
            "coverage": "regional_sample", "emails_sent": 0,
        }
        buf = io.StringIO()
        with patch("new_leads.run", return_value=result), \
             patch("sys.argv", ["script", "--region", "Leiden", "--keywords", "zorg"]), \
             redirect_stdout(buf):
            rc = main()
        self.assertEqual(rc, 0)
        self.assertNotIn("Secret Company", buf.getvalue())
        self.assertNotIn("secret.example.org", buf.getvalue())
        self.assertEqual(json.loads(buf.getvalue())["emails_sent"], 0)

    def test_stdout_never_discloses_exception_details(self):
        buf = io.StringIO()
        with patch("new_leads.run", side_effect=RuntimeError("SECRET user@example.org")), \
             patch("sys.argv", ["script", "--region", "Leiden", "--keywords", "zorg"]), \
             redirect_stdout(buf):
            rc = main()
        self.assertEqual(rc, 1)
        self.assertNotIn("user@example.org", buf.getvalue())
        self.assertIn("discovery_or_registry_unavailable", buf.getvalue())

    def test_no_verified_lead_claim_from_hint_only(self):
        r = select_candidates({"candidates": [
            {"name_hint": "Unknown BV", "website_hint": "https://unknown.example.org"},
        ]}, registry(), 3)
        self.assertEqual(r["counts"]["verified_new_leads"], 0)
        self.assertEqual(r["emails_sent"], 0)

class DispatchScenarios(unittest.TestCase):
    def test_valid_push_request(self):
        request = resolve_request("push", {"head_commit": {
            "message": "LEADS_DISCOVERY_ONLY: Leiden|schoonmaak,installatie|10"
        }}, {})
        self.assertEqual(request, ("Leiden", "schoonmaak,installatie", "10", "25"))

    def test_invalid_push_markers_do_not_trigger(self):
        bad = ("", "LEADS_PREFLIGHT_ONLY:", "LEADS_DISCOVERY_ONLY: Amsterdam|horeca|0",
               "LEADS_DISCOVERY_ONLY: Leiden|zorg|101",
               "LEADS_DISCOVERY_ONLY: Leiden|zorg|1; touch /tmp/attack",
               "LEADS_DISCOVERY_ONLY: Leiden|zorg|1 extra",
               "LEADS_DISCOVERY_ONLY: Leiden|zorg|1|extra",
               "LEADS_DISCOVERY_ONLY: Leiden|zorg|1\nInjected control line",
               "LEADS_DISCOVERY_ONLY: Leiden|zorg|1\nanother line")
        for v in bad:
            with self.subTest(message=v):
                if v.endswith("\nInjected control line") or v.endswith("\nanother line"):
                    # Only the FIRST line of a commit message is an authorized marker;
                    # later commit-body content is deliberately ignored by this parser.
                    self.assertEqual(resolve_request("push", {"head_commit": {"message": v}}, {}),
                                     ("Leiden", "zorg", "1", "25"))
                else:
                    with self.assertRaises(ValueError):
                        resolve_request("push", {"head_commit": {"message": v}}, {})

    def test_invalid_events_and_dispatch_inputs_rejected(self):
        bad_cases = [
            ("issue_comment", {}, {}),
            ("pull_request", {}, {}),
            ("workflow_dispatch", {}, {"execution_mode": "preflight"}),
            ("workflow_dispatch", {}, {"execution_mode": "discover",
                                      "region": "A", "keywords": "zorg", "limit": "5", "radius_km": "8"}),
            ("workflow_dispatch", {}, {"execution_mode": "discover",
                                      "region": "Leiden", "keywords": "z", "limit": "5", "radius_km": "8"}),
            ("workflow_dispatch", {}, {"execution_mode": "discover",
                                      "region": "Leiden", "keywords": "zorg", "limit": "5", "radius_km": "400"}),
        ]
        for event,payload,inputs in bad_cases:
            with self.subTest(event=event, inputs=inputs):
                with self.assertRaises(ValueError):
                    resolve_request(event, payload, inputs)

if __name__ == "__main__":
    unittest.main()
