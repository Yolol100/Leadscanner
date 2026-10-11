"""Regressions for broad, evidence-bound, ranked site findings."""
import unittest
from unittest.mock import patch

from cold_stages import broad_research_links, parse_html
from outreach_stages import select_one_reason, value_action_for, body_for, validate_mail
from instantly_historical_site_research import draft_for_review


def item(text, path):
    return {
        "text": text, "source_type": "official_site",
        "source_url": "https://sample.nl/" + path, "page_type": "detail",
    }


class BroadFindingsTests(unittest.TestCase):
    def test_unlisted_category_is_not_discarded(self):
        row = {
            "research_status": "ready", "official_domain": "sample.nl",
            "evidence_candidates": [
                item("Onze klanten ontvangen een persoonlijke handleiding na elke installatie.", "installatie"),
            ],
        }
        selected = select_one_reason(row)
        self.assertEqual(selected["outreach_status"], "ready")
        self.assertEqual(selected["selected_findings"][0]["category"], "other")
        self.assertEqual(selected["selected_findings"][0]["source_type"], "official_site")

    def test_ranked_findings_are_diverse_and_bounded(self):
        texts = [
            ("Klanten kunnen online een afspraak aanvragen voor de jaarlijkse onderhoudsbeurt.", "afspraak"),
            ("Vraag online een offerte aan via ons formulier voor maatwerk.", "offerte"),
            ("Bestel online uw onderdelen en kies het gewenste afleveradres.", "bestellen"),
            ("Onze klanten vinden antwoorden in de kennisbank met veelgestelde vragen.", "faq"),
            ("U kunt uw bestelling retourneren via ons retourformulier voor klanten.", "retouren"),
            ("Bekijk onze projecten met praktijkvoorbeelden van gerealiseerde installaties.", "projecten"),
            ("Onze monteurs installeren apparatuur voor zakelijke klanten in Nederland.", "installaties"),
        ]
        row = {
            "research_status": "ready", "official_domain": "sample.nl",
            "evidence_candidates": [item(text, path) for text, path in texts],
        }
        selected = select_one_reason(row)
        findings = selected["selected_findings"]
        self.assertEqual(len(findings), 5)
        self.assertEqual(findings[0]["category"], "appointment")
        self.assertEqual(len({f["category"] for f in findings}), 5)
        self.assertTrue(all(f["score"] >= 70 for f in findings))
        self.assertTrue(all(f["source_url"].startswith("https://sample.nl/") for f in findings))
        valued = value_action_for(selected)
        self.assertEqual(valued["value_action_status"], "proposed")
        mail = body_for(valued)
        self.assertEqual(mail.count("?"), 1)
        self.assertTrue(all(f["observation"].split()[0] in mail for f in findings))
        self.assertNotIn("review_findings_missing_or_unverified", validate_mail(valued, "ideeën op basis van jullie website", mail))
        self.assertLessEqual(len(mail.split()), 155)
        subject, draft = draft_for_review(
            selected["verified_observation"], valued["value_first_action"],
            selected["signal_type"], selected["language"], findings,
        )
        self.assertTrue(subject)
        self.assertEqual(draft.count("?"), 1)

    def test_portfolio_is_not_promoted_by_irrelevant_process_context(self):
        from outreach_stages import classify_evidence
        result = classify_evidence({
            "text": "Bekijk onze projecten met praktijkvoorbeelden van gerealiseerde installaties.",
            "source_type": "official_site",
            "source_url": "https://sample.nl/werkwijze",
            "page_type": "process",
        })
        self.assertEqual(result["signal_type"], "portfolio")
        self.assertEqual(result["signal_score"], 63)

    def test_weak_other_does_not_fill_email_to_six_points(self):
        row = {
            "research_status": "ready", "official_domain": "sample.nl",
            "evidence_candidates": [
                item("Onze klanten ontvangen een persoonlijke handleiding na iedere installatie.", "installatie"),
                item("Bezoekers bekijken vooraf een demonstratie van onze apparatuur op de website.", "demo"),
                item("Zakelijke klanten kiezen vooraf een persoonlijke uitleg over onze werkwijze.", "uitleg"),
                item("Gebruikers downloaden op verzoek een praktische introductie van onze producten.", "intro"),
            ],
        }
        findings = select_one_reason(row)["selected_findings"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["category"], "other")

    def test_generic_other_without_action_is_not_promoted(self):
        result = select_one_reason({
            "research_status": "ready", "official_domain": "sample.nl",
            "evidence_candidates": [
                item("Onze medewerkers werken iedere dag met veel enthousiasme in de werkplaats.", "team"),
            ],
        })
        self.assertEqual(result["outreach_status"], "hold")

    def test_only_same_domain_evidence_is_selected(self):
        row = {
            "research_status": "ready", "official_domain": "sample.nl",
            "evidence_candidates": [
                item("Onze klanten ontvangen een persoonlijke handleiding na elke installatie.", "installatie"),
                {"text": "Klanten kunnen online een afspraak aanvragen voor onderhoud.",
                 "source_url": "https://attacker.example/afspraak", "source_type": "official_site",
                 "page_type": "process"},
            ],
        }
        findings = select_one_reason(row)["selected_findings"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["category"], "other")

    def test_generic_marketing_is_still_held(self):
        row = {
            "research_status": "ready", "official_domain": "sample.nl",
            "evidence_candidates": [item("Wij leveren kwaliteit en goede service met persoonlijke aandacht.", "over-ons")],
        }
        self.assertEqual(select_one_reason(row)["outreach_status"], "hold")

    def test_broad_links_include_unknown_pages_but_exclude_sensitive_routes(self):
        html = """<a href="/installatie">Installatie</a>
        <a href="/retouren">Retouren</a>
        <a href="/iets-nieuws">Andere info</a>
        <a href="/checkout">Afrekenen</a>
        <a href="https://external.example/path">Externe site</a>"""
        links = broad_research_links(parse_html(html), "https://sample.nl/", "sample.nl")
        self.assertIn("https://sample.nl/installatie", links)
        self.assertIn("https://sample.nl/retouren", links)
        self.assertNotIn("https://sample.nl/checkout", links)
        self.assertFalse(any("external.example" in url for url in links))


if __name__ == "__main__":
    unittest.main()
