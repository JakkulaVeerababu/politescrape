"""Exceptions raised by politescrape."""

from __future__ import annotations


class PoliteScrapeError(Exception):
    """Base class for every error this package raises."""


class RobotsDisallowed(PoliteScrapeError):
    """The site's robots.txt does not allow this URL for our user agent."""

    def __init__(self, url: str, user_agent: str) -> None:
        super().__init__(f"robots.txt does not allow {user_agent!r} to fetch {url}")
        self.url = url
        self.user_agent = user_agent


class FetchError(PoliteScrapeError):
    """A request failed for good: network error, timeout or too many redirects."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"could not fetch {url}: {reason}")
        self.url = url
        self.reason = reason


class ResponseTooLarge(FetchError):
    """The response body is larger than the client's ``max_bytes`` limit."""

    def __init__(self, url: str, limit: int) -> None:
        super().__init__(url, f"the response is larger than {limit:,} bytes")
        self.limit = limit


class HTTPStatusError(PoliteScrapeError):
    """Raised by :meth:`Page.raise_for_status` for 4xx and 5xx responses."""

    def __init__(self, url: str, status: int) -> None:
        super().__init__(f"HTTP {status} for {url}")
        self.url = url
        self.status = status


class SchemaError(PoliteScrapeError, ValueError):
    """An extraction schema is malformed."""
