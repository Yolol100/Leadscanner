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

    def test_bulk_defaults_are_bounded(self):
        self.assertEqual(fast.DEFAULT_SHARD_CONCURRENCY, 60)
        self.assertEqual(fast.DEFAULT_TOTAL_CONCURRENCY, 240)
        self.assertEqual(fast.DEFAULT_PER_HOST_CONCURRENCY, 2)


if __name__ == "__main__":
    unittest.main()
