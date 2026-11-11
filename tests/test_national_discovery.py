import unittest
from unittest.mock import patch

import new_leads
from trigger_request import resolve_request


class NationalDiscoveryTests(unittest.TestCase):
    def test_twelve_regions_and_round_robin(self):
        visited = []
        index_by_region = {region: i + 1 for i, region in enumerate(new_leads.NATIONAL_HUBS)}

        def source(**kwargs):
            visited.append(kwargs["region"])
            idx = index_by_region[kwargs["region"]]
            return {"candidates": [
                {"name_hint": f"Sample {idx} A", "website_hint": f"https://sample{idx}a.nl"},
                {"name_hint": f"Sample {idx} B", "website_hint": f"https://sample{idx}b.nl"},
            ]}

        with patch("new_leads.load_discovery_suppressions", return_value=[]), \
             patch("new_leads.discover", side_effect=source):
            out = new_leads.run("Nederland", ["kapsalon", "bouwbedrijf"], 25, 18)
        self.assertEqual(set(visited), set(new_leads.NATIONAL_HUBS))
        self.assertEqual(len(visited), len(new_leads.NATIONAL_HUBS))
        self.assertEqual(out["counts"]["regions_scanned"], 12)
        self.assertEqual(out["counts"]["new_unverified_hints"], 18)
        self.assertEqual(out["counts"]["verified_new_leads"], 0)
        self.assertEqual(out["coverage"], "12_regional_centre_samples_not_exhaustive")
        self.assertEqual(out["candidates"][0]["company"], "Sample 1 A")
        self.assertEqual(out["candidates"][1]["company"], "Sample 2 A")
        self.assertEqual(out["emails_sent"], 0)
        self.assertEqual(out["mailbox_writes"], 0)

    def test_bounded_parallelism_preserves_results_and_improves_offline_latency(self):
        """Deterministic synthetic I/O benchmark; no live websites or Sheets."""
        from threading import Lock
        from time import perf_counter, sleep

        lock = Lock()
        active = 0
        highest = 0
        positions = {region: idx + 1 for idx, region in enumerate(new_leads.NATIONAL_HUBS)}

        def delayed_source(**kwargs):
            nonlocal active, highest
            with lock:
                active += 1
                highest = max(highest, active)
            sleep(0.04)  # Simulate the per-region remote download latency.
            with lock:
                active -= 1
            idx = positions[kwargs["region"]]
            return {"candidates": [
                {"name_hint": f"Fictief bedrijf {idx}", "website_hint": f"https://fictief-{idx}.example"}
            ]}

        started = perf_counter()
        baseline = [delayed_source(region=region)["candidates"]
                    for region in new_leads.NATIONAL_HUBS]
        baseline_time = perf_counter() - started
        self.assertEqual(highest, 1)  # Baseline really was sequential.

        started = perf_counter()
        with patch("new_leads.discover", side_effect=delayed_source):
            result = new_leads.discover_sampled_netherlands(["vakbedrijven"], 25, 100)
        parallel_time = perf_counter() - started
        self.assertEqual(result["candidates"], [x for group in baseline for x in group])
        self.assertEqual(result["regions_scanned"], 12)
        self.assertEqual(highest, new_leads.MAX_NATIONAL_DISCOVERY_WORKERS)
        self.assertEqual(active, 0)
        # Allow substantial CI scheduling variance, but confirm useful gain.
        self.assertLess(parallel_time, baseline_time * 0.85)
        print(f"NATIONAL_DISCOVERY_BENCH=green serial_s={baseline_time:.3f} "
              f"parallel_s={parallel_time:.3f} speedup={baseline_time / parallel_time:.2f}")

    def test_failure_in_later_region_is_anonymous_and_blocks_all(self):
        def source(**kwargs):
            if kwargs["region"] == "Middelburg":
                raise ValueError("private person@example.test")
            return {"candidates": []}

        with patch("new_leads.load_discovery_suppressions", return_value=[]), \
             patch("new_leads.discover", side_effect=source):
            with self.assertRaisesRegex(
                RuntimeError, "^national_region_10_source_unavailable$"
            ) as failure:
                new_leads.run("Nederland", ["vakbedrijven"], 25, 10)
        self.assertNotIn("person@example.test", str(failure.exception))

    def test_partial_region_failure_blocks_result(self):
        with patch("new_leads.load_discovery_suppressions", return_value=[]), \
             patch("new_leads.discover", side_effect=RuntimeError("down")):
            with self.assertRaisesRegex(RuntimeError, "^national_region_01_source_unavailable$"):
                new_leads.run("Heel Nederland", ["kapsalon"], 25, 30)

    def test_exception_source_details_are_not_logged(self):
        with patch("new_leads.load_discovery_suppressions", return_value=[]), \
             patch("new_leads.discover", side_effect=RuntimeError("private prospect@example.test")):
            with self.assertRaises(RuntimeError) as captured:
                new_leads.run("Nederland", ["bouwbedrijf"], 25, 30)
        self.assertEqual(str(captured.exception), "national_region_01_source_unavailable")
        self.assertNotIn("prospect@example.test", str(captured.exception))

    def test_live_suppressions_checked_before_national_download(self):
        with patch("new_leads.load_discovery_suppressions", side_effect=RuntimeError("no registry")), \
             patch("new_leads.discover") as source:
            with self.assertRaises(RuntimeError):
                new_leads.run("Nederland", ["bouwbedrijf"], 25, 30)
            source.assert_not_called()

    def test_unapproved_dispatch_does_not_trigger_discovery(self):
        with self.assertRaises(ValueError):
            resolve_request("workflow_dispatch", {}, {"execution_mode": "preflight"})
        accepted = resolve_request("workflow_dispatch", {}, {
            "execution_mode": "discover", "region": "Nederland",
            "keywords": "kapsalon,bouwbedrijf", "radius_km": "25", "limit": "30",
        })
        self.assertEqual(accepted, ("Nederland", "kapsalon,bouwbedrijf", "30", "25.0"))

    def test_workflow_discovery_is_manual_and_preflight_guarded(self):
        from pathlib import Path
        workflow = (Path(__file__).resolve().parents[1] /
                    ".github/workflows/fresh-leads.yml").read_text()
        self.assertNotIn("LEADS_PREFLIGHT_ONLY:", workflow)
        self.assertNotIn("LEADS_DISCOVERY_ONLY:", workflow)
        self.assertIn("github.event_name == 'workflow_dispatch'", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("python3 scripts/trigger_request.py", workflow)
        self.assertIn('FRESH_LEADS_PREFLIGHT=green', workflow)


if __name__ == "__main__":
    unittest.main()
