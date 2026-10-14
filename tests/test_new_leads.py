import unittest
from unittest.mock import patch
from new_leads import safe_hint, select_candidates, run
from dedupe_preflight import load_registry_values

HEADERS = ["company", "website", "domain", "emails", "status", "history",
           "lead_ids", "last_event_at", "sources", "exclude_from_new_leads"]


class NewLeadsTests(unittest.TestCase):
    def test_untrusted_urls_blocked(self):
        for value in ["http://localhost/", "http://127.0.0.1/",
                      "http://10.1.1.1/", "https://x.local/", "ftp://abc.nl",
                      "https://u:pass@abc.nl/", "https://fake.test/"]:
            self.assertEqual(safe_hint(value), "")
        self.assertEqual(safe_hint("https://bedrijf.nl/"), "https://bedrijf.nl/")

    def test_dedupe_and_run_duplicates(self):
        old = load_registry_values([HEADERS, ["Bekend BV", "https://bekend.nl",
            "bekend.nl", "info@bekend.nl", "sent", "", "", "", "", "TRUE"]])
        r = select_candidates({"candidates": [
            {"name_hint": "Bekend BV", "website_hint": "https://bekend.nl"},
            {"name_hint": "Nieuwe BV", "website_hint": "https://nieuw.nl"},
            {"name_hint": "Andere", "website_hint": "https://nieuw.nl/page"}]}, old, 10)
        self.assertEqual(r["counts"]["previously_used"], 1)
        self.assertEqual(r["counts"]["duplicate"], 1)
        self.assertEqual(r["counts"]["new_unverified_hints"], 1)
        self.assertEqual(r["counts"]["verified_new_leads"], 0)

    def test_oversamples_before_deduplication(self):
        known = load_registry_values([HEADERS, [
            "Known", "https://known.nl", "known.nl", "", "sent", "", "", "", "", "TRUE",
        ]])
        with patch("new_leads.load_suppressions", return_value=known), \
             patch("new_leads.discover", return_value={"candidates": []}) as discover:
            run("Leiden", ["winkel"], 8, 20)
        self.assertEqual(discover.call_args.kwargs["max_results"], 100)
        with patch("new_leads.load_suppressions", return_value=known), \
             patch("new_leads.discover", return_value={"candidates": []}) as discover:
            run("Leiden", ["winkel"], 8, 100)
        self.assertEqual(discover.call_args.kwargs["max_results"], 500)

    def test_missing_registry_fails_before_discovery(self):
        with patch("new_leads.load_suppressions", side_effect=RuntimeError()),              patch("new_leads.discover") as discovery:
            with self.assertRaises(RuntimeError):
                run("Leiden", ["winkel"], 8, 10)
            discovery.assert_not_called()
