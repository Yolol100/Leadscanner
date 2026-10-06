"""High-throughput first-party website verification for opening remediation."""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urldefrag, urljoin, urlparse

import aiohttp

from extract_public_contacts import LinkParser, detect_language, normalize_domain
from observation_quality import business_sentences, first_party_prose, natural_opening
from url_safety import is_public_http_url

MAX_BYTES_PER_PAGE = 1_000_000
MAX_PAGES_PER_SITE = 3
MAX_REDIRECTS = 5
DEFAULT_TOTAL_CONCURRENCY = 240
DEFAULT_SHARD_CONCURRENCY = 60
DEFAULT_PER_HOST_CONCURRENCY = 2
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_RETRIES = 2

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _retry_after_seconds(value: str | None) -> float:
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    try:
        return max(0.0, min(5.0, float(raw)))
    except ValueError:
        try:
            when = parsedate_to_datetime(raw)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            return max(0.0, min(5.0, when.timestamp() - time.time()))
        except (TypeError, ValueError, OverflowError):
            return 0.0


def _cache_key(url: str) -> str:
    return urldefrag(str(url or "").strip())[0]


def _cacheable_fetch(value) -> bool:
    try:
        html, final, status, _headers = value
    except (TypeError, ValueError):
        return False
    return bool(html and final and status and 200 <= int(status) < 400)


class AsyncWebsiteAuditor:
    def __init__(self, *, total_concurrency: int | None = None, per_host_concurrency: int | None = None):
        self.total_concurrency = total_concurrency or _env_int(
            "LEADSCANNER_WEBSITE_TOTAL_CONCURRENCY", DEFAULT_TOTAL_CONCURRENCY, 1, 320
        )
        self.per_host_concurrency = per_host_concurrency or _env_int(
            "LEADSCANNER_WEBSITE_PER_HOST", DEFAULT_PER_HOST_CONCURRENCY, 1, 4
        )
        self.timeout_seconds = float(
            os.environ.get("LEADSCANNER_WEBSITE_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
        )
        self._session: aiohttp.ClientSession | None = None
        self._cache: dict[str, tuple[str | None, str | None, int | None, dict[str, str]]] = {}
        self._inflight: dict[str, asyncio.Task] = {}
        self._cache_lock = asyncio.Lock()
        self._host_penalty_until: dict[str, float] = {}

    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(
            total=max(1.0, self.timeout_seconds),
            connect=min(4.0, max(1.0, self.timeout_seconds)),
            sock_read=max(2.0, self.timeout_seconds - 1.0),
        )
        connector = aiohttp.TCPConnector(
            limit=self.total_concurrency,
            limit_per_host=self.per_host_concurrency,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
        )
        self._session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers=_HEADERS,
            raise_for_status=False,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _is_public(self, url: str) -> bool:
        # Re-resolve before every outbound attempt. Do not cache DNS safety
        # decisions: a transient resolver failure must not poison the run and
        # a prior public answer must not weaken redirect/retry SSRF checks.
        return bool(await asyncio.to_thread(is_public_http_url, url))

    async def _respect_host_penalty(self, url: str) -> None:
        host = (urlparse(url).hostname or "").casefold()
        until = self._host_penalty_until.get(host, 0.0)
        delay = until - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)

    def _penalize_host(self, url: str, delay: float) -> None:
        host = (urlparse(url).hostname or "").casefold()
        if host:
            self._host_penalty_until[host] = max(
                self._host_penalty_until.get(host, 0.0),
                time.monotonic() + max(0.0, delay),
            )

    async def _fetch_html_uncached(self, url: str):
        if self._session is None:
            raise RuntimeError("AsyncWebsiteAuditor must be used as an async context manager")
        current_url = str(url or "").strip()
        original_domain = normalize_domain(current_url)
        last_status: int | None = None
        for _ in range(MAX_REDIRECTS + 1):
            for attempt in range(MAX_RETRIES + 1):
                if not await self._is_public(current_url):
                    return None, current_url or None, last_status, {}
                await self._respect_host_penalty(current_url)
                try:
                    async with self._session.get(current_url, allow_redirects=False) as response:
                        status = int(response.status)
                        last_status = status
                        response_url = str(response.url or current_url).strip()
                        headers = {k.casefold(): str(v) for k, v in response.headers.items()}
                        if not await self._is_public(response_url):
                            return None, response_url or current_url, status, headers

                        if status in {429, 500, 502, 503, 504} and attempt < MAX_RETRIES:
                            retry_after = _retry_after_seconds(headers.get("retry-after"))
                            delay = max(retry_after, min(2.0, 0.2 * (2 ** attempt)))
                            self._penalize_host(current_url, delay)
                            response.release()
                            continue

                        if status in {301, 302, 303, 307, 308}:
                            location = headers.get("location", "").strip()
                            if not location:
                                return None, response_url or current_url, status, headers
                            next_url = urljoin(response_url or current_url, location)
                            if not await self._is_public(next_url):
                                return None, next_url, status, headers
                            if original_domain and normalize_domain(next_url) != original_domain:
                                return None, next_url, status, headers
                            current_url = next_url
                            break

                        content_type = headers.get("content-type", "").casefold()
                        is_html = "text/html" in content_type or "application/xhtml+xml" in content_type
                        if not (200 <= status < 400) or not is_html:
                            return None, response_url or current_url, status, headers

                        chunks: list[bytes] = []
                        total = 0
                        async for chunk in response.content.iter_chunked(65536):
                            if not chunk:
                                continue
                            remaining = MAX_BYTES_PER_PAGE - total
                            if remaining <= 0:
                                break
                            chunks.append(bytes(chunk[:remaining]))
                            total += min(len(chunk), remaining)
                            if total >= MAX_BYTES_PER_PAGE:
                                break
                        charset = response.charset or "utf-8"
                        body = b"".join(chunks).decode(charset, errors="replace")
                        return body, response_url or current_url, status, headers
                except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeError):
                    if attempt >= MAX_RETRIES:
                        return None, current_url or None, last_status, {}
                    await asyncio.sleep(min(1.0, 0.15 * (2 ** attempt)))
            else:
                return None, current_url or None, last_status, {}
            continue
        return None, current_url or None, last_status, {}

    async def fetch_cached(self, url: str):
        key = _cache_key(url)
        async with self._cache_lock:
            if key in self._cache:
                return self._cache[key]
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(self._fetch_html_uncached(key))
                self._inflight[key] = task
        try:
            value = await task
        except BaseException:
            async with self._cache_lock:
                if self._inflight.get(key) is task:
                    self._inflight.pop(key, None)
            raise
        async with self._cache_lock:
            if self._inflight.get(key) is task:
                self._inflight.pop(key, None)
            # Cache only proven readable HTML. 4xx/5xx/timeouts/DNS failures
            # are not durable negative evidence and must be retryable.
            if _cacheable_fetch(value):
                self._cache[key] = value
        return value

    async def audit_row(self, row: dict, override: dict | None = None, *, shard_semaphore: asyncio.Semaphore | None = None):
        expected = normalize_domain(row.get("website") or "")
        override = override or {}
        website = str(row.get("website") or "").strip()
        source_url = str(override.get("source_url") or "").strip()
        urls: list[str] = []
        for candidate in ([source_url, website] if source_url else [website]):
            if candidate and candidate not in urls:
                urls.append(candidate)

        pages = []
        errors: list[str] = []
        checked: set[str] = set()
        verified_at = _iso_now()
        while urls and len(pages) < MAX_PAGES_PER_SITE:
            url = urls.pop(0)
            requested_override_source = bool(override and source_url and url == source_url)
            if url in checked:
                continue
            checked.add(url)
            if normalize_domain(url) != expected:
                errors.append("official_domain_mismatch")
                continue
            try:
                if shard_semaphore is None:
                    fetched = await self.fetch_cached(url)
                else:
                    async with shard_semaphore:
                        fetched = await self.fetch_cached(url)
                html, final, status, headers = fetched
                if not html or not final or not status or not 200 <= status < 400:
                    errors.append(f"{url}: HTTP {status or 'unavailable'}; no readable official page")
                    continue
                if normalize_domain(final) != expected:
                    errors.append(f"{url}: redirected off official domain")
                    continue
                lang, _ = detect_language(html, default=row.get("language") or "nl")
                blocks = first_party_prose(html)
                sentences = business_sentences(html)
                page_sha256 = hashlib.sha256(html.encode()).hexdigest()
                retained_blocks = blocks[:100]
                if requested_override_source:
                    quote = str(override.get("evidence_quote") or override.get("observation") or "")
                    retained_blocks += [b for b in blocks if quote and quote in b and b not in retained_blocks]
                pages.append({
                    "url": final,
                    "http_status": status,
                    "language": lang,
                    "sha256": page_sha256,
                    "etag": headers.get("etag"),
                    "last_modified": headers.get("last-modified"),
                    "prose": retained_blocks,
                })

                if requested_override_source:
                    observation = str(override.get("observation") or "")
                    evidence_quote = str(override.get("evidence_quote") or observation)
                    if evidence_quote and any(evidence_quote in block for block in retained_blocks):
                        try:
                            language = override.get("language") or lang
                            if language not in {"nl", "en"}:
                                raise ValueError("unsupported approved prose language")
                            name_fields = {}
                            if override.get("company_name"):
                                name_quote = str(override.get("company_name_quote") or "")
                                if override["company_name"] not in name_quote or not any(
                                    name_quote in block for block in retained_blocks
                                ):
                                    raise ValueError("company-name correction lacks exact first-party prose evidence")
                                name_fields = {
                                    key: override[key]
                                    for key in ("company_name", "old_company_name", "company_name_quote")
                                }
                            return {
                                "status": "ready",
                                "verified_at": verified_at,
                                "proof": {
                                    "observation": observation,
                                    "opening": natural_opening(observation, language),
                                    "evidence_quote": evidence_quote,
                                    "source_url": final,
                                    "language": language,
                                    "page_sha256": page_sha256,
                                    **name_fields,
                                },
                                "pages": pages,
                                "errors": errors,
                            }
                        except ValueError as exc:
                            errors.append(str(exc))

                if not override:
                    for sentence in sentences:
                        if not re.match(r"^(Wij|We|Jullie)\b", sentence):
                            continue
                        try:
                            opening = natural_opening(sentence, lang)
                        except ValueError:
                            continue
                        return {
                            "status": "ready",
                            "verified_at": verified_at,
                            "proof": {
                                "observation": sentence,
                                "opening": opening,
                                "evidence_quote": sentence,
                                "source_url": final,
                                "language": lang,
                                "page_sha256": page_sha256,
                            },
                            "pages": pages,
                            "errors": errors,
                        }

                if len(pages) == 1:
                    parser = LinkParser()
                    try:
                        parser.feed(html)
                    except Exception:
                        pass
                    for href, label in parser.links:
                        link = urljoin(final, href)
                        if (
                            normalize_domain(link) == expected
                            and re.search(
                                r"over.?ons|about|diensten|services|producten|products|assortiment|menu|menukaart",
                                link + " " + unescape(label),
                                re.I,
                            )
                            and link not in checked
                            and link not in urls
                        ):
                            urls.append(link)
                            if len(urls) + len(pages) >= 6:
                                break
            except Exception as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")

        if override:
            errors.append("exact approved business sentence absent from eligible first-party prose")
        return {
            "status": "hold",
            "verified_at": verified_at,
            "reason": "; ".join(errors) if not pages else (
                "No short declarative business fact with an explicit business subject could be verified "
                "in eligible prose on the checked official pages; " + "; ".join(errors)
            ),
            "pages": pages,
            "errors": errors,
        }

    async def audit_many(self, rows, proofs=None, *, shard_concurrency: int | None = None):
        rows = list(rows)
        proofs = [None] * len(rows) if proofs is None else list(proofs)
        if len(rows) != len(proofs):
            raise ValueError("website proof count mismatch")
        limit = shard_concurrency or _env_int(
            "LEADSCANNER_WEBSITE_SHARD_CONCURRENCY", DEFAULT_SHARD_CONCURRENCY, 1, 80
        )
        semaphore = asyncio.Semaphore(min(limit, max(1, len(rows))))
        return await asyncio.gather(*(
            self.audit_row(row, proof, shard_semaphore=semaphore)
            for row, proof in zip(rows, proofs)
        ))


async def _audit_shards_async(shards, proofs_by_shard=None):
    shards = [list(shard) for shard in shards]
    if proofs_by_shard is None:
        proofs_by_shard = [None] * len(shards)
    if len(shards) != len(proofs_by_shard):
        raise ValueError("proof shard count mismatch")
    async with AsyncWebsiteAuditor() as auditor:
        return await asyncio.gather(*(
            auditor.audit_many(shard, proofs)
            for shard, proofs in zip(shards, proofs_by_shard)
        ))


def audit_website_shards(shards, proofs_by_shard=None):
    return asyncio.run(_audit_shards_async(shards, proofs_by_shard))


def audit_websites(rows, proofs=None):
    return audit_website_shards([list(rows)], [proofs])[0]
