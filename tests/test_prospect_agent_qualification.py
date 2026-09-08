from __future__ import annotations

import unittest
from datetime import datetime, timezone

from prospect_agent_qualification import AGENT_CATALOG, assess_candidate


class ProspectAgentQualificationTests(unittest.TestCase):
    def _candidate(self, **overrides):
        row = {
            "candidate_id": "prospect-1",
            "company": "Example Service",
            "website": "https://example.com/",
            "country": "US",
            "status": "discovered",
        }
        row.update(overrides)
        return row

    def test_catalog_contains_exact_six_approved_agents(self):
        self.assertEqual(set(AGENT_CATALOG), {
            "front_desk_sales", "lead_reactivation", "review_concierge",
            "customer_support", "commerce", "quote_intake",
        })

    def test_booking_flow_selects_front_desk_sales_and_can_reach_a_without_signal(self):
        html = """
        <html><head><title>Example Dental Clinic</title></head><body>
        <h1>Dental services</h1><a href='/book'>Book an appointment</a>
        <a href='/contact'>Contact</a><p>Professional dental services.</p></body></html>
        """
        result = assess_candidate(self._candidate(company="Example Dental Clinic"), html, [])
        self.assertEqual(result.agent_type, "front_desk_sales")
        self.assertEqual(result.agent_opportunity_score, 3)
        self.assertEqual(result.value_integration_fit_score, 2)
        self.assertEqual(result.customer_potential, 8)
        self.assertEqual(result.tier, "A")
        self.assertEqual(result.status, "qualified")
        self.assertIn("Front Desk & Sales Agent", result.idea)

    def test_quote_flow_selects_quote_intake(self):
        html = """
        <html><head><title>Example Installations</title></head><body>
        <h1>Installation services</h1><a href='/quote'>Request a quote</a>
        <p>Contact us for pricing and services.</p></body></html>
        """
        result = assess_candidate(self._candidate(company="Example Installations"), html, [])
        self.assertEqual(result.agent_type, "quote_intake")
        self.assertEqual(result.agent_opportunity_score, 3)
        self.assertIn("Quote & Intake Agent", result.idea)

    def test_shop_flow_selects_commerce(self):
        html = """
        <html><head><title>Example Shop</title></head><body>
        <h1>Products</h1><a href='/shop'>Shop online</a><a href='/cart'>Cart</a>
        <p>Add to cart and checkout.</p></body></html>
        """
        result = assess_candidate(self._candidate(company="Example Shop"), html, [])
        self.assertEqual(result.agent_type, "commerce")
        self.assertIn("Commerce Agent", result.idea)

    def test_support_flow_selects_customer_support(self):
        html = """
        <html><head><title>Example Software</title></head><body>
        <h1>Software services</h1><a href='/support'>Customer support</a>
        <a href='/faq'>FAQ</a></body></html>
        """
        result = assess_candidate(self._candidate(company="Example Software"), html, [])
        self.assertEqual(result.agent_type, "customer_support")
        self.assertIn("Customer Support Agent", result.idea)

    def test_review_flow_needs_extra_signal_before_auto_qualification(self):
        html = """
        <html><head><title>Example Cleaning</title></head><body>
        <h1>Cleaning services</h1><section>Customer reviews and testimonials</section>
        </body></html>
        """
        no_signal = assess_candidate(self._candidate(company="Example Cleaning"), html, [])
        self.assertEqual(no_signal.agent_type, "review_concierge")
        self.assertNotEqual(no_signal.status, "qualified")
        signals = [{
            "candidate_id": "prospect-1", "detected_at": datetime.now(timezone.utc).isoformat(),
            "evidence_date": "", "status": "active", "strength": "2",
        }]
        with_signal = assess_candidate(self._candidate(company="Example Cleaning"), html, signals)
        self.assertEqual(with_signal.status, "qualified")
        self.assertIn("Review Agent", with_signal.idea)

    def test_generic_contact_only_is_hold_not_auto_qualified(self):
        html = """
        <html><head><title>Example Services</title></head><body>
        <h1>Professional services</h1><a href='/contact'>Contact us</a>
        </body></html>
        """
        result = assess_candidate(self._candidate(), html, [])
        self.assertEqual(result.agent_type, "front_desk_sales")
        self.assertEqual(result.agent_opportunity_score, 2)
        self.assertEqual(result.status, "hold")

    def test_agency_target_stays_rejected(self):
        html = """
        <html><head><title>Example AI Agency</title></head><body>
        <h1>AI automation agency</h1><p>We build AI agents for clients.</p>
        <a href='/book'>Book an appointment</a></body></html>
        """
        result = assess_candidate(self._candidate(company="Example AI Agency"), html, [])
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.customer_potential, 0)


if __name__ == "__main__":
    unittest.main()