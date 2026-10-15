"""Network-free regression QA for fast and conservative refill."""
import time
import unittest
from concurrent.futures import ThreadPoolExecutor as RealThreadPool
from unittest.mock import Mock, patch
from pathlib import Path

from verified_fill import fill_verified, MAX_SITE_CHECKS
from verify_official_lead import verify_official_site
from test_verified_fill_100 import hint, approved, FakeResponse


class FastRefillTests(unittest.TestCase):
    def test_one_worker_pool_and_recovers_from_one_bad_website(self):
        calls = []
        pools = []
        def discoverer(**args):
            calls.append(args["region"])
            start = 0 if len(calls) == 1 else 60
            return {"candidates": [hint(i) for i in range(start, start + 60)]}
        def verify(row):
            if row["overture_id"] == "test-1":
                raise ValueError("broken public site")
            return approved(row)
        def make_pool(*args, **kwargs):
            pools.append(1)
            return RealThreadPool(*args, **kwargs)
        with patch("verified_fill.ThreadPoolExecutor", side_effect=make_pool):
            result = fill_verified("Nederland", ["vakbedrijven"], 25,
                                   discoverer=discoverer, verifier=verify,
                                   load_registry=lambda: [])
        self.assertEqual(len(pools), 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["counts"]["approved"], 100)
        self.assertGreaterEqual(result["counts"]["sites_checked"], 101)
        self.assertLess(result["counts"]["sites_checked"], 125)
        self.assertEqual(result["emails_sent"], 0)

    def test_fast_final_batch_avoids_unused_website_requests(self):
        # First 99 pass: only 2 more should be checked, not a whole batch of 24.
        count = []
        def inspect(row):
            count.append(row)
            return approved(row)
        result = fill_verified("Delft", ["vakbedrijven"], 8,
                 discoverer=lambda **k: {"candidates": [hint(i) for i in range(150)]},
                 verifier=inspect, load_registry=lambda: [])
        self.assertTrue(result["complete"])
        self.assertGreaterEqual(result["counts"]["sites_checked"], 100)
        self.assertLess(result["counts"]["sites_checked"], 110)
        self.assertEqual(len(count), result["counts"]["sites_checked"])

    def test_generic_industry_and_city_words_do_not_prove_identity(self):
        row = hint(2)
        row["name_hint"] = "Schildersbedrijf Rotterdam"
        row["category_hint"] = "painter"
        html = ('<h1>Schildersbedrijf in Rotterdam</h1>'
                '<p>Wij zijn gespecialiseerd in schilderwerk.</p>'
                '<a href="mailto:info@fictief-2.nl">info@fictief-2.nl</a>')
        conn = Mock()
        conn.get.side_effect = lambda url, **kwargs: (
            FakeResponse(status=404) if url.endswith("robots.txt") else FakeResponse(html))
        with patch("verify_official_lead.is_public_http_url", return_value=True):
            self.assertIsNone(verify_official_site(row, session=conn))

    def test_hundreds_of_contact_links_do_not_resolve_dns_individually(self):
        row = hint(3)
        row["name_hint"] = "Schildersbedrijf Amstel"
        row["category_hint"] = "painter"
        html = ('<h1>Schildersbedrijf Amstel</h1><p>Schilderwerken Amstel</p>'
                + ''.join('<a href="/contact-%d/">Contact</a>' % i for i in range(450)))
        conn = Mock()
        conn.get.side_effect = lambda url, **kwargs: (
            FakeResponse(status=404) if url.endswith("robots.txt")
            else FakeResponse('<a href="mailto:info@fictief-3.nl">Mail</a>')
            if "contact-" in url else FakeResponse(html))
        with patch("verify_official_lead.is_public_http_url", return_value=True) as check:
            got = verify_official_site(row, session=conn)
        self.assertIsNotNone(got)
        self.assertEqual(got["email"], "info@fictief-3.nl")
        # One public-IP/DNS check for each actual request, none for the 450 links.
        self.assertLessEqual(check.call_count, 8)
        self.assertLessEqual(conn.get.call_count, 3)

    def test_manual_dispatch_skips_duplicate_test_install_but_keeps_ci_guard(self):
        doc = (Path(__file__).resolve().parents[1] /
               ".github/workflows/fresh-leads.yml").read_text()
        self.assertIn("if: github.event_name != 'workflow_dispatch'", doc)
        self.assertEqual(doc.count("needs.test.result == 'skipped'"), 2)
        self.assertEqual(doc.count("always() && !cancelled()"), 2)
        self.assertEqual(doc.count("python3 -m compileall -q scripts"), 3)
        self.assertIn("github.event_name == 'push'", doc)
        self.assertIn("pull_request:", doc)

    def test_parallel_simulation_reports_timing_without_external_requests(self):
        def network_latency(_row):
            time.sleep(0.012)
            return approved(_row)
        result = fill_verified("Delft", ["vakbedrijven"], 8,
                    discoverer=lambda **k: {"candidates": [hint(i) for i in range(100)]},
                    verifier=network_latency, load_registry=lambda: [])
        self.assertEqual(result["counts"]["approved"], 100)
        self.assertLessEqual(result["counts"]["sites_checked"], MAX_SITE_CHECKS)
        self.assertGreaterEqual(result["timings"]["verification_s"], 0)
        print("REFILL100_SPEED_SIM=green pool=1 verified=100 parallel_workers=6 sent=0")


if __name__ == "__main__":
    unittest.main()
