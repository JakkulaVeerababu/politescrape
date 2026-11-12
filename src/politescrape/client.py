"""The polite HTTP client at the heart of politescrape."""

from __future__ import annotations

import email.utils
import logging
import math
import os
import random
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from types import TracebackType
from urllib.parse import urljoin

import httpx

from politescrape._version import __version__
from politescrape.cache import CachedResponse, DiskCache
from politescrape.errors import FetchError, ResponseTooLarge, RobotsDisallowed
from politescrape.page import Page
from politescrape.response import Response
from politescrape.robots import MAX_ROBOTS_BYTES, RobotsTxt
from politescrape.urls import is_http_url, origin

log = logging.getLogger("politescrape")

DEFAULT_USER_AGENT = (
    f"politescrape/{__version__} (+https://github.com/JakkulaVeerababu/politescrape)"
)
DEFAULT_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
SLOW_DOWN_STATUSES = frozenset({429, 503})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECTS = 10
MAX_ROBOTS_REDIRECTS = 5

ROBOTS_TTL = 24 * 60 * 60.0
"""How long (seconds) a site's robots.txt is trusted before it is read again."""
ROBOTS_FAILURE_TTL = 10 * 60.0
"""How long to wait before retrying a robots.txt that could not be reached."""
MAX_SITE_DELAY = 60.0
"""Upper limit for the pause between two requests to one site."""
MAX_BACKOFF = 60.0


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Turn a ``Retry-After`` header (seconds or an HTTP date) into seconds to wait."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return max(0.0, (when - current).total_seconds())


class Client:
    """Fetch pages without being a burden on the sites you read.

    Every request made through a client:

    * is checked against the site's robots.txt (RFC 9309) first;
    * waits ``delay`` seconds after the previous request to the same site, or
      longer when the site publishes a ``Crawl-delay``;
    * is retried with growing pauses on network errors and on 429 and 5xx
      responses, waiting as long as a ``Retry-After`` header asks;
    * makes the client slow down for that site after a 429 or 503;
    * carries a ``User-Agent`` that says who is asking.

    Use it as a context manager, or call :meth:`close` when you are done::

        with Client(user_agent="my-project/1.0 (+https://example.org/about)") as client:
            page = client.get("https://example.com/")

    A client is not safe to share between threads.

    Args:
        user_agent: Sent with every request and matched against robots.txt
            groups. Name your project and give a URL or email address so site
            owners can reach you.
        delay: Minimum seconds between two requests to the same site.
        respect_robots: Set to ``False`` only for sites you own or have
            permission to scrape.
        timeout: Seconds to wait for a connection or for more data.
        retries: How many times a failed request is tried again.
        backoff: The first retry waits about this many seconds; each further
            retry waits twice as long.
        max_retry_after: Give up instead of retrying when a site asks to wait
            longer than this many seconds.
        max_bytes: Refuse response bodies larger than this.
        cache_dir: Keep copies of pages in this directory and revalidate them
            with ``ETag``/``Last-Modified`` instead of downloading them again.
        cache_ttl: Reuse a cached page without contacting the site at all when
            it is younger than this many seconds.
        headers: Extra request headers.
        parser: The Beautiful Soup parser used for pages (``"html.parser"`` by
            default; ``"lxml"`` is faster when installed).
        transport: A custom httpx transport, mainly for tests.
        clock: Monotonic clock, replaceable in tests.
        sleep: Sleep function, replaceable in tests.
    """

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        delay: float = 1.0,
        respect_robots: bool = True,
        timeout: float = 20.0,
        retries: int = 3,
        backoff: float = 1.0,
        max_retry_after: float = 120.0,
        max_bytes: int = 10 * 1024 * 1024,
        cache_dir: str | os.PathLike[str] | None = None,
        cache_ttl: float | None = None,
        headers: Mapping[str, str] | None = None,
        parser: str = "html.parser",
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("delay must be a number of seconds, 0 or more")
        if retries < 0:
            raise ValueError("retries must be 0 or more")
        if backoff < 0:
            raise ValueError("backoff must be 0 or more")
        if timeout <= 0:
            raise ValueError("timeout must be greater than 0")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be greater than 0")

        request_headers = httpx.Headers({"User-Agent": user_agent, "Accept": DEFAULT_ACCEPT})
        if headers:
            request_headers.update(headers)
        user_agent = request_headers["User-Agent"].strip()
        if not user_agent:
            raise ValueError("user_agent must not be empty")

        self.user_agent = user_agent
        self.delay = float(delay)
        self.respect_robots = respect_robots
        self.retries = retries
        self.backoff = float(backoff)
        self.max_retry_after = float(max_retry_after)
        self.max_bytes = max_bytes
        self.cache_ttl = cache_ttl
        self.parser = parser

        self._http = httpx.Client(
            headers=request_headers,
            timeout=timeout,
            follow_redirects=False,
            transport=transport,
        )
        self._cache = DiskCache(cache_dir) if cache_dir is not None else None
        self._clock = clock
        self._sleep = sleep
        self._random = random.Random()
        self._robots: dict[str, tuple[RobotsTxt, float]] = {}
        self._last_request: dict[str, float] = {}
        self._slowdown: dict[str, float] = {}

    def __enter__(self) -> Client:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying network connections."""
        self._http.close()

    # ------------------------------------------------------------------ public

    def get(self, url: str) -> Page:
        """Fetch ``url`` and return it as a :class:`Page` ready for extraction.

        Raises:
            RobotsDisallowed: robots.txt does not allow the URL.
            FetchError: the request failed after every retry.
        """
        return Page(self.fetch(url), parser=self.parser)

    def fetch(self, url: str) -> Response:
        """Fetch ``url`` and return the raw :class:`Response`.

        Redirects are followed one hop at a time so that every hop is checked
        against robots.txt and rate limited like any other request. Responses
        with an error status are returned, not raised; check ``response.ok``.
        """
        if not is_http_url(url):
            raise FetchError(url, "only http:// and https:// URLs can be fetched")
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            if self.respect_robots and not self.robots(current).can_fetch(self.user_agent, current):
                raise RobotsDisallowed(current, self.user_agent)
            response = self._fetch_one(current)
            location = response.headers.get("location")
            if response.status in REDIRECT_STATUSES and location:
                target = urljoin(current, location)
                if not is_http_url(target):
                    raise FetchError(url, f"redirected to an unsupported address: {target}")
                log.debug("%s redirects to %s", current, target)
                current = target
                continue
            response.url = url
            response.final_url = current
            return response
        raise FetchError(url, f"gave up after {MAX_REDIRECTS} redirects")

    def robots(self, url: str) -> RobotsTxt:
        """Return the robots.txt rules for the site that serves ``url``.

        The file is fetched once per site and remembered for a day. Following
        RFC 9309, a site without a robots.txt (any 4xx answer) allows
        everything, while a robots.txt that cannot be reached (network error,
        5xx or 429) means nothing may be fetched until it can be read.
        """
        key = origin(url)
        cached = self._robots.get(key)
        now = self._clock()
        if cached is not None and cached[1] > now:
            return cached[0]
        rules, lifetime = self._load_robots(key)
        self._robots[key] = (rules, self._clock() + lifetime)
        return rules

    def allowed(self, url: str) -> bool:
        """True when robots.txt allows this client to fetch ``url``."""
        if not self.respect_robots:
            return True
        return self.robots(url).can_fetch(self.user_agent, url)

    def site_delay(self, url: str) -> float:
        """Seconds this client currently leaves between requests to the site of ``url``."""
        return self._delay_for(origin(url))

    # ----------------------------------------------------------------- private

    def _load_robots(self, site: str) -> tuple[RobotsTxt, float]:
        current = f"{site}/robots.txt"
        try:
            for _ in range(MAX_ROBOTS_REDIRECTS + 1):
                status, headers, content = self._send(
                    current, None, MAX_ROBOTS_BYTES, truncate=True
                )
                location = headers.get("location")
                if status in REDIRECT_STATUSES and location:
                    current = urljoin(current, location)
                    if not is_http_url(current):
                        return RobotsTxt.allow_all(), ROBOTS_TTL
                    continue
                break
            else:
                log.warning("%s/robots.txt redirects too many times; treating it as absent", site)
                return RobotsTxt.allow_all(), ROBOTS_TTL
        except FetchError as error:
            log.warning("Could not read %s/robots.txt (%s); not fetching from it", site, error)
            return RobotsTxt.disallow_all(), ROBOTS_FAILURE_TTL
        if 200 <= status < 300:
            return RobotsTxt.parse(content), ROBOTS_TTL
        if status == 429 or status >= 500:
            log.warning("%s/robots.txt answered HTTP %d; not fetching from it", site, status)
            return RobotsTxt.disallow_all(), ROBOTS_FAILURE_TTL
        return RobotsTxt.allow_all(), ROBOTS_TTL

    def _fetch_one(self, url: str) -> Response:
        """Fetch one URL (no redirects), going through the cache when there is one."""
        cached = self._cache.get(url) if self._cache is not None else None
        if cached is not None and self.cache_ttl is not None and cached.age() < self.cache_ttl:
            return _from_cache(cached)

        conditional: dict[str, str] = {}
        if cached is not None:
            if cached.headers.get("etag"):
                conditional["If-None-Match"] = cached.headers["etag"]
            if cached.headers.get("last-modified"):
                conditional["If-Modified-Since"] = cached.headers["last-modified"]

        status, headers, content = self._send(url, conditional or None, self.max_bytes)

        if status == 304 and cached is not None and self._cache is not None:
            cached.headers.update(
                {name: value for name, value in headers.items() if not name.startswith("content-")}
            )
            cached.stored_at = time.time()
            self._cache.set(cached)
            return _from_cache(cached)

        response = Response(url=url, final_url=url, status=status, headers=headers, content=content)
        cacheable = status == 200 and "no-store" not in headers.get("cache-control", "").lower()
        if self._cache is not None and cacheable:
            self._cache.set(CachedResponse(url, status, dict(headers), content, time.time()))
        return response

    def _send(
        self,
        url: str,
        headers: Mapping[str, str] | None,
        limit: int,
        *,
        truncate: bool = False,
    ) -> tuple[int, dict[str, str], bytes]:
        """Make one request, rate limited and retried. Redirects are not followed."""
        site = origin(url)
        attempt = 0
        while True:
            self._wait_for_turn(site)
            try:
                status, response_headers, content = self._request(url, headers, limit, truncate)
            except (httpx.UnsupportedProtocol, httpx.InvalidURL, httpx.DecodingError) as error:
                raise FetchError(url, _describe(error)) from error
            except httpx.TransportError as error:
                if attempt >= self.retries:
                    raise FetchError(url, _describe(error)) from error
                pause = self._backoff_pause(attempt)
                log.info("%s failed (%s); trying again in %.1fs", url, _describe(error), pause)
                self._sleep(pause)
                attempt += 1
                continue
            finally:
                self._last_request[site] = self._clock()

            if status not in RETRY_STATUSES or attempt >= self.retries:
                return status, response_headers, content

            retry_after = parse_retry_after(response_headers.get("retry-after"))
            if status in SLOW_DOWN_STATUSES:
                self._slow_down(site, retry_after)
            if retry_after is not None and retry_after > self.max_retry_after:
                log.warning(
                    "%s asked to wait %.0fs before retrying; giving up on %s",
                    site,
                    retry_after,
                    url,
                )
                return status, response_headers, content
            pause = retry_after if retry_after is not None else self._backoff_pause(attempt)
            log.info("HTTP %d from %s; trying again in %.1fs", status, url, pause)
            self._sleep(pause)
            attempt += 1

    def _request(
        self,
        url: str,
        headers: Mapping[str, str] | None,
        limit: int,
        truncate: bool,
    ) -> tuple[int, dict[str, str], bytes]:
        with self._http.stream("GET", url, headers=headers) as response:
            response_headers = {name.lower(): value for name, value in response.headers.items()}
            declared = response_headers.get("content-length", "")
            if not truncate and declared.isdigit() and int(declared) > limit:
                raise ResponseTooLarge(url, limit)
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > limit:
                    if not truncate:
                        raise ResponseTooLarge(url, limit)
                    chunks.append(chunk[: len(chunk) - (size - limit)])
                    break
                chunks.append(chunk)
            return response.status_code, response_headers, b"".join(chunks)

    def _wait_for_turn(self, site: str) -> None:
        """Pause until this site may be contacted again.

        The pause is worked out here, not when the previous request ended, so
        it uses what has been learned since: a ``Crawl-delay`` read from
        robots.txt, or a request by the site to slow down.
        """
        last = self._last_request.get(site)
        if last is None:
            return
        wait = last + self._delay_for(site) - self._clock()
        if wait > 0:
            log.debug("Waiting %.2fs before the next request to %s", wait, site)
            self._sleep(wait)

    def _delay_for(self, site: str) -> float:
        delay = self.delay
        cached = self._robots.get(site)
        if cached is not None:
            crawl_delay = cached[0].crawl_delay(self.user_agent)
            if crawl_delay is not None:
                delay = max(delay, min(crawl_delay, MAX_SITE_DELAY))
        return max(delay, self._slowdown.get(site, 0.0))

    def _slow_down(self, site: str, retry_after: float | None) -> None:
        """Double the pause for a site that answered 429 or 503."""
        current = self._delay_for(site)
        slower = min(MAX_SITE_DELAY, max(current * 2, 1.0, retry_after or 0.0))
        self._slowdown[site] = slower
        log.info("%s asked us to slow down; now waiting %.1fs between requests", site, slower)

    def _backoff_pause(self, attempt: int) -> float:
        if self.backoff == 0:
            return 0.0
        base = min(MAX_BACKOFF, self.backoff * float(2**attempt))
        return float(base + self._random.uniform(0, self.backoff))


def _from_cache(cached: CachedResponse) -> Response:
    return Response(
        url=cached.url,
        final_url=cached.url,
        status=cached.status,
        headers=dict(cached.headers),
        content=cached.content,
        from_cache=True,
        fetched_at=datetime.fromtimestamp(cached.stored_at, tz=timezone.utc),
    )


def _describe(error: Exception) -> str:
    return str(error) or type(error).__name__
