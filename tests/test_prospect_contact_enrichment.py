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

    def test_noreply_is_rejected_but_official_free_mail_can_be_contact_evidence(self):
        self.assertFalse(m.is_allowed_business_address("noreply@example.nl"))
        self.assertTrue(m.is_allowed_business_address("hello@gmail.com"))
        self.assertTrue(m.is_allowed_business_address("contact@example.nl"))

    def test_decision_maker_role_beats_generic_even_on_external_provider(self):
        page = Page(
            "info@example.nl owner@example.com",
            [
                ("mailto:info@example.nl", "General contact"),
                ("mailto:owner@gmail.com", "Founder / eigenaar"),
            ],
        )
        with patch.object(m, "root_url", return_value="https://example.nl/"), patch.object(m, "parse_page", return_value=page), patch.object(m, "mx_status", return_value="present"), patch.object(m, "host_key", side_effect=lambda url: "example.nl" if "example.nl" in url else ("gmail.com" if "gmail.com" in url else "example.com")):
            result = m.discover_contact("https://example.nl", fetch=lambda url: page)
        self.assertEqual(result.email, "owner@gmail.com")
        self.assertEqual(result.contact_priority_tier, "decision_maker")
        self.assertEqual(result.contact_role, "founder")
        self.assertEqual(result.status, "manual_review")

    def test_department_address_beats_generic_when_no_decision_maker_is_proven(self):
        page = Page(
            "info@example.nl marketing@example.nl",
            [
                ("mailto:info@example.nl", "Contact"),
                ("mailto:marketing@example.nl", "Marketing"),
            ],
        )
        with patch.object(m, "root_url", return_value="https://example.nl/"), patch.object(m, "parse_page", return_value=page), patch.object(m, "mx_status", return_value="present"), patch.object(m, "host_key", return_value="example.nl"):
            result = m.discover_contact("https://example.nl", fetch=lambda url: page)
        self.assertEqual(result.email, "marketing@example.nl")
        self.assertEqual(result.contact_priority_tier, "department")

    def test_localpart_alone_does_not_prove_named_person(self):
        self.assertEqual(
            m.contact_role_and_priority("jan.jansen@example.nl", ""),
            ("", "generic"),
        )

    def test_source_label_can_prove_named_person_identity(self):
        self.assertEqual(
            m.contact_role_and_priority("jan.jansen@example.nl", "Jan Jansen"),
            ("", "named_person"),
        )

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

    def test_retryable_contact_rows_do_not_block_future_retry(self):
        contacts = [
            {"candidate_id": "retry", "status": m.RETRYABLE_CONTACT_STATUS},
            {"candidate_id": "ready", "status": "ready"},
            {"candidate_id": "missing", "status": "not_found"},
        ]
        self.assertEqual(m.definitive_contact_ids(contacts), {"ready", "missing"})

    def test_transient_fetch_failure_is_fail_closed_for_only_that_prospect(self):
        row = {"candidate_id": "retry", "company": "Retry Inc", "website": "https://retry.example"}
        with patch.object(m, "discover_contact", side_effect=m.ContactDiscoveryError("HTTP Error 429: Too Many Requests")):
            output, is_ready = m.contact_output(row, fetch=lambda url: "")
        self.assertFalse(is_ready)
        self.assertEqual(output["status"], m.RETRYABLE_CONTACT_STATUS)
        self.assertEqual(output["email"], "")
        self.assertIn("429", output["reason"])

    def test_ready_contact_output_remains_ready(self):
        row = {"candidate_id": "ready", "company": "Ready Inc", "website": "https://ready.example"}
        candidate = m.ContactCandidate(
            email="info@ready.example",
            source_url="https://ready.example/contact",
            source_kind="mailto",
            domain_alignment="aligned",
            mx_status="present",
            status="ready",
            reason="public business address found on official site with aligned domain and MX present",
            contact_role="",
            contact_priority_tier="generic",
        )
        with patch.object(m, "discover_contact", return_value=candidate):
            output, is_ready = m.contact_output(row, fetch=lambda url: "")
        self.assertTrue(is_ready)
        self.assertEqual(output["status"], "ready")
        self.assertEqual(output["email"], "info@ready.example")
        self.assertEqual(output["contact_priority_tier"], "generic")


if __name__ == "__main__":
    unittest.main()
