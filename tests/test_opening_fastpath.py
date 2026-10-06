import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import opening_fastpath as fast


class OpeningFastpathTests(unittest.IsolatedAsyncioTestCase):
    async def test_homepage_fact_exits_before_deeper_links(self):
        row = {"website": "https://example.com/", "language": "nl"}
        html = '<main><p>Wij serveren tapas.</p></main><a href="/over-ons">Over ons</a>'
        with patch.object(fast, "business_sentences", return_value=["Wij serveren tapas."]), \
             patch.object(fast, "first_party_prose", return_value=["Wij serveren tapas."]), \
             patch.object(fast, "natural_opening", return_value="Ik zag op jullie website dat jullie tapas serveren."):
            async with fast.AsyncWebsiteAuditor(total_concurrency=10, per_host_concurrency=2) as auditor:
                auditor.fetch_cached = AsyncMock(return_value=(html, row["website"], 200, {"content-type": "text/html"}))
                result = await auditor.audit_row(row)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(auditor.fetch_cached.await_count, 1)
        self.assertIn("page_sha256", result["proof"])
        self.assertTrue(result["verified_at"].endswith("Z"))

    async def test_inflight_url_is_fetched_only_once(self):
        auditor = fast.AsyncWebsiteAuditor(total_concurrency=10, per_host_concurrency=2)
        calls = 0

        async def fake_fetch(url):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return ("<html></html>", url, 200, {"content-type": "text/html"})

        auditor._fetch_html_uncached = fake_fetch
        first, second = await asyncio.gather(
            auditor.fetch_cached("https://example.com/"),
            auditor.fetch_cached("https://example.com/"),
        )
        self.assertEqual(calls, 1)
        self.assertEqual(first, second)

    async def test_transient_exception_does_not_poison_inflight_cache(self):
        auditor = fast.AsyncWebsiteAuditor(total_concurrency=10, per_host_concurrency=2)
        calls = 0

        async def flaky(url):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("transient")
            return ("<html></html>", url, 200, {"content-type": "text/html"})

        auditor._fetch_html_uncached = flaky
        with self.assertRaises(RuntimeError):
            await auditor.fetch_cached("https://example.com/")
        value = await auditor.fetch_cached("https://example.com/")
        self.assertEqual(calls, 2)
        self.assertEqual(value[2], 200)

    async def test_failed_http_result_is_not_negative_cached(self):
        auditor = fast.AsyncWebsiteAuditor(total_concurrency=10, per_host_concurrency=2)
        calls = 0

        async def flaky(url):
            nonlocal calls
            calls += 1
            if calls == 1:
                return (None, url, 503, {"content-type": "text/html"})
            return ("<html></html>", url, 200, {"content-type": "text/html"})

        auditor._fetch_html_uncached = flaky
        self.assertEqual((await auditor.fetch_cached("https://example.com/"))[2], 503)
        self.assertEqual((await auditor.fetch_cached("https://example.com/"))[2], 200)
        self.assertEqual(calls, 2)

    async def test_dns_safety_decision_is_not_cached_between_outbound_checks(self):
        auditor = fast.AsyncWebsiteAuditor(total_concurrency=10, per_host_concurrency=2)
        with patch.object(fast, "is_public_http_url", side_effect=[False, True]) as check:
            self.assertFalse(await auditor._is_public("https://example.com/"))
            self.assertTrue(await auditor._is_public("https://example.com/"))
        self.assertEqual(check.call_count, 2)

    async def test_override_survives_same_domain_redirect(self):
        row = {"website": "https://example.com/", "language": "nl"}
        override = {
            "source_url": "http://example.com/over-ons",
            "observation": "Wij maken keukens op maat.",
            "evidence_quote": "Wij maken keukens op maat.",
            "language": "nl",
        }
        html = "<main><p>Wij maken keukens op maat.</p></main>"
        with patch.object(fast, "first_party_prose", return_value=["Wij maken keukens op maat."]), \
             patch.object(fast, "business_sentences", return_value=["Wij maken keukens op maat."]), \
             patch.object(fast, "natural_opening", return_value="Ik zag op jullie website dat jullie keukens op maat maken."):
            async with fast.AsyncWebsiteAuditor(total_concurrency=10, per_host_concurrency=2) as auditor:
                auditor.fetch_cached = AsyncMock(return_value=(
                    html,
                    "https://example.com/over-ons/",
                    200,
                    {"content-type": "text/html"},
                ))
                result = await auditor.audit_row(row, override)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["proof"]["source_url"], "https://example.com/over-ons/")

    def test_bulk_defaults_are_bounded(self):
        self.assertEqual(fast.DEFAULT_SHARD_CONCURRENCY, 60)
        self.assertEqual(fast.DEFAULT_TOTAL_CONCURRENCY, 240)
        self.assertEqual(fast.DEFAULT_PER_HOST_CONCURRENCY, 2)


if __name__ == "__main__":
    unittest.main()
