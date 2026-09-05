import importlib.util
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

spec = importlib.util.spec_from_file_location("prospect_discovery", SCRIPTS / "prospect_discovery.py")
discovery = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = discovery
spec.loader.exec_module(discovery)

runtime_spec = importlib.util.spec_from_file_location("prospect_discovery_runtime", SCRIPTS / "prospect_discovery_runtime.py")
runtime = importlib.util.module_from_spec(runtime_spec)
sys.modules[runtime_spec.name] = runtime
runtime_spec.loader.exec_module(runtime)


class ProspectSourceMeshTests(unittest.TestCase):
    def test_directory_sitemap_is_an_explicit_source_type(self):
        source = discovery.SourceSpec.from_row({
            "source_id": "members-sitemap",
            "source_type": "directory_sitemap",
            "source_url": "https://directory.example/sitemap.xml",
            "max_candidates": "5",
            "approved": "TRUE",
            "enabled": "TRUE",
        })
        self.assertEqual(source.source_type, "directory_sitemap")
        self.assertEqual(source.max_candidates, 5)

    def test_sitemap_urlset_is_parsed_without_external_entity_support(self):
        kind, locations = discovery.parse_sitemap_locations(
            '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            '<url><loc>https://directory.example/member/a</loc></url>'
            '<url><loc>https://directory.example/member/b</loc></url>'
            '</urlset>'
        )
        self.assertEqual(kind, "urlset")
        self.assertEqual(locations, [
            "https://directory.example/member/a",
            "https://directory.example/member/b",
        ])
        with self.assertRaises(discovery.DiscoveryError):
            discovery.parse_sitemap_locations(
                '<!DOCTYPE foo [<!ENTITY x SYSTEM "file:///etc/passwd">]><urlset>&x;</urlset>'
            )

    def test_directory_sitemap_follows_profile_to_official_company_site(self):
        source = discovery.SourceSpec(
            source_id="members-sitemap",
            source_type="directory_sitemap",
            source_url="https://directory.example/sitemap.xml",
            max_candidates=5,
            approved=True,
        )
        pages = {
            "https://directory.example/sitemap.xml": (
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '<url><loc>https://directory.example/member/acme</loc></url>'
                '</urlset>'
            ),
            "https://directory.example/member/acme": '<a href="https://acme.example/diensten">Website</a>',
            "https://acme.example/": '<meta property="og:site_name" content="Acme BV"><p>Webdesign</p>',
        }
        def fetch(url):
            if url in pages:
                return pages[url]
            raise discovery.DiscoveryError(f"missing fixture: {url}")
        result = discovery.discover_source(source, fetch)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].company, "Acme BV")
        self.assertEqual(result[0].website, "https://acme.example/")
        self.assertEqual(result[0].source_type, "directory_sitemap")

    def test_sitemap_index_follows_only_bounded_same_host_children(self):
        source = discovery.SourceSpec(
            source_id="members-index",
            source_type="directory_sitemap",
            source_url="https://directory.example/sitemap-index.xml",
            max_candidates=3,
            approved=True,
        )
        pages = {
            "https://directory.example/sitemap-index.xml": (
                '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '<sitemap><loc>https://directory.example/members-1.xml</loc></sitemap>'
                '<sitemap><loc>https://evil.example/external.xml</loc></sitemap>'
                '</sitemapindex>'
            ),
            "https://directory.example/members-1.xml": (
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '<url><loc>https://directory.example/member/beta</loc></url>'
                '</urlset>'
            ),
            "https://directory.example/member/beta": '<a href="https://beta.example/">Website</a>',
            "https://beta.example/": '<meta property="og:site_name" content="Beta BV">',
        }
        fetched = []
        def fetch(url):
            fetched.append(url)
            if url in pages:
                return pages[url]
            raise discovery.DiscoveryError(f"missing fixture: {url}")
        result = discovery.discover_source(source, fetch)
        self.assertEqual(len(result), 1)
        self.assertNotIn("https://evil.example/external.xml", fetched)
        self.assertEqual(discovery.HARD_MAX_SITEMAP_CHILDREN, 3)

    def test_http_client_contract_allows_bounded_xml_sources(self):
        text = (SCRIPTS / "prospect_discovery.py").read_text(encoding="utf-8")
        self.assertIn('"application/xml"', text)
        self.assertIn('"text/xml"', text)
        self.assertIn("response exceeds byte limit", text)
        self.assertIn("robots.txt disallows fetch", text)

    def test_source_run_row_is_stable_and_sanitized(self):
        source = discovery.SourceSpec(
            source_id="s1",
            source_type="directory_sitemap",
            source_url="https://directory.example/sitemap.xml",
            approved=True,
        )
        row = runtime.source_run_row(
            run_id="run-1",
            run_at="2026-09-05T10:00:00+00:00",
            source=source,
            status="error",
            seen=2,
            new_count=1,
            duplicate_count=1,
            duration_ms=123,
            error="x" * 400,
        )
        record = dict(zip(runtime.SOURCE_RUN_HEADERS, row))
        self.assertEqual(record["source_id"], "s1")
        self.assertEqual(record["source_type"], "directory_sitemap")
        self.assertEqual(record["duration_ms"], 123)
        self.assertEqual(len(record["error"]), 300)

    def test_source_run_history_is_optional_until_bootstrap(self):
        text = (SCRIPTS / "prospect_discovery_runtime.py").read_text(encoding="utf-8")
        self.assertIn('"ProspectSourceRuns": SOURCE_RUN_HEADERS', text)
        self.assertIn('"source_runs_available": "ProspectSourceRuns" in sheet_titles', text)
        self.assertIn('source_runs_persisted = "ProspectSourceRuns" in sheet_titles', text)
        self.assertIn("ProspectSourceRuns", text)

    def test_machine_and_human_contracts_match_source_mesh(self):
        contract = json.loads((ROOT / "toolkit-contract.json").read_text(encoding="utf-8"))
        registry = json.loads((ROOT / "tool-registry.json").read_text(encoding="utf-8"))
        discovery_contract = contract["capabilities"]["prospect_discovery"]
        self.assertIn("directory_sitemap", discovery_contract["source_types"])
        self.assertEqual(discovery_contract["directory_sitemap_child_hard_cap"], 3)
        self.assertIn("ProspectSourceRuns", discovery_contract["outputs"])
        self.assertIn("ProspectSourceRuns", registry["capabilities"]["prospect_discovery"]["writes"])
        self.assertFalse(registry["tools"]["directory_sitemap_adapter"]["automatic_score_effect"])
        integration = (ROOT / "LEADS-INTEGRATION.md").read_text(encoding="utf-8")
        self.assertIn("`directory_sitemap`", integration)
        self.assertIn("`ProspectSourceRuns`", integration)
        self.assertIn("nooit kwalificatie of send permission", integration)


if __name__ == "__main__":
    unittest.main()
