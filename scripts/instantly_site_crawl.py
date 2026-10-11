"""Polite, bounded, same-domain public-page fetching for evidence-only audits.

One Requests session per prospect, at most one in-flight request per prospect.
Many independent prospects can run concurrently; a site is not flooded with
simultaneous page requests. No credentialed, login, cart, or checkout browsing.
Robots.txt is read with same-domain redirect checks, never urllib's unchecked
robotparser.read(). Unknown/unreachable robots policy fails closed.
"""
from __future__ import annotations

import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from dedupe_preflight import normalize_domain
from url_safety import is_public_http_url

USER_AGENT = "Leadscanner/2.1 (+https://andrewbaeten.nl)"
ROBOTS_AGENT = "Leadscanner"
MAX_SITE_HTTP_REQUESTS = 40
MAX_ROBOTS_BYTES = 128_000
MAX_ROBOTS_REDIRECTS = 4
ROBOTS_TIMEOUT_SECONDS = 5
MIN_HOST_INTERVAL_SECONDS = 0.25
MAX_ACCEPTED_CRAWL_DELAY_SECONDS = 8


class PoliteSiteSession:
    """Wrap one isolated requests.Session; reject disallowed/excessive reads."""

    def __init__(self, session, expected_domain: str, *, clock=time.monotonic, sleeper=time.sleep):
        self.session = session
        self.expected_domain = expected_domain
        self.clock = clock
        self.sleeper = sleeper
        self.policy_cache: dict[str, tuple[RobotFileParser | None, float, bool]] = {}
        self.last_request_at: dict[str, float] = {}
        self.html_calls = 0
        self.policy_hold = False

    def _robots_policy(self, origin: str) -> tuple[RobotFileParser | None, float, bool]:
        cached = self.policy_cache.get(origin)
        if cached is not None:
            return cached
        current = origin + "/robots.txt"
        parsed_policy = None
        delay = MIN_HOST_INTERVAL_SECONDS
        allowed = False
        for _ in range(MAX_ROBOTS_REDIRECTS + 1):
            if not is_public_http_url(current) or normalize_domain(current) != self.expected_domain:
                break
            try:
                response = self.session.get(
                    current, allow_redirects=False, timeout=ROBOTS_TIMEOUT_SECONDS,
                    stream=True,
                    headers={"User-Agent": USER_AGENT, "Accept": "text/plain"},
                )
            except requests.RequestException:
                break
            try:
                status = int(response.status_code)
                if status in {301, 302, 303, 307, 308}:
                    location = str((response.headers or {}).get("location") or "").strip()
                    if not location:
                        break
                    current = urljoin(current, location)
                    continue
                # Unavailable robots.txt is permissive per RFC 9309; an
                # overwhelmed, blocked or unreachable origin is not.
                if status in {401, 403, 429} or status >= 500:
                    break
                if 400 <= status < 500:
                    allowed = True
                    break
                if status != 200:
                    break
                data = bytearray()
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        if len(data) + len(chunk) > MAX_ROBOTS_BYTES:
                            break
                        data.extend(chunk)
                else:
                    parsed_policy = RobotFileParser()
                    parsed_policy.parse(bytes(data).decode("utf-8-sig", errors="replace").splitlines())
                    wait = parsed_policy.crawl_delay(ROBOTS_AGENT)
                    rate = parsed_policy.request_rate(ROBOTS_AGENT)
                    if rate is not None and rate.requests:
                        wait = max(wait or 0, rate.seconds / rate.requests)
                    delay = max(MIN_HOST_INTERVAL_SECONDS, float(wait or 0))
                    allowed = delay <= MAX_ACCEPTED_CRAWL_DELAY_SECONDS
                    break
                break
            finally:
                response.close()
        result = (parsed_policy, delay, allowed)
        self.policy_cache[origin] = result
        return result

    def get(self, url: str, **kwargs):
        if not is_public_http_url(url) or normalize_domain(url) != self.expected_domain:
            raise requests.RequestException("site_crawl_outside_verified_domain")
        if self.html_calls >= MAX_SITE_HTTP_REQUESTS:
            raise requests.RequestException("site_crawl_page_budget_exceeded")
        parsed = urlparse(url)
        origin = parsed.scheme + "://" + parsed.netloc
        policy, interval, available = self._robots_policy(origin)
        if not available or (policy is not None and not policy.can_fetch(ROBOTS_AGENT, url)):
            self.policy_hold = True
            raise requests.RequestException("site_crawl_robots_policy_hold")
        previous = self.last_request_at.get(origin)
        if previous is not None:
            wait = interval - (self.clock() - previous)
            if wait > 0:
                self.sleeper(wait)
        self.last_request_at[origin] = self.clock()
        self.html_calls += 1
        return self.session.get(url, **kwargs)
