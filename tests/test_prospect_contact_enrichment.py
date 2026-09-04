import unittest
from unittest.mock import patch

import prospect_contact_enrichment as m


class Page:
    def __init__(self, text="", links=None):
        self.text = text
        self.links = links or []


class ContactEnrichmentTests(unittest.TestCase):
    def test_official_aligned_address_is_ready(self):
        pages = {
            "https://example.nl/": Page("", [("https://example.nl/contact", "Contact")]),
            "https://example.nl/contact": Page("info@example.nl", [("mailto:info@example.nl", "mail")]),
        }
        with patch.object(m, "root_url", return_value="https://example.nl/"), patch.object(m, "parse_page", side_effect=lambda content, url: content), patch.object(m, "mx_status", return_value="present"), patch.object(m, "host_key", side_effect=lambda url: "example.nl" if "example.nl" in url else "other.nl"):
            result = m.discover_contact("https://example.nl", fetch=lambda url: pages[url])
        self.assertEqual(result.email, "info@example.nl")
        self.assertEqual(result.status, "ready")

    def test_external_domain_is_manual_review(self):
        page = Page("agency@agency-mail.nl")
        with patch.object(m, "root_url", return_value="https://example.nl/"), patch.object(m, "parse_page", return_value=page), patch.object(m, "mx_status", return_value="present"), patch.object(m, "host_key", side_effect=lambda url: "example.nl" if "example.nl" in url else "agency-mail.nl"):
            result = m.discover_contact("https://example.nl", fetch=lambda url: page)
        self.assertEqual(result.status, "manual_review")
        self.assertEqual(result.domain_alignment, "external_domain")

    def test_noreply_and_free_mail_are_rejected(self):
        self.assertFalse(m.is_allowed_business_address("noreply@example.nl"))
        self.assertFalse(m.is_allowed_business_address("hello@gmail.com"))
        self.assertTrue(m.is_allowed_business_address("contact@example.nl"))

    def test_only_qualified_unseen_prospects_are_eligible(self):
        rows = [
            {"candidate_id": "1", "status": "qualified", "website": "https://a.nl"},
            {"candidate_id": "2", "status": "hold", "website": "https://b.nl"},
            {"candidate_id": "3", "status": "qualified", "website": "https://c.nl"},
        ]
        selected = m.eligible_prospects(rows, {"3"}, 10)
        self.assertEqual([row["candidate_id"] for row in selected], ["1"])

    def test_hard_cap_is_25(self):
        rows = [{"candidate_id": str(i), "status": "qualified", "website": f"https://{i}.example.nl"} for i in range(40)]
        self.assertEqual(len(m.eligible_prospects(rows, set(), m.HARD_MAX_PROSPECTS_PER_RUN)), 25)


if __name__ == "__main__":
    unittest.main()
