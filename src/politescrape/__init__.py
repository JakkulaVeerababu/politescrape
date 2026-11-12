"""politescrape: polite, structured web scraping.

Fetch a page and read what is on it::

    import politescrape

    page = politescrape.get("https://books.toscrape.com/")
    page.metadata["title"]      # what the page says about itself
    page.json_ld                # embedded structured data
    page.tables                 # data tables
    page.links                  # absolute, de-duplicated links
    page.markdown               # the main content, ready to read or feed to a model

Every request respects the site's robots.txt, waits between requests, retries
with growing pauses and slows down when the site asks it to. For more than one
page, keep a :class:`Client` open or use :func:`crawl`.
"""

from __future__ import annotations

from typing import Any

from politescrape._version import __version__
from politescrape.client import DEFAULT_USER_AGENT, Client
from politescrape.crawler import Crawler, CrawlStats, crawl
from politescrape.errors import (
    FetchError,
    HTTPStatusError,
    PoliteScrapeError,
    ResponseTooLarge,
    RobotsDisallowed,
    SchemaError,
)
from politescrape.extract import Content, Link, Schema, Table, compile_schema, load_schema
from politescrape.markdown import html_to_markdown
from politescrape.page import Page
from politescrape.response import Response
from politescrape.robots import RobotsTxt

__all__ = [
    "DEFAULT_USER_AGENT",
    "Client",
    "Content",
    "CrawlStats",
    "Crawler",
    "FetchError",
    "HTTPStatusError",
    "Link",
    "Page",
    "PoliteScrapeError",
    "Response",
    "ResponseTooLarge",
    "RobotsDisallowed",
    "RobotsTxt",
    "Schema",
    "SchemaError",
    "Table",
    "__version__",
    "compile_schema",
    "crawl",
    "get",
    "html_to_markdown",
    "load_schema",
]


def get(url: str, **client_options: Any) -> Page:
    """Fetch one page politely and return it ready for extraction.

    This opens a :class:`Client` for a single request. When you fetch several
    pages, create one client and reuse it: it remembers each site's robots.txt
    and paces the requests.

    ``client_options`` are passed to :class:`Client` (``user_agent``,
    ``delay``, ``cache_dir`` and so on).
    """
    with Client(**client_options) as client:
        return client.get(url)
