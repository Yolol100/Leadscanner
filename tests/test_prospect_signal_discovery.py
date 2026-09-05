import importlib.util
import pathlib
import sys
import unittest

MODULE_PATH = pathlib.Path(__file__).parents[1] / "scripts" / "prospect_signal_discovery.py"
spec = importlib.util.spec_from_file_location("prospect_signal_discovery", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class ProspectSignalDiscoveryTests(unittest.TestCase):
    def test_host_and_signal_id_are_stable(self):
        self.assertEqual(module.canonical_host("https://www.Example.nl/a"), "example.nl")
        self.assertEqual(
            module.stable_signal_id("p1", "hiring", "https://example.nl/jobs"),
            module.stable_signal_id("p1", "hiring", "https://example.nl/jobs"),
        )

    def test_detects_wordpress_woocommerce_and_active_hiring(self):
        html = '<html><a href="/werken-bij">Vacatures</a><script src="/wp-content/plugins/woocommerce/x.js"></script></html>'
        def fetch(url):
            self.assertEqual(url, "https://example.nl/werken-bij")
            return "<h1>Openstaande vacatures</h1><a>Solliciteer</a>"
        signals = module.discover_official_signals("https://example.nl/", html, fetch_text=fetch)
        types = {item.signal_type for item in signals}
        self.assertEqual(types, {"technology_wordpress", "technology_woocommerce", "hiring"})
        hiring = next(item for item in signals if item.signal_type == "hiring")
        self.assertEqual(hiring.strength, 2)
        self.assertEqual(hiring.confidence, "high")

    def test_external_jobs_link_is_not_accepted_as_official_signal(self):
        html = '<a href="https://jobs.example.org/company">Careers</a>'
        signals = module.discover_official_signals("https://example.nl/", html)
        self.assertFalse(any(item.signal_type == "hiring" for item in signals))

    def test_hiring_page_without_fetch_is_weak_signal(self):
        html = '<a href="/careers">Join us</a>'
        signals = module.discover_official_signals("https://example.nl/", html)
        hiring = next(item for item in signals if item.signal_type == "hiring")
        self.assertEqual(hiring.strength, 1)

    def test_no_markers_yields_no_signal(self):
        self.assertEqual(module.discover_official_signals("https://example.nl/", "<p>Hello</p>"), [])


if __name__ == "__main__":
    unittest.main()
