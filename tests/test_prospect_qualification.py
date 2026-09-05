from __future__ import annotations

import pathlib
import unittest

from prospect_qualification import assess_candidate


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

    def test_evidence_bound_shop_can_reach_a_without_fake_signal(self):
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
        self.assertTrue(result.fact)
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
        <html><head><title>Example Products</title></head>
        <body><p>Products and services.</p></body></html>
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

    def test_autopilot_workflow_has_no_mailbox_or_seed_secrets(self):
        workflow = pathlib.Path(".github/workflows/leads-autopilot.yml").read_text(encoding="utf-8")
        self.assertNotIn("OUTREACH_MAIL_PASSWORD", workflow)
        self.assertNotIn("OUTREACH_MAILBOXES_JSON", workflow)
        self.assertNotIn("OUTREACH_SEED_INBOXES_JSON", workflow)
        self.assertNotIn("outreach_direct_smtp_runtime.py", workflow)
        self.assertIn("send permission:", workflow)
        self.assertIn("none", workflow)


if __name__ == "__main__":
    unittest.main()
