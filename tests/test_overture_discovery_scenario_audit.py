import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from overture_discovery import (
    bbox_from_center,
    discover,
    download_overture_places,
    probe_website,
    read_candidates,
    resolve_region_center,
)
from run_overture_discovery_request import load_request


class ScenarioAuditTests(unittest.TestCase):
    def feature(self, i, *, category="bakery", website=True, status="open", name=None):
        props = {
            "names": {"primary": name or f"Bakery {i}"},
            "basic_category": category,
            "confidence": 0.9,
            "operating_status": status,
            "emails": ["must-not-leak@example.test"],
            "phones": ["+31000000000"],
            "socials": ["https://social.example/test"],
        }
        if website:
            props["websites"] = [f"https://bakery{i}.example/"]
        return {
            "type": "Feature",
            "id": f"id-{i}",
            "properties": props,
            "geometry": {"type": "Point", "coordinates": [4.48, 51.92]},
        }

    def geo(self, items):
        h = tempfile.NamedTemporaryFile(mode="w", suffix=".geojsonseq", delete=False, encoding="utf-8")
        for item in items:
            h.write("\x1e" + json.dumps(item) + "\n")
        h.close()
        return Path(h.name)

    def request(self, **overrides):
        data = {
            "request_id": "scenario-audit-001",
            "enabled": True,
            "region": "Rotterdam",
            "radius_km": 8,
            "keywords": ["bakery"],
            "max_results": 10,
            "require_website": True,
            "probe_websites": True,
        }
        data.update(overrides)
        h = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, h)
        h.close()
        return Path(h.name)

    def rows(self, items, n=100, require=True):
        p = self.geo(items)
        try:
            return read_candidates(p, keywords=["bakery"], max_results=n, require_website=require)
        finally:
            p.unlink(missing_ok=True)

    def test_01_normal_region_branch_contract(self):
        p = self.request()
        try:
            r = load_request(p)
        finally:
            p.unlink(missing_ok=True)
        self.assertEqual(r["region"], "Rotterdam")
        self.assertIsNone(r["bbox"])

    def test_02_zero_results(self):
        self.assertEqual(self.rows([]), [])

    def test_03_duplicate_records(self):
        x = self.feature(1)
        self.assertEqual(len(self.rows([x, x])), 1)

    def test_04_missing_website_is_filtered(self):
        self.assertEqual(self.rows([self.feature(1, website=False)]), [])

    @patch("overture_discovery.requests.get")
    def test_05_redirect_preserves_final_url_without_authorizing_identity(self, get):
        response = Mock(status_code=200, url="https://final.example/")
        response.close = Mock()
        get.return_value = response
        r = probe_website("https://start.example/")
        self.assertEqual(r["final_url"], "https://final.example/")
        self.assertEqual(r["status"], "reachable_needs_leads_identity_verification")

    @patch("overture_discovery.requests.get", side_effect=requests.ConnectionError())
    def test_06_unreachable_website(self, _):
        r = probe_website("https://down.example/")
        self.assertEqual(r["status"], "unreachable")

    def test_07_identity_never_auto_authorized(self):
        row = self.rows([self.feature(1)])[0]
        self.assertEqual(row["identity_status"], "needs_leads_verification")

    def test_08_closed_is_filtered(self):
        self.assertEqual(self.rows([self.feature(1, status="closed")]), [])

    def test_09_category_noise_is_filtered(self):
        x = self.feature(1, category="supermarket", name="Generic Supermarket")
        x["properties"]["taxonomy"] = {"theme": ["bakery"]}
        self.assertEqual(self.rows([x]), [])

    def test_10_pdok_no_match_fails_closed(self):
        session = Mock()
        response = Mock()
        response.raise_for_status = Mock()
        response.json.return_value = {"response": {"docs": []}}
        session.get.return_value = response
        with self.assertRaises(RuntimeError):
            resolve_region_center("NoSuchPlace", session=session)

    def test_11_pdok_unavailable_fails_closed(self):
        session = Mock()
        session.get.side_effect = requests.ConnectionError("offline")
        with self.assertRaises(requests.ConnectionError):
            resolve_region_center("Rotterdam", session=session)

    @patch("overture_discovery.shutil.which", return_value="/usr/bin/overturemaps")
    def test_12_overture_unavailable_fails_closed(self, _):
        runner = Mock(return_value=Mock(returncode=1, stderr="offline", stdout=""))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):
                download_overture_places((4.3, 51.8, 4.7, 52.1), Path(d) / "x", runner=runner)

    def test_13_radius_min_boundary(self):
        self.assertEqual(len(bbox_from_center(4.4, 51.9, 0.5)), 4)

    def test_14_radius_max_boundary(self):
        self.assertEqual(len(bbox_from_center(4.4, 51.9, 50)), 4)

    def test_15_radius_outside_boundary_rejected(self):
        for value in (0.49, 50.01):
            with self.assertRaises(ValueError):
                bbox_from_center(4.4, 51.9, value)

    def test_16_one_candidate(self):
        self.assertEqual(len(self.rows([self.feature(1)], n=1)), 1)

    def test_17_ten_candidates(self):
        self.assertEqual(len(self.rows([self.feature(i) for i in range(10)], n=10)), 10)

    def test_18_twentyfive_candidates(self):
        self.assertEqual(len(self.rows([self.feature(i) for i in range(25)], n=25)), 25)

    def test_19_fifty_candidates(self):
        self.assertEqual(len(self.rows([self.feature(i) for i in range(50)], n=50)), 50)

    def test_20_hundred_candidates(self):
        self.assertEqual(len(self.rows([self.feature(i) for i in range(100)], n=100)), 100)

    def test_21_over_hundred_runtime_request_rejected(self):
        p = self.request(max_results=101)
        try:
            with self.assertRaises(ValueError):
                load_request(p)
        finally:
            p.unlink(missing_ok=True)

    def test_22_over_twelve_keywords_rejected(self):
        p = self.request(keywords=[f"k{i}" for i in range(13)])
        try:
            with self.assertRaises(ValueError):
                load_request(p)
        finally:
            p.unlink(missing_ok=True)

    def test_23_region_and_bbox_rejected(self):
        p = self.request(bbox="4.3,51.8,4.7,52.1")
        try:
            with self.assertRaises(ValueError):
                load_request(p)
        finally:
            p.unlink(missing_ok=True)

    def test_24_missing_region_and_bbox_rejected(self):
        p = self.request(region="")
        try:
            with self.assertRaises(ValueError):
                load_request(p)
        finally:
            p.unlink(missing_ok=True)

    def test_25_no_cross_lead_contamination(self):
        a = self.rows([self.feature(1)], n=1)
        b = self.rows([self.feature(2)], n=1)
        self.assertEqual(a[0]["overture_id"], "id-1")
        self.assertEqual(b[0]["overture_id"], "id-2")

    @patch("overture_discovery.download_overture_places")
    @patch("overture_discovery.read_candidates")
    @patch("overture_discovery.resolve_region_center")
    @patch("overture_discovery.probe_website")
    def test_26_partial_probe_failure_preserves_non_authorizing_candidates(self, probe, region, rows, download):
        region.return_value = {"lon": 4.4, "lat": 51.9, "authentication": "none"}
        rows.return_value = [
            {"overture_id": "a", "website_hint": "https://a.example", "identity_status": "needs_leads_verification"},
            {"overture_id": "b", "website_hint": "https://b.example", "identity_status": "needs_leads_verification"},
        ]
        probe.side_effect = [
            {"status": "reachable_needs_leads_identity_verification", "final_url": "https://a.example", "http_status": 200, "detail": None},
            {"status": "unreachable", "final_url": None, "http_status": None, "detail": "ConnectionError"},
        ]
        out = discover(region="Rotterdam", bbox=None, radius_km=8, keywords=["bakery"], max_results=2, require_website=True, probe_websites=True)
        self.assertEqual(out["candidate_count"], 2)
        self.assertFalse(out["privacy_and_scope"]["draftqueue_write"])
        self.assertFalse(out["privacy_and_scope"]["email_send"])

    def test_27_retry_path_falls_back_from_woonplaats_to_gemeente(self):
        session = Mock()
        first = Mock(); first.raise_for_status = Mock(); first.json.return_value = {"response": {"docs": []}}
        second = Mock(); second.raise_for_status = Mock(); second.json.return_value = {"response": {"docs": [{"id":"g","weergavenaam":"Rotterdam","type":"gemeente","centroide_ll":"POINT(4.4 51.9)"}]}}
        session.get.side_effect = [first, second]
        r = resolve_region_center("Rotterdam", session=session)
        self.assertEqual(r["resolved_type"], "gemeente")
        self.assertEqual(session.get.call_count, 2)

    def test_28_idempotent_candidate_read(self):
        items = [self.feature(i) for i in range(10)]
        self.assertEqual(self.rows(items, n=10), self.rows(items, n=10))

    def test_29_runtime_branch_cleanup_contract(self):
        text = Path(".github/workflows/overture-discovery.yml").read_text(encoding="utf-8")
        self.assertIn("cleanup-runtime-branch:", text)
        self.assertIn('gh api --method DELETE "repos/$GITHUB_REPOSITORY/git/refs/heads/$RUNTIME_BRANCH"', text)

    def test_30_artifact_retention_is_one_day(self):
        text = Path(".github/workflows/overture-discovery.yml").read_text(encoding="utf-8")
        self.assertIn("retention-days: 1", text)

    def test_all_candidates_omit_contact_fields(self):
        serialized = json.dumps(self.rows([self.feature(1)]))
        self.assertNotIn("must-not-leak@example.test", serialized)
        self.assertNotIn("+31000000000", serialized)
        self.assertNotIn("social.example", serialized)


if __name__ == "__main__":
    unittest.main()
