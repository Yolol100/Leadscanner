"""Broken first-party HTTP streams must remain holds, not partial evidence."""
import unittest
from unittest.mock import patch

import requests
from cold_stages import research_candidate, safe_fetch_html, verify_candidate


class StreamResponse:
    def __init__(self, url, chunks=None, failure=None):
        self.url = url
        self.status_code = 200
        self.headers = {"content-type": "text/html; charset=utf-8"}
        self.encoding = "utf-8"
        self.chunks = chunks or []
        self.failure = failure
        self.closed = False

    def iter_content(self, chunk_size=65536, decode_unicode=False):
        for chunk in self.chunks:
            yield chunk
        if self.failure is not None:
            raise self.failure

    def close(self):
        self.closed = True


class StreamSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        return self.responses.pop(0)


class StreamFailureSafetyTests(unittest.TestCase):
    @patch("cold_stages.is_public_http_url", return_value=True)
    def test_request_stream_failures_discard_all_partial_html(self, _safe):
        errors = (
            requests.exceptions.ChunkedEncodingError("truncated private response"),
            requests.exceptions.ContentDecodingError("private page decoding"),
            requests.exceptions.ConnectionError("connection reset after headers"),
            requests.exceptions.ReadTimeout("stream read timeout"),
        )
        for failure in errors:
            with self.subTest(error=type(failure).__name__):
                response = StreamResponse("https://sample.nl/",
                    chunks=[b"<html><body>partial claim"],
                    failure=failure)
                html, url, status = safe_fetch_html(
                    StreamSession([response]), "https://sample.nl/", "sample.nl",
                )
                self.assertIsNone(html)
                self.assertEqual(url, "https://sample.nl/")
                self.assertEqual(status, 200)
                self.assertTrue(response.closed)

    @patch("cold_stages.is_public_http_url", return_value=True)
    def test_failed_stream_keeps_verification_on_hold(self, _safe):
        response = StreamResponse("https://sample.nl/",
            chunks=[b"<h1>Fictief bewijs</h1>"],
            failure=requests.exceptions.ChunkedEncodingError("cut mid-html"))
        session = StreamSession([response])
        result = verify_candidate({
            "name_hint": "Sample", "website_hint": "https://sample.nl/"
        }, session_factory=lambda: session)
        self.assertFalse(result["ready_for_research"])
        self.assertEqual(result["contact_status"], "hold_unreachable_official_site")
        self.assertTrue(response.closed)

    @patch("cold_stages.is_public_http_url", return_value=True)
    def test_broken_subpage_is_counted_and_other_pages_continue(self, _safe):
        broken = StreamResponse("https://sample.nl/broken",
            chunks=[b"<p>Partial fabricated observation</p>"],
            failure=requests.exceptions.ChunkedEncodingError("broken chunk"))
        good = StreamResponse("https://sample.nl/help",
            chunks=[b"<html><body><p>Klanten kunnen online een afspraak plannen via het portaal.</p></body></html>"])
        session = StreamSession([broken, good])
        result = research_candidate({
            "name_hint": "Sample", "ready_for_research": True,
            "official_url": "https://sample.nl/",
            "official_domain": "sample.nl",
            "homepage_text_excerpt": "Sample biedt zakelijke dienstverlening.",
            "research_links": ["https://sample.nl/broken", "https://sample.nl/help"],
            "contact_links": [],
        }, session_factory=lambda: session)
        self.assertEqual(result["research_status"], "ready")
        self.assertEqual(result["research_page_failure_counts"].get("request_unavailable"), 1)
        self.assertEqual(result["research_pages_fetched"], 2)
        self.assertNotIn("https://sample.nl/broken", result["researched_urls"])
        self.assertNotIn("Partial fabricated observation",
                         str(result["evidence_candidates"]))
        self.assertTrue(broken.closed)
        self.assertTrue(good.closed)

    @patch("cold_stages.is_public_http_url", return_value=True)
    def test_unexpected_code_error_does_not_get_marked_success(self, _safe):
        response = StreamResponse("https://sample.nl/",
            failure=ValueError("unexpected parser programming error"))
        with self.assertRaises(ValueError):
            safe_fetch_html(StreamSession([response]),
                            "https://sample.nl/", "sample.nl")
        self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main()
