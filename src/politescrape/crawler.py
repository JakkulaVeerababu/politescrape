"""Crawl a site politely, one page at a time."""

from __future__ import annotations

import logging
import re
from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from politescrape.client import Client
from politescrape.errors import FetchError, RobotsDisallowed
from politescrape.page import Page
from politescrape.sitemaps import parse_sitemap
from politescrape.urls import is_http_url, normalize_url, origin, same_site

log = logging.getLogger("politescrape")

SKIP_EXTENSIONS = frozenset(
    {
        ".7z", ".avi", ".bmp", ".bz2", ".css", ".csv", ".dmg", ".doc", ".docx", ".eot", ".epub",
        ".exe", ".flac", ".gif", ".gz", ".ico", ".iso", ".jpeg", ".jpg", ".js", ".json", ".m4a",
        ".m4v", ".mkv", ".mov", ".mp3", ".mp4", ".mpeg", ".mpg", ".msi", ".odp", ".ods", ".odt",
        ".ogg", ".otf", ".pdf", ".png", ".ppt", ".pptx", ".rar", ".rss", ".svg", ".tar", ".tgz",
        ".tif", ".tiff", ".ttf", ".wav", ".webm", ".webp", ".woff", ".woff2", ".xls", ".xlsx",
        ".xml", ".zip",
    }
)  # fmt: skip
"""Links ending in these extensions are not followed: they are not web pages."""

MAX_SITEMAP_FILES = 50
"""How many sitemap files one crawl reads at most."""


@dataclass
class CrawlStats:
    """What happened during a crawl."""

    pages: int = 0
    """Pages fetched and handed to you."""
    errors: int = 0
    """Requests that failed after every retry."""
    blocked: int = 0
    """Addresses that robots.txt did not allow."""
    skipped: int = 0
    """Links left out by the crawl's own rules (other sites, patterns, file types)."""

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _patterns(value: str | Iterable[str] | None, name: str) -> list[re.Pattern[str]]:
    if value is None:
        return []
    values = [value] if isinstance(value, str) else list(value)
    compiled = []
    for pattern in values:
        try:
            compiled.append(re.compile(pattern))
        except re.error as error:
            raise ValueError(f"{name}: invalid pattern {pattern!r}: {error}") from error
    return compiled


class Crawler:
    """Follow links from one or more start pages, breadth first.

    Iterate over a crawler to get :class:`Page` objects as they are fetched::

        crawler = Crawler("https://example.com/", max_pages=50)
        for page in crawler:
            print(page.url, page.metadata["title"])
        print(crawler.stats)

    Every request goes through a :class:`Client`, so robots.txt, delays and
    retries apply. On top of that the crawler honours ``nofollow`` (both on
    links and as a page-wide robots directive), never fetches an address
    twice, and stays on the start site unless told otherwise.

    Args:
        start_urls: One address or several.
        client: The client to use. When omitted, one is created from
            ``client_options`` and closed when the crawl ends.
        max_pages: Stop after this many pages.
        max_depth: How many links away from a start page to go. ``0`` fetches
            only the start pages (and sitemap pages); ``None`` means no limit.
        stay_on_site: Follow links only to the sites of the start pages.
        allowed_domains: Follow links to these domains and their subdomains
            instead (overrides ``stay_on_site``).
        include: Regular expressions; when given, only links matching at
            least one are followed.
        exclude: Regular expressions; links matching any are not followed.
        sitemaps: Also queue the pages listed in the site's sitemaps.
        follow_nofollow: Follow links even when the page asks crawlers not to.
        skip_extensions: Do not follow links to files with these extensions.
        **client_options: Passed to :class:`Client` when ``client`` is omitted.
    """

    def __init__(
        self,
        start_urls: str | Iterable[str],
        *,
        client: Client | None = None,
        max_pages: int = 100,
        max_depth: int | None = 3,
        stay_on_site: bool = True,
        allowed_domains: Iterable[str] | None = None,
        include: str | Iterable[str] | None = None,
        exclude: str | Iterable[str] | None = None,
        sitemaps: bool = False,
        follow_nofollow: bool = False,
        skip_extensions: Iterable[str] = SKIP_EXTENSIONS,
        **client_options: Any,
    ) -> None:
        if client is not None and client_options:
            raise TypeError("pass either a client or client options, not both")
        urls = [start_urls] if isinstance(start_urls, str) else list(start_urls)
        if not urls:
            raise ValueError("at least one start URL is needed")
        for url in urls:
            if not is_http_url(url):
                raise ValueError(f"not an http(s) URL: {url!r}")
        if max_pages < 1:
            raise ValueError("max_pages must be 1 or more")
        if max_depth is not None and max_depth < 0:
            raise ValueError("max_depth must be 0 or more, or None for no limit")

        self.start_urls = list(dict.fromkeys(normalize_url(url) for url in urls))
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.stay_on_site = stay_on_site
        self.allowed_domains = [domain.lower().strip(".") for domain in allowed_domains or []]
        self.include = _patterns(include, "include")
        self.exclude = _patterns(exclude, "exclude")
        self.sitemaps = sitemaps
        self.follow_nofollow = follow_nofollow
        self.skip_extensions = frozenset(extension.lower() for extension in skip_extensions)
        self.stats = CrawlStats()
        self._client = client
        self._client_options = client_options

    def __iter__(self) -> Iterator[Page]:
        self.stats = CrawlStats()
        if self._client is not None:
            yield from self._run(self._client)
            return
        with Client(**self._client_options) as client:
            yield from self._run(client)

    # ----------------------------------------------------------------- private

    def _run(self, client: Client) -> Iterator[Page]:
        queue: deque[tuple[str, int]] = deque((url, 0) for url in self.start_urls)
        seen = set(self.start_urls)
        queue_limit = max(1000, 20 * self.max_pages)

        if self.sitemaps:
            for url in self._sitemap_pages(client):
                if url not in seen and len(queue) < queue_limit and self._wanted(url):
                    seen.add(url)
                    queue.append((url, 0))

        fetched: set[str] = set()
        while queue and self.stats.pages < self.max_pages:
            url, depth = queue.popleft()
            if url in fetched:
                continue  # an earlier address redirected here
            try:
                page = client.get(url)
            except RobotsDisallowed:
                self.stats.blocked += 1
                log.info("Skipped %s (not allowed by robots.txt)", url)
                continue
            except FetchError as error:
                self.stats.errors += 1
                log.warning("%s", error)
                continue
            try:
                final_url = normalize_url(page.url)
            except ValueError:
                final_url = url
            if final_url in fetched:
                continue  # two addresses redirect to the same page; hand it over once
            fetched.update((url, final_url))
            seen.add(final_url)
            self.stats.pages += 1
            log.info("[%d/%d] %d %s", self.stats.pages, self.max_pages, page.status, page.url)
            yield page

            if not page.ok or not page.is_html:
                continue
            if self.max_depth is not None and depth >= self.max_depth:
                continue
            if not self.follow_nofollow and _asks_not_to_follow(page):
                continue
            for link in page.links:
                if link.nofollow and not self.follow_nofollow:
                    continue
                try:
                    candidate = normalize_url(link.url)
                except ValueError:
                    continue
                if candidate in seen:
                    continue
                seen.add(candidate)
                if not self._wanted(candidate):
                    self.stats.skipped += 1
                elif len(queue) < queue_limit:
                    queue.append((candidate, depth + 1))

    def _wanted(self, url: str) -> bool:
        """Apply the crawl's own rules to a discovered address."""
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if self.allowed_domains:
            if not any(host == d or host.endswith("." + d) for d in self.allowed_domains):
                return False
        elif self.stay_on_site and not any(same_site(url, start) for start in self.start_urls):
            return False
        if PurePosixPath(parts.path).suffix.lower() in self.skip_extensions:
            return False
        if self.include and not any(pattern.search(url) for pattern in self.include):
            return False
        return not any(pattern.search(url) for pattern in self.exclude)

    def _sitemap_pages(self, client: Client) -> Iterator[str]:
        """Yield the pages listed in the sitemaps of the start sites."""
        pending: deque[str] = deque()
        for site in dict.fromkeys(origin(url) for url in self.start_urls):
            declared = client.robots(site + "/").sitemaps
            pending.extend(declared or [site + "/sitemap.xml"])
        read: set[str] = set()
        while pending and len(read) < MAX_SITEMAP_FILES:
            sitemap_url = pending.popleft()
            if sitemap_url in read or not is_http_url(sitemap_url):
                continue
            read.add(sitemap_url)
            try:
                response = client.fetch(sitemap_url)
            except (RobotsDisallowed, FetchError) as error:
                log.info("Could not read sitemap %s: %s", sitemap_url, error)
                continue
            if not response.ok:
                continue
            pages, children = parse_sitemap(response.content)
            pending.extend(children)
            for page_url in pages:
                try:
                    yield normalize_url(page_url)
                except ValueError:
                    continue


def _asks_not_to_follow(page: Page) -> bool:
    """True when a page says ``nofollow`` for all of its links."""
    directives = ",".join(
        [page.metadata.get("robots") or "", page.headers.get("x-robots-tag", "")]
    ).lower()
    tokens = {token.strip() for token in directives.split(",")}
    return "nofollow" in tokens or "none" in tokens


def crawl(start_urls: str | Iterable[str], **options: Any) -> Crawler:
    """Crawl from ``start_urls``; a shortcut for :class:`Crawler`.

    ::

        for page in crawl("https://example.com/", max_pages=20, delay=2):
            print(page.url)
    """
    return Crawler(start_urls, **options)
