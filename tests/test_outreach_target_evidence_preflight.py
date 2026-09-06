import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import outreach_target_evidence_preflight as p


FACT = "Example sells handmade lighting and home accessories through its online store."
IDEA = "Make the mobile category navigation visible above the product grid so shoppers can reach the right collection faster."
ADDRESS = "123 Main Street, Example City"


def source(**extra):
    payload = {
        "evidence_url": "https://shop.example.com/collections",
        "fact": FACT,
        "idea": IDEA,
        "analysis_type": "webshop",
    }
    payload.update(extra)
    return "website_scan:" + json.dumps(payload, separators=(",", ":"))


def row(country="US", company="Example Inc", **overrides):
    base = {
        "company": company,
        "website": "https://shop.example.com/",
        "country": country,
        "source": source(),
        "body": f"Hi Example team,\n\n{FACT}\n\nOne idea: {IDEA}\n\nThis is a commercial message.\n{p.POSTAL_PLACEHOLDER}\n\nBest regards,\nAndrew Baeten",
        "status": "approved",
    }
    base.update(overrides)
    return base


class FakeClient:
    def __init__(self, html):
        self.html = html

    def fetch_text(self, _url):
        return self.html


class TargetEvidencePreflightTests(unittest.TestCase):
    def test_netherlands_is_not_country_blocked(self):
        errors = p.metadata_errors(row(country="NL"), postal_address=ADDRESS)
        self.assertFalse(any("NL target" in item for item in errors))

    def test_webactueel_self_target_is_blocked_before_send(self):
        evidence = source(evidence_url="https://webactueel.nl/")
        errors = p.metadata_errors(
            row(website="https://webactueel.nl/", source=evidence),
            postal_address=ADDRESS,
        )
        self.assertTrue(any("self domain" in item.lower() for item in errors))
        live_errors = p.website_target_errors(
            row(website="https://sub.webactueel.nl/", source=evidence),
            FakeClient("<html><body>Webactueel</body></html>"),
        )
        self.assertTrue(any("self domain" in item.lower() for item in live_errors))

    def test_us_requires_private_postal_config_and_placeholder(self):
        errors = p.metadata_errors(row(country="US"), postal_address="")
        self.assertTrue(any("OUTREACH_POSTAL_ADDRESS" in item for item in errors))
        body = row(country="US")["body"].replace(p.POSTAL_PLACEHOLDER, "")
        errors = p.metadata_errors(row(country="US", body=body), postal_address=ADDRESS)
        self.assertTrue(any("private postal placeholder" in item for item in errors))

    def test_us_requires_commercial_identification(self):
        body = row(country="US")["body"].replace("commercial message", "note")
        errors = p.metadata_errors(row(country="US", body=body), postal_address=ADDRESS)
        self.assertTrue(any("commercial/advertising" in item for item in errors))

    def test_us_rejects_persisted_private_postal_address(self):
        body = row(country="US")["body"].replace(p.POSTAL_PLACEHOLDER, ADDRESS)
        errors = p.metadata_errors(row(country="US", body=body), postal_address=ADDRESS)
        self.assertTrue(any("must not be persisted" in item for item in errors))

    def test_us_evidence_metadata_can_be_green_with_private_placeholder(self):
        self.assertEqual(
            p.metadata_errors(row(country="US"), postal_address=ADDRESS),
            [],
        )

    def test_evidence_url_must_be_official_domain(self):
        bad_source = source(evidence_url="https://third-party.example/evidence")
        errors = p.metadata_errors(row(source=bad_source), postal_address=ADDRESS)
        self.assertTrue(any("official prospect domain" in item for item in errors))

    def test_exact_scan_fact_must_be_in_mail(self):
        body = row()["body"].replace(FACT, "A generic compliment.")
        errors = p.metadata_errors(row(body=body), postal_address=ADDRESS)
        self.assertTrue(any("exact website_scan fact" in item for item in errors))

    def test_exact_scan_idea_must_be_in_mail(self):
        body = row()["body"].replace(IDEA, "A generic redesign idea.")
        errors = p.metadata_errors(row(body=body), postal_address=ADDRESS)
        self.assertTrue(any("exact website_scan idea" in item for item in errors))

    def test_uk_requires_verified_corporate_subscriber(self):
        uk_source = source(subscriber_type="corporate")
        self.assertEqual(
            p.metadata_errors(
                row(country="GB", company="Example Limited", source=uk_source),
                postal_address="",
            ),
            [],
        )
        errors = p.metadata_errors(row(country="GB", company="Example Studio", source=uk_source), postal_address="")
        self.assertTrue(any("corporate subscriber" in item for item in errors))

    def test_live_target_check_rejects_agency_homepage(self):
        for copy in (
            "We are a digital marketing agency for growing brands.",
            "We are a mobile app development agency for startups.",
            "We are a software development agency creating custom platforms.",
            "We are a UX agency for digital product teams.",
        ):
            errors = p.website_target_errors(
                row(country="US"),
                FakeClient(f"<html><title>Example</title><body>{copy}</body></html>"),
            )
            self.assertTrue(any("agency" in item for item in errors))

    def test_live_target_check_accepts_normal_webshop(self):
        errors = p.website_target_errors(
            row(country="US"),
            FakeClient("<html><title>Example Shop</title><body>Furniture, lighting and home accessories. Shop online.</body></html>"),
        )
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
