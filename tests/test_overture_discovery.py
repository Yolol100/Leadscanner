import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from overture_discovery import (
    bbox_from_center,
    download_overture_places,
    parse_bbox,
    probe_candidates,
    probe_website,
    read_candidates,
    resolve_region_center,
)


class FakePDOK:
    def get(self, url, params, headers, timeout):
        response = Mock()
        response.raise_for_status = Mock()
        if params["fq"] == "type:woonplaats":
            response.json.return_value = {
                "response": {
                    "docs": [
                        {
                            "id": "woonplaats-rotterdam",
                            "weergavenaam": "Rotterdam",
                            "type": "woonplaats",
                            "centroide_ll": "POINT(4.477733 51.924442)",
                        }
                    ]
                }
            }
        else:
            response.json.return_value = {"response": {"docs": []}}
        return response


class OvertureDiscoveryTests(unittest.TestCase):
    def feature(self, *, fid, name, category, website=None, confidence=0.8, status="open"):
        props = {
            "names": {"primary": name},
            "basic_category": category,
            "confidence": confidence,
            "operating_status": status,
            "emails": ["must-not-leak@example.test"],
            "phones": ["+31000000000"],
            "socials": ["https://social.example/test"],
        }
        if website:
            props["websites"] = [website]
        return {
            "type": "Feature",
            "id": fid,
            "properties": props,
            "geometry": {"type": "Point", "coordinates": [4.48, 51.92]},
        }

    def write_geojsonseq(self, items):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".geojsonseq", delete=False, encoding="utf-8")
        for item in items:
            tmp.write("\x1e" + json.dumps(item) + "\n")
        tmp.close()
        return Path(tmp.name)

    def test_pdok_region_resolution_needs_no_authentication(self):
        result = resolve_region_center("Rotterdam", session=FakePDOK())
        self.assertEqual(result["resolved_name"], "Rotterdam")
        self.assertEqual(result["resolved_type"], "woonplaats")
        self.assertEqual(result["authentication"], "none")
        self.assertAlmostEqual(result["lon"], 4.477733)
        self.assertAlmostEqual(result["lat"], 51.924442)

    def test_bbox_from_center_is_bounded(self):
        west, south, east, north = bbox_from_center(4.477733, 51.924442, 8)
        self.assertLess(west, 4.477733)
        self.assertGreater(east, 4.477733)
        self.assertLess(south, 51.924442)
        self.assertGreater(north, 51.924442)
        with self.assertRaises(ValueError):
            bbox_from_center(4.477733, 51.924442, 100)

    def test_parse_bbox_rejects_invalid_order(self):
        self.assertEqual(parse_bbox("4.3,51.8,4.7,52.1"), (4.3, 51.8, 4.7, 52.1))
        with self.assertRaises(ValueError):
            parse_bbox("4.7,51.8,4.3,52.1")

    @patch("overture_discovery.shutil.which", return_value="/usr/local/bin/overturemaps")
    def test_download_uses_official_cli_without_credentials(self, which):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "places.geojsonseq"

            def fake_runner(args, check, capture_output, text, timeout):
                self.assertEqual(args[0], "/usr/local/bin/overturemaps")
                self.assertEqual(args[1:3], ["download", "--bbox"])
                self.assertIn("geojsonseq", args)
                self.assertIn("place", args)
                self.assertFalse(any("key" in str(arg).casefold() for arg in args))
                output.write_text("", encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            download_overture_places((4.3, 51.8, 4.7, 52.1), output, runner=fake_runner)
            self.assertTrue(output.exists())

    def test_candidate_filter_emits_no_contact_fields(self):
        path = self.write_geojsonseq(
            [
                self.feature(
                    fid="overture-1",
                    name="Bakker Een",
                    category="bakery",
                    website="https://bakker.example/",
                    confidence=0.9,
                ),
                self.feature(
                    fid="overture-2",
                    name="Andere Winkel",
                    category="retail",
                    website="https://retail.example/",
                    confidence=0.99,
                ),
            ]
        )
        try:
            rows = read_candidates(
                path,
                keywords=["bakery"],
                max_results=10,
                require_website=True,
            )
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["overture_id"], "overture-1")
        self.assertEqual(rows[0]["website_hint"], "https://bakker.example/")
        serialized = json.dumps(rows)
        self.assertNotIn("must-not-leak@example.test", serialized)
        self.assertNotIn("+31000000000", serialized)
        self.assertNotIn("social.example", serialized)
        self.assertEqual(rows[0]["identity_status"], "needs_leads_verification")

    def test_closed_and_no_website_candidates_can_be_removed(self):
        path = self.write_geojsonseq(
            [
                self.feature(
                    fid="closed",
                    name="Closed Bakery",
                    category="bakery",
                    website="https://closed.example/",
                    status="closed_permanently",
                ),
                self.feature(
                    fid="no-site",
                    name="No Site Bakery",
                    category="bakery",
                    website=None,
                ),
                self.feature(
                    fid="open",
                    name="Open Bakery",
                    category="bakery",
                    website="https://open.example/",
                ),
            ]
        )
        try:
            rows = read_candidates(
                path,
                keywords=["bakery"],
                max_results=10,
                require_website=True,
            )
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual([row["overture_id"] for row in rows], ["open"])

    def test_broad_taxonomy_does_not_create_false_positive(self):
        item = self.feature(
            fid="supermarket",
            name="Generic Supermarket",
            category="food_and_beverage_store",
            website="https://market.example/",
            confidence=0.99,
        )
        item["properties"]["categories"] = {"alternate": ["bakery", "pastry"]}
        item["properties"]["taxonomy"] = {"theme": ["bakery"]}
        path = self.write_geojsonseq([item])
        try:
            rows = read_candidates(
                path,
                keywords=["bakery"],
                max_results=10,
                require_website=True,
            )
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(rows, [])

    def test_duplicate_overture_records_are_deduplicated(self):
        duplicate = self.feature(
            fid="dup-1",
            name="Duplicate Bakery",
            category="bakery",
            website="https://duplicate.example/",
            confidence=0.9,
        )
        path = self.write_geojsonseq([duplicate, duplicate])
        try:
            rows = read_candidates(
                path,
                keywords=["bakery"],
                max_results=10,
                require_website=True,
            )
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["overture_id"], "dup-1")

    def test_direct_discovery_max_results_is_bounded_to_100(self):
        path = self.write_geojsonseq([])
        try:
            with self.assertRaises(ValueError):
                read_candidates(
                    path,
                    keywords=[],
                    max_results=101,
                    require_website=False,
                )
        finally:
            path.unlink(missing_ok=True)

    def test_closed_status_variants_are_excluded(self):
        path = self.write_geojsonseq(
            [
                self.feature(
                    fid="closed",
                    name="Closed Bakery",
                    category="bakery",
                    website="https://closed.example/",
                    status="closed",
                ),
                self.feature(
                    fid="open",
                    name="Open Bakery",
                    category="bakery",
                    website="https://open.example/",
                    status="open",
                ),
            ]
        )
        try:
            rows = read_candidates(
                path,
                keywords=["bakery"],
                max_results=10,
                require_website=True,
            )
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual([row["overture_id"] for row in rows], ["open"])

    @patch("overture_discovery.requests.get")
    def test_website_probe_is_non_authorizing_direct_readback(self, get):
        response = Mock()
        response.status_code = 200
        response.url = "https://final.example/"
        response.close = Mock()
        get.return_value = response
        result = probe_website("https://hint.example/")
        self.assertEqual(result["status"], "reachable_needs_leads_identity_verification")
        self.assertEqual(result["final_url"], "https://final.example/")
        response.close.assert_called_once()

    def test_probe_candidates_is_bounded_and_preserves_order(self):
        candidates = [
            {"website_hint": "https://one.example/"},
            {"website_hint": "https://two.example/"},
            {"website_hint": None},
        ]

        def fake_probe(url):
            if "two" in url:
                raise RuntimeError("synthetic probe failure")
            return {
                "status": "reachable_needs_leads_identity_verification",
                "final_url": url,
                "http_status": 200,
                "detail": None,
            }

        results = probe_candidates(candidates, probe=fake_probe, max_workers=2)
        self.assertEqual(results[0]["final_url"], "https://one.example/")
        self.assertEqual(results[1]["status"], "unreachable")
        self.assertEqual(results[1]["detail"], "probe_error:RuntimeError")
        self.assertEqual(results[2]["status"], "not_available")

        with self.assertRaises(ValueError):
            probe_candidates(candidates, probe=fake_probe, max_workers=9)



if __name__ == "__main__":
    unittest.main()
