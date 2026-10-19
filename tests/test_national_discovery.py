import unittest
from unittest.mock import patch

import new_leads
from trigger_request import resolve_request


class NationalDiscoveryTests(unittest.TestCase):
    def test_twelve_regions_and_round_robin(self):
        visited = []

        def source(**kwargs):
            visited.append(kwargs["region"])
            idx = len(visited)
            return {"candidates": [
                {"name_hint": f"Sample {idx} A", "website_hint": f"https://sample{idx}a.nl"},
                {"name_hint": f"Sample {idx} B", "website_hint": f"https://sample{idx}b.nl"},
            ]}

        with patch("new_leads.load_discovery_suppressions", return_value=[]), \
             patch("new_leads.discover", side_effect=source):
            out = new_leads.run("Nederland", ["kapsalon", "bouwbedrijf"], 25, 18)
        self.assertEqual(tuple(visited), new_leads.NATIONAL_HUBS)
        self.assertEqual(out["counts"]["regions_scanned"], 12)
        self.assertEqual(out["counts"]["new_unverified_hints"], 18)
        self.assertEqual(out["counts"]["verified_new_leads"], 0)
        self.assertEqual(out["coverage"], "12_regional_centre_samples_not_exhaustive")
        self.assertEqual(out["candidates"][0]["company"], "Sample 1 A")
        self.assertEqual(out["candidates"][1]["company"], "Sample 2 A")
        self.assertEqual(out["emails_sent"], 0)
        self.assertEqual(out["mailbox_writes"], 0)

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

    def test_push_request_is_bounded_and_has_no_shell_interpolation(self):
        request = resolve_request("push", {
            "head_commit": {"message": "LEADS_DISCOVERY_ONLY: Nederland|kapsalon,bouwbedrijf|30"}
        }, {})
        self.assertEqual(request, ("Nederland", "kapsalon,bouwbedrijf", "30", "25.0"))
        for message in (
            "LEADS_DISCOVERY_ONLY: Nederland; echo BAD|kapsalon|30",
            "LEADS_DISCOVERY_ONLY: Nederland|kapsalon|101",
            "LEADS_DISCOVERY_ONLY: Nederland|kapsalon|0",
            "LEADS_DISCOVERY_ONLY: Nederland|kapsalon|30; ls",
            "LEADS_PREFLIGHT_ONLY: noop",
        ):
            with self.assertRaises(ValueError):
                resolve_request("push", {"head_commit": {"message": message}}, {})

    def test_unapproved_dispatch_does_not_trigger_discovery(self):
        with self.assertRaises(ValueError):
            resolve_request("workflow_dispatch", {}, {"execution_mode": "preflight"})
        accepted = resolve_request("workflow_dispatch", {}, {
            "execution_mode": "discover", "region": "Nederland",
            "keywords": "kapsalon,bouwbedrijf", "radius_km": "25", "limit": "30",
        })
        self.assertEqual(accepted, ("Nederland", "kapsalon,bouwbedrijf", "30", "25.0"))

    def test_workflow_requires_two_distinct_run_markers(self):
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
