import importlib.util
import pathlib
import sys
import unittest
from datetime import datetime, timezone

MODULE_PATH = pathlib.Path(__file__).parents[1] / "scripts" / "prospect_intelligence.py"
spec = importlib.util.spec_from_file_location("prospect_intelligence", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class Candidate:
    website = "https://www.example.nl/"
    company = "Example BV"
    source_id = "directory-a"
    source_type = "directory_index"
    source_url = "https://directory.example/list"
    country = "NL"
    matched_terms = ("wordpress", "woocommerce")


class ProspectIntelligenceTests(unittest.TestCase):
    def test_canonical_entity_and_observation_are_stable(self):
        self.assertEqual(module.canonical_domain("https://www.Example.nl/a"), "example.nl")
        self.assertEqual(module.entity_id_for_domain("example.nl"), module.entity_id_for_domain("https://www.example.nl/"))
        row = module.make_observation_row(
            run_id="123", observed_at="2026-09-05T10:00:00+00:00", candidate=Candidate(), outcome="duplicate"
        )
        self.assertEqual(row[module.OBSERVATION_HEADERS.index("outcome")], "duplicate")
        self.assertEqual(row[module.OBSERVATION_HEADERS.index("entity_id")], module.entity_id_for_domain("example.nl"))

    def test_target_is_bounded_and_reports_gap(self):
        self.assertEqual(module.clamp_target("200", 50), 50)
        self.assertEqual(module.clamp_target("bad", 50), 50)
        self.assertEqual(module.target_summary(7, 10), {"target_new": 10, "target_met": False, "target_gap": 3})

    def test_signals_fail_closed_and_require_known_candidate(self):
        base = {
            "candidate_id": "prospect-1",
            "detected_at": "2026-09-05T10:00:00+00:00",
            "signal_type": "hiring",
            "evidence_url": "https://example.nl/jobs",
            "evidence_date": "2026-09-05T00:00:00+00:00",
            "strength": "2",
            "confidence": "high",
            "source_id": "official-site",
            "status": "active",
            "note": "Vacaturepagina",
        }
        result = module.normalize_signal(base, known_candidate_ids={"prospect-1"})
        self.assertTrue(result["signal_id"].startswith("signal-"))
        bad = dict(base, strength="3")
        with self.assertRaises(ValueError):
            module.normalize_signal(bad, known_candidate_ids={"prospect-1"})
        with self.assertRaises(ValueError):
            module.normalize_signal(base, known_candidate_ids={"other"})

    def test_entities_use_observations_for_freshness(self):
        candidates = [{
            "candidate_id": "p1", "discovered_at": "2026-08-01T00:00:00+00:00",
            "company": "Example BV", "website": "https://example.nl/", "source_id": "s1", "status": "discovered",
        }]
        observations = [{
            "observed_at": "2026-09-04T00:00:00+00:00", "company": "Example B.V.",
            "website": "https://www.example.nl/", "source_id": "s2",
        }]
        rows = module.build_entities(
            candidates, observations, now=datetime(2026, 9, 5, tzinfo=timezone.utc), stale_days=30
        )
        self.assertEqual(len(rows), 1)
        record = dict(zip(module.ENTITY_HEADERS, rows[0]))
        self.assertEqual(record["canonical_domain"], "example.nl")
        self.assertEqual(record["freshness"], "fresh")
        self.assertIn("s1", record["source_ids"])
        self.assertIn("s2", record["source_ids"])

    def test_source_metrics_attribute_minimal_outcomes_by_domain(self):
        sources = [{"source_id": "s1", "approved": "TRUE", "enabled": "TRUE"}]
        candidates = [{
            "candidate_id": "p1", "company": "Example", "website": "https://example.nl/",
            "source_id": "s1", "status": "qualified",
        }]
        contacts = [{"candidate_id": "p1", "status": "ready"}]
        leads = [{"Website": "https://www.example.nl/", "Status": "klant"}]
        signals = [{"candidate_id": "p1", "status": "active", "strength": "2"}]
        rows = module.build_source_metrics(sources, candidates, contacts, leads, signals, generated_at="now")
        metric = dict(zip(module.SOURCE_METRIC_HEADERS, rows[0]))
        self.assertEqual(metric["qualified"], 1)
        self.assertEqual(metric["contacts_ready"], 1)
        self.assertEqual(metric["strong_signals"], 1)
        self.assertEqual(metric["lead_customer"], 1)
        self.assertEqual(metric["qualification_rate"], "1.0000")

    def test_evidence_graph_links_source_signal_contact_and_outcome(self):
        candidates = [{
            "candidate_id": "p1", "discovered_at": "2026-09-01T00:00:00+00:00",
            "company": "Example", "website": "https://example.nl/", "source_id": "s1",
            "source_url": "https://directory.example/", "status": "qualified",
        }]
        signals = [{
            "signal_id": "sig1", "candidate_id": "p1", "detected_at": "2026-09-02T00:00:00+00:00",
            "source_id": "official-site", "signal_type": "hiring", "evidence_url": "https://example.nl/jobs",
            "confidence": "high", "strength": "2", "status": "active",
        }]
        contacts = [{
            "candidate_id": "p1", "checked_at": "2026-09-03T00:00:00+00:00",
            "status": "ready", "source_url": "https://example.nl/contact", "reason": "official-site",
        }]
        leads = [{"Website": "https://example.nl/", "Status": "positief"}]
        edges = module.build_evidence_edges(candidates, signals, contacts, leads)
        types = {row[module.EVIDENCE_HEADERS.index("edge_type")] for row in edges}
        self.assertEqual(types, {"source_discovery", "signal", "contact_evidence", "lead_outcome"})

    def test_lookalike_is_advisory_and_uses_customer_seed(self):
        candidates = [
            {"candidate_id": "seed", "website": "https://seed.nl/", "matched_terms": "wordpress, woocommerce", "country": "NL"},
            {"candidate_id": "other", "website": "https://other.nl/", "matched_terms": "wordpress", "country": "NL"},
        ]
        leads = [{"Website": "https://seed.nl/", "Status": "klant"}]
        rows = module.build_lookalike_recommendations(candidates, leads, generated_at="now")
        self.assertEqual(len(rows), 1)
        record = dict(zip(module.LOOKALIKE_HEADERS, rows[0]))
        self.assertEqual(record["candidate_id"], "other")
        self.assertGreater(float(record["similarity"]), 0)
        self.assertIn("never changes Customer Potential", record["note"])


if __name__ == "__main__":
    unittest.main()
