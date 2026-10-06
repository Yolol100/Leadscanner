import os
import unittest
from unittest.mock import patch

from extract_public_contacts import extract_verified_observation
from observation_quality import business_sentences, natural_opening, observation_rejection
from prepare_growth_batch import build_opening, exact_nl_opening_from_existing
from myhost_opening_remediation import _website_workers, replace_opening, validate_request


class ObservationQualityTests(unittest.TestCase):
    def test_metadata_regression_is_blocked_at_extraction_and_generation(self):
        bad = "Restaurant Groningen | Dinercafé Plezant | Diephuisstraat 6 Groningen"
        self.assertIsNotNone(observation_rejection(bad))
        self.assertIsNone(extract_verified_observation(f'<title>{bad}</title><meta name="description" content="{bad}"><p>{bad}</p>'))
        with self.assertRaises(ValueError):
            build_opening("Voorbeeld", "nl", bad)
        with self.assertRaises(ValueError):
            exact_nl_opening_from_existing("Ik zag op jullie website dat " + bad + ".")

    def test_title_address_category_and_keywords_are_not_sentences(self):
        for bad in ("Restaurant Utrecht – Voorbeeld – Centrum", "Voorbeeld Restaurant Dorpsstraat 8 Utrecht", "Fysiotherapie in Utrecht", "Voorbeeld, kapsalon, krullen, knippen, beauty", "Welkom op onze website", "Onze klantenservice staat voor u klaar"):
            with self.subTest(bad=bad):
                self.assertIsNotNone(observation_rejection(bad))

    def test_first_party_business_prose_wins_over_metadata_footer_and_reviews(self):
        html = '<head><title>Wij verkopen fietsen in Delft.</title></head><nav><p>Wij verkopen fietsen in Delft.</p></nav><main><p>Wij maken keukens op maat.</p></main><footer><p>Wij verkopen fietsen in Delft.</p></footer><div class="reviews"><p>Wij verkopen fietsen in Delft.</p></div>'
        self.assertEqual(business_sentences(html), ["Wij maken keukens op maat."])
        self.assertEqual(extract_verified_observation(html), "Wij maken keukens op maat.")

    def test_root_template_and_consent_classes_do_not_hide_main_prose(self):
        for marker in ('page-template-elementor_header_footer', 'cookies-not-set'):
            html = f'<html><body class="{marker}"><main><p>Wij serveren tapas.</p></main><div class="cookie-banner"><p>Wij verkopen fietsen.</p></div><footer><p>Wij verkopen fietsen.</p></footer></body></html>'
            self.assertEqual(business_sentences(html), ['Wij serveren tapas.'])

    def test_one_fact_natural_dutch_and_english(self):
        self.assertEqual(natural_opening("Wij serveren tapas.", "nl"), "Ik zag op jullie website dat jullie tapas serveren.")
        self.assertEqual(natural_opening("Wij bieden lunch en diner.", "nl"), "Ik zag op jullie website dat jullie lunch en diner aanbieden.")
        self.assertEqual(natural_opening("Wij zijn gespecialiseerd in maatwerkkeukens.", "nl"), "Ik zag op jullie website dat jullie gespecialiseerd zijn in maatwerkkeukens.")
        self.assertEqual(natural_opening("We provide bespoke kitchen furniture.", "en"), "I saw on your website that you provide bespoke kitchen furniture.")
        self.assertIsNotNone(observation_rejection("Wij verkopen fietsen en bieden onderhoud in Delft."))

    def test_narrative_and_review_fragments_cannot_hide_a_predicate(self):
        for bad in ("We weten hoe lastig het is om geen fiets te hebben.", "Wij willen meer zijn dan een sportschool.", "Wij begrijpen dat motivatie moeilijk is, daarom bieden wij training aan.", "We hebben beiden een steak gehad."):
            self.assertIsNotNone(observation_rejection(bad))

    def test_opening_only_replacement_preserves_offer_subject_independent_body(self):
        tail = '\n\nMet mijn Groeiabonnement:\n• Website/webshop\n€250–€500\nCTA\nOpt-out\nGroet,\nAndrew'
        old = 'Hallo,\n\nIk zag op jullie website dat metadata.' + tail
        new = replace_opening(old, 'Ik zag op jullie website dat jullie lunch aanbieden.')
        self.assertEqual(new, 'Hallo,\n\nIk zag op jullie website dat jullie lunch aanbieden.' + tail)

    def test_parallel_website_workers_remain_bounded(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_website_workers(100), 20)
        with patch.dict(os.environ, {"LEADSCANNER_WEBSITE_WORKERS": "999"}):
            self.assertEqual(_website_workers(100), 24)

    def test_writes_require_bounded_source_and_immutable_audit(self):
        req = {"mode": "audit", "source_archive_artifact_id": 1, "source_artifact_ids": [1], "offset": 0, "limit": 100}
        self.assertEqual(validate_request(req), req)
        for change in ({"limit": 101}, {"mode": "apply"}, {"source_artifact_ids": [1, 1]}, {"offset": -1}):
            with self.assertRaises(ValueError):
                validate_request({**req, **change})


if __name__ == '__main__':
    unittest.main()
