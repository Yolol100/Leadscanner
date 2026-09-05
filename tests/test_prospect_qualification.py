from __future__ import annotations

import pathlib
import unittest
from datetime import datetime, timedelta, timezone

from prospect_qualification import _eligible_candidates, assess_candidate


class ProspectQualificationTests(unittest.TestCase):
    def _candidate(self, **overrides):
        row = {
            "candidate_id": "prospect-1",
            "company": "Example Products",
            "website": "https://example.com/",
            "country": "US",
            "status": "discovered",
        }
        row.update(overrides)
        return row

    def test_severe_mobile_gap_can_reach_a_without_fake_signal(self):
        html = """
        <html><head><title>Example Products Shop</title></head>
        <body><p>Browse our products and shop online.</p><a href='/products'>Products</a></body></html>
        """
        result = assess_candidate(self._candidate(), html, [])
        self.assertEqual(result.icp_score, 3)
        self.assertEqual(result.website_opportunity_score, 3)
        self.assertEqual(result.offer_fit_score, 2)
        self.assertEqual(result.customer_potential, 8)
        self.assertEqual(result.tier, "A")
        self.assertEqual(result.status, "qualified")
        self.assertIn("viewport", result.fact.lower())
        self.assertTrue(result.idea)

    def test_agency_target_is_rejected_fail_closed(self):
        html = """
        <html><head><title>Example Web Design Agency</title></head>
        <body><h1>Web design and SEO agency</h1><p>We build websites for clients.</p></body></html>
        """
        result = assess_candidate(self._candidate(company="Example Agency"), html, [])
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.customer_potential, 0)
        self.assertIn("agency/provider", result.reason)

    def test_signal_strength_is_bounded_to_two(self):
        html = """
        <html><head><title>Example Products</title><meta name='viewport' content='width=device-width'></head>
        <body><h1>Products</h1><a href='/contact'>Contact</a><p>Products and services.</p></body></html>
        """
        signals = [{
            "candidate_id": "prospect-1",
            "status": "active",
            "strength": "2",
        }]
        result = assess_candidate(self._candidate(), html, signals)
        self.assertEqual(result.signal_score, 2)
        self.assertLessEqual(result.customer_potential, 10)

    def test_good_site_without_concrete_gap_is_not_auto_qualified(self):
        html = """
        <html><head><title>Example Maintenance</title>
        <meta name='description' content='Professional maintenance services'>
        <meta name='viewport' content='width=device-width, initial-scale=1'>
        </head><body><h1>Professional maintenance services</h1>
        <a href='/contact'>Contact</a><p>Maintenance services for professional clients.</p></body></html>
        """
        result = assess_candidate(self._candidate(company="Example Maintenance"), html, [])
        self.assertNotEqual(result.status, "qualified")
        self.assertEqual(result.website_opportunity_score, 0)
        self.assertFalse(result.fact)
        self.assertFalse(result.idea)

    def test_product_word_alone_does_not_turn_manufacturer_into_webshop(self):
        html = """
        <html><head><title>Industrial Components Manufacturer</title>
        <meta name='description' content='Industrial products for OEM customers'>
        <meta name='viewport' content='width=device-width, initial-scale=1'>
        </head><body><h1>Industrial Components</h1>
        <p>We manufacture products and components for industrial customers.</p>
        <a href='/contact'>Contact</a><a href='/products'>Products</a></body></html>
        """
        result = assess_candidate(self._candidate(company="Industrial Components"), html, [])
        self.assertEqual(result.analysis_type, "website")
        self.assertEqual(result.icp_score, 2)
        self.assertEqual(result.offer_fit_score, 1)
        self.assertNotEqual(result.status, "qualified")

    def test_generic_small_gaps_do_not_stack_into_three_point_opportunity(self):
        html = """
        <html><head><title>Example Maintenance</title>
        <meta name='viewport' content='width=device-width, initial-scale=1'>
        </head><body><p>Professional maintenance services for business clients.</p></body></html>
        """
        result = assess_candidate(self._candidate(company="Example Maintenance"), html, [])
        self.assertEqual(result.analysis_type, "website")
        self.assertEqual(result.website_opportunity_score, 2)
        self.assertIn("primary_evidence=no_contact_link", result.reason)

    def test_recent_assessed_rows_do_not_starve_new_candidates(self):
        now = datetime.now(timezone.utc)
        candidates = [
            self._candidate(candidate_id="old-hold", status="hold"),
            self._candidate(candidate_id="new-prospect", status="discovered", company="New Prospect"),
        ]
        existing = {
            "old-hold": {"assessed_at": (now - timedelta(days=1)).isoformat()},
        }
        eligible = _eligible_candidates(candidates, existing, force_recheck=False, recheck_days=30)
        self.assertEqual([row["candidate_id"] for row in eligible], ["new-prospect"])

    def test_force_recheck_includes_recent_qualified_and_rejected(self):
        now = datetime.now(timezone.utc).isoformat()
        candidates = [
            self._candidate(candidate_id="qualified-1", status="qualified"),
            self._candidate(candidate_id="rejected-1", status="rejected"),
        ]
        existing = {
            "qualified-1": {"assessed_at": now},
            "rejected-1": {"assessed_at": now},
        }
        eligible = _eligible_candidates(candidates, existing, force_recheck=True, recheck_days=30)
        self.assertEqual({row["candidate_id"] for row in eligible}, {"qualified-1", "rejected-1"})

    def test_autopilot_workflow_has_no_mailbox_or_seed_secrets(self):
        workflow = pathlib.Path(".github/workflows/leads-autopilot.yml").read_text(encoding="utf-8")
        self.assertNotIn("OUTREACH_MAIL_PASSWORD", workflow)
        self.assertNotIn("OUTREACH_MAILBOXES_JSON", workflow)
        self.assertNotIn("OUTREACH_SEED_INBOXES_JSON", workflow)
        self.assertNotIn("outreach_direct_smtp_runtime.py", workflow)
        self.assertIn("send permission:", workflow)
        self.assertIn("none", workflow)

    def test_sender_readiness_workflow_run_only_accepts_green_main_push_from_same_repo(self):
        workflow = pathlib.Path(".github/workflows/sender-readiness.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_run:", workflow)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", workflow)
        self.assertIn("github.event.workflow_run.event == 'push'", workflow)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", workflow)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository", workflow)


if __name__ == "__main__":
    unittest.main()
