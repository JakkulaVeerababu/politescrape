"""Shared test helpers.

Tests never touch the network. A :class:`FakeSite` answers every request and
a :class:`FakeClock` stands in for time, so the suite is fast and can check
exactly how long the client decided to wait.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from politescrape import Client

SITE = "https://example.test"

Handler = Callable[[httpx.Request], httpx.Response]


class FakeClock:
    """A clock that only moves when something sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += max(seconds, 0.0)


class FakeSite:
    """A website made of canned responses, with a log of the requests it received."""

    def __init__(self) -> None:
        self._routes: dict[str, list[Handler | Exception]] = {}
        self.requests: list[httpx.Request] = []

    @staticmethod
    def _key(url: str) -> str:
        return str(httpx.URL(url if "://" in url else SITE + url))

    def add(
        self,
        url: str,
        body: str | bytes = "",
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        content_type: str = "text/html; charset=utf-8",
    ) -> None:
        """Queue a response for ``url`` (a path on ``SITE``, or a full address).

        Responses are served in the order they were added; the last one keeps
        being served, so a single ``add`` describes a page that never changes.
        """
        content = body.encode("utf-8") if isinstance(body, str) else body
        all_headers = {"content-type": content_type, **(headers or {})}

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, headers=all_headers, content=content)

        self.add_handler(url, respond)

    def add_handler(self, url: str, handler: Handler) -> None:
        """Queue a function that builds the response from the request."""
        self._routes.setdefault(self._key(url), []).append(handler)

    def fail(self, url: str, error: Exception) -> None:
        """Queue a network failure for ``url``."""
        self._routes.setdefault(self._key(url), []).append(error)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        queue = self._routes.get(str(request.url))
        if not queue:
            return httpx.Response(404, text="not found")
        step = queue[0] if len(queue) == 1 else queue.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(request)

    def hits(self, path: str) -> int:
        """How many requests were made for ``path`` (path and query)."""
        return sum(1 for request in self.requests if request.url.raw_path.decode() == path)

    @property
    def paths(self) -> list[str]:
        return [request.url.raw_path.decode() for request in self.requests]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def site() -> FakeSite:
    return FakeSite()


@pytest.fixture
def make_client(site: FakeSite, clock: FakeClock) -> Iterator[Callable[..., Client]]:
    """Build clients wired to the fake site and clock. No delays unless a test asks."""
    clients: list[Client] = []

    def factory(**options: Any) -> Client:
        options.setdefault("delay", 0)
        options.setdefault("backoff", 0)
        client = Client(
            transport=httpx.MockTransport(site.handle),
            clock=clock.time,
            sleep=clock.sleep,
            **options,
        )
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.close()
