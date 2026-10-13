import unittest

from verified_site_issues import markup_issues, verified_broken_link


class VerifiedIssueTests(unittest.TestCase):
    def test_static_unlabeled_form_and_image_link_are_observable(self):
        html = ('<form><input type="email" id="email"></form>'
                '<a href="/winkel"><img src="shop.png"></a>')
        issues = markup_issues(html, "https://example.nl/contact")
        self.assertEqual([x["category"] for x in issues],
                         ["unlabeled_form_control", "unnamed_image_link"])
        self.assertTrue(all(x["source_type"] == "official_site" for x in issues))

    def test_explicit_and_nested_labels_prevent_false_positive(self):
        html = ('<form><label for="mail">Email</label><input id="mail">'
                '<label>Bericht <textarea></textarea></label></form>'
                '<a href="/"><img src="logo.png" alt="Home"></a>')
        self.assertEqual(markup_issues(html, "https://example.nl/contact"), [])

    def test_aria_labels_prevent_false_positive(self):
        html = ('<form><input type="text" aria-labelledby="name"></form>'
                '<a aria-label="Winkel" href="/winkel"><img src="shop.png"></a>')
        self.assertEqual(markup_issues(html, "https://example.nl"), [])

    def test_live_review_requires_two_distinct_verified_site_issues(self):
        from outreach_stages import (
            select_one_reason, value_action_for, generate_one_mail,
        )
        candidate = {
            "research_status": "ready", "official_domain": "example.nl",
            "public_business_email": "info@example.nl",
            "contact_status": "verified_official_site",
            "evidence_candidates": [
                {"text": "Klanten kunnen via onze website een afspraak maken voor onderhoud.",
                 "source_url": "https://example.nl/afspraak", "source_type": "official_site"},
                {"text": "Wij bieden onze klanten een online formulier voor een offerteaanvraag.",
                 "source_url": "https://example.nl/offerte", "source_type": "official_site"},
            ],
            "site_issue_candidates": [
                {"category": "broken_internal_link", "source_type": "official_site",
                 "source_url": "https://example.nl/diensten", "severity": 100,
                 "observation_nl": "Een interne link naar de productpagina geeft bij twee controles de status HTTP 404"},
                {"category": "unlabeled_form_control", "source_type": "official_site",
                 "source_url": "https://example.nl/contact", "severity": 90,
                 "observation_nl": "Een invoerveld in het contactformulier heeft geen correct gekoppeld toegankelijk label"},
            ],
        }
        result = generate_one_mail(value_action_for(select_one_reason(candidate)))
        self.assertEqual(result["mail_status"], "ready_for_human_review")
        self.assertEqual(len(result["selected_findings"]), 2)
        self.assertEqual(result["body"].count("Verbeteridee:"), 2)
        self.assertTrue(result["subject"].startswith("2 technische aandachtspunten"))
        self.assertFalse(result["automatic_send"])
        candidate["site_issue_candidates"] = []
        self.assertEqual(select_one_reason(candidate)["outreach_status"], "hold")
        candidate["site_issue_candidates"] = [
            {**result["selected_findings"][0], "severity": 100,
             "observation_nl": result["selected_findings"][0]["observation"]}
        ]
        self.assertEqual(select_one_reason(candidate)["outreach_status"], "hold")

    def test_offsite_issue_can_never_count_as_researched_error(self):
        from outreach_stages import select_one_reason
        candidate = {
            "research_status": "ready", "official_domain": "example.nl",
            "evidence_candidates": [
                {"text": "Onze klanten kunnen online een afspraak maken voor hun onderhoud.",
                 "source_url": "https://example.nl/afspraak", "source_type": "official_site"},
                {"text": "Wij geven alle bezoekers een duidelijke route voor het contactformulier.",
                 "source_url": "https://example.nl/contact", "source_type": "official_site"},
            ],
            "site_issue_candidates": [
                {"category": "broken_internal_link", "source_type": "official_site",
                 "source_url": "https://unrelated.example/", "severity": 100,
                 "observation_nl": "Een interne link geeft bij twee controles een duidelijke foutmelding"},
                {"category": "unnamed_image_link", "source_type": "official_site",
                 "source_url": "https://example.nl/", "severity": 85,
                 "observation_nl": "Een afbeeldingslink mist in de HTML een toegankelijke naam voor bezoekers"},
            ],
        }
        self.assertEqual(select_one_reason(candidate)["outreach_status"], "hold")

    def test_broken_link_requires_repeat_check_in_caller(self):
        issue = verified_broken_link("https://example.nl/diensten",
                                     "https://example.nl/removed?private=1")
        self.assertIn("/removed", issue["observation_nl"])
        self.assertNotIn("private", issue["observation_nl"])
        self.assertEqual(issue["severity"], 100)


if __name__ == "__main__":
    unittest.main()
