"""The polite client: robots.txt, pacing, retries, redirects, size limits and caching."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest

from politescrape import Client, FetchError, ResponseTooLarge, RobotsDisallowed
from politescrape.client import DEFAULT_USER_AGENT, MAX_SITE_DELAY, parse_retry_after
from politescrape.response import decode_body

from .conftest import SITE, FakeClock, FakeSite

MakeClient = Callable[..., Client]


# ------------------------------------------------------------------ the basics


def test_get_returns_a_page_and_identifies_itself(site: FakeSite, make_client: MakeClient) -> None:
    site.add("/", "<title>Hello</title>")
    page = make_client().get(SITE + "/")

    assert page.ok
    assert page.metadata["title"] == "Hello"
    assert site.paths == ["/robots.txt", "/"]
    assert all(request.headers["user-agent"] == DEFAULT_USER_AGENT for request in site.requests)


def test_error_statuses_are_returned_not_raised(site: FakeSite, make_client: MakeClient) -> None:
    page = make_client().get(SITE + "/missing")
    assert page.status == 404
    assert not page.ok


@pytest.mark.parametrize("url", ["ftp://example.test/file", "/relative", "mailto:a@example.test"])
def test_only_web_addresses_can_be_fetched(url: str, make_client: MakeClient) -> None:
    with pytest.raises(FetchError, match="http"):
        make_client().fetch(url)


def test_user_agent_can_be_set_through_headers(site: FakeSite, make_client: MakeClient) -> None:
    client = make_client(headers={"user-agent": "research-bot/2.0", "Accept-Language": "en"})
    client.fetch(SITE + "/")
    assert client.user_agent == "research-bot/2.0"
    assert site.requests[-1].headers["user-agent"] == "research-bot/2.0"
    assert site.requests[-1].headers["accept-language"] == "en"


@pytest.mark.parametrize(
    "options",
    [
        {"delay": -1},
        {"delay": float("nan")},
        {"retries": -1},
        {"backoff": -1},
        {"timeout": 0},
        {"max_bytes": 0},
        {"user_agent": "   "},
    ],
)
def test_invalid_options_are_rejected(options: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="must"):
        Client(**options)  # type: ignore[arg-type]


# ------------------------------------------------------------------ robots.txt


def test_disallowed_pages_are_never_requested(site: FakeSite, make_client: MakeClient) -> None:
    site.add("/robots.txt", "User-agent: *\nDisallow: /private/\n", content_type="text/plain")
    client = make_client()

    with pytest.raises(RobotsDisallowed) as raised:
        client.get(SITE + "/private/data")

    assert raised.value.url == SITE + "/private/data"
    assert site.paths == ["/robots.txt"]
    assert not client.allowed(SITE + "/private/data")
    assert client.allowed(SITE + "/public")


def test_a_site_without_robots_txt_allows_everything(
    site: FakeSite, make_client: MakeClient
) -> None:
    site.add("/robots.txt", status=404)
    assert make_client().get(SITE + "/anything").status == 404  # reached the page itself
    assert site.hits("/anything") == 1


@pytest.mark.parametrize("status", [500, 503, 429])
def test_unreachable_robots_txt_blocks_the_site(
    status: int, site: FakeSite, make_client: MakeClient
) -> None:
    site.add("/robots.txt", status=status)
    site.add("/", "<title>Home</title>")
    with pytest.raises(RobotsDisallowed):
        make_client(retries=1).get(SITE + "/")
    assert site.hits("/") == 0


def test_robots_txt_network_failure_blocks_the_site(
    site: FakeSite, make_client: MakeClient
) -> None:
    site.fail("/robots.txt", httpx.ConnectError("connection refused"))
    with pytest.raises(RobotsDisallowed):
        make_client(retries=0).get(SITE + "/")


def test_robots_txt_is_read_once_per_site(site: FakeSite, make_client: MakeClient) -> None:
    client = make_client()
    for path in ("/a", "/b", "/c"):
        client.fetch(SITE + path)
    client.fetch("https://other.test/a")
    assert site.hits("/robots.txt") == 2  # once for each of the two sites


def test_robots_txt_is_read_again_after_a_day(
    site: FakeSite, clock: FakeClock, make_client: MakeClient
) -> None:
    client = make_client()
    client.fetch(SITE + "/a")
    clock.now += 25 * 60 * 60
    client.fetch(SITE + "/a")
    assert site.hits("/robots.txt") == 2


def test_robots_txt_redirects_are_followed(site: FakeSite, make_client: MakeClient) -> None:
    site.add("/robots.txt", status=301, headers={"location": "/real-robots.txt"})
    site.add("/real-robots.txt", "User-agent: *\nDisallow: /x\n", content_type="text/plain")
    assert not make_client().allowed(SITE + "/x")


def test_robots_checks_can_be_turned_off(site: FakeSite, make_client: MakeClient) -> None:
    site.add("/robots.txt", "User-agent: *\nDisallow: /\n", content_type="text/plain")
    site.add("/", "<title>Mine</title>")
    client = make_client(respect_robots=False)
    assert client.get(SITE + "/").metadata["title"] == "Mine"
    assert client.allowed(SITE + "/")
    assert site.paths == ["/"]


# ---------------------------------------------------------------------- pacing


def test_waits_between_requests_to_the_same_site(
    site: FakeSite, clock: FakeClock, make_client: MakeClient
) -> None:
    client = make_client(delay=2)
    client.fetch(SITE + "/a")  # robots.txt, pause, page
    client.fetch(SITE + "/b")  # pause, page
    assert clock.sleeps == [2, 2]


def test_does_not_wait_longer_than_needed(
    site: FakeSite, clock: FakeClock, make_client: MakeClient
) -> None:
    client = make_client(delay=2)
    client.fetch(SITE + "/a")
    clock.now += 1.5  # the caller spent time on something else
    client.fetch(SITE + "/b")
    assert clock.sleeps[-1] == pytest.approx(0.5)
    clock.now += 10
    client.fetch(SITE + "/c")
    assert len(clock.sleeps) == 2  # no pause was needed


def test_different_sites_do_not_wait_for_each_other(
    site: FakeSite, clock: FakeClock, make_client: MakeClient
) -> None:
    client = make_client(delay=5, respect_robots=False)
    client.fetch(SITE + "/a")
    client.fetch("https://other.test/a")
    assert clock.sleeps == []


def test_crawl_delay_from_robots_txt_is_honoured(
    site: FakeSite, clock: FakeClock, make_client: MakeClient
) -> None:
    site.add("/robots.txt", "User-agent: *\nCrawl-delay: 7\n", content_type="text/plain")
    client = make_client(delay=1)
    client.fetch(SITE + "/a")
    client.fetch(SITE + "/b")
    assert clock.sleeps == [7, 7]
    assert client.site_delay(SITE + "/") == 7


def test_absurd_crawl_delays_are_capped(site: FakeSite, make_client: MakeClient) -> None:
    site.add("/robots.txt", "User-agent: *\nCrawl-delay: 86400\n", content_type="text/plain")
    client = make_client()
    client.fetch(SITE + "/a")
    assert client.site_delay(SITE + "/") == MAX_SITE_DELAY


# --------------------------------------------------------------------- retries


def test_retries_server_errors_until_success(site: FakeSite, make_client: MakeClient) -> None:
    site.add("/flaky", status=503)
    site.add("/flaky", status=502)
    site.add("/flaky", "<title>Finally</title>")
    page = make_client().get(SITE + "/flaky")
    assert page.metadata["title"] == "Finally"
    assert site.hits("/flaky") == 3


def test_gives_up_after_the_configured_retries(site: FakeSite, make_client: MakeClient) -> None:
    site.add("/down", status=500)
    response = make_client(retries=2).fetch(SITE + "/down")
    assert response.status == 500
    assert site.hits("/down") == 3  # the first try and two retries


def test_client_errors_are_not_retried(site: FakeSite, make_client: MakeClient) -> None:
    site.add("/gone", status=410)
    assert make_client().fetch(SITE + "/gone").status == 410
    assert site.hits("/gone") == 1


def test_backoff_grows_with_each_retry(
    site: FakeSite, clock: FakeClock, make_client: MakeClient
) -> None:
    site.add("/down", status=500)
    make_client(retries=3, backoff=1.0, respect_robots=False).fetch(SITE + "/down")
    first, second, third = clock.sleeps
    assert 1 <= first <= 2
    assert 2 <= second <= 3
    assert 4 <= third <= 5


def test_retry_after_is_honoured_and_slows_the_client_down(
    site: FakeSite, clock: FakeClock, make_client: MakeClient
) -> None:
    site.add("/busy", status=429, headers={"retry-after": "7"})
    site.add("/busy", "<title>Now</title>")
    client = make_client(delay=1, respect_robots=False)

    assert client.get(SITE + "/busy").ok
    assert clock.sleeps[0] == 7
    # The site said "too many requests", so later requests are spaced further apart.
    assert client.site_delay(SITE + "/") == 7


def test_slows_down_after_503_without_retry_after(site: FakeSite, make_client: MakeClient) -> None:
    site.add("/busy", status=503)
    site.add("/busy", "ok")
    client = make_client(delay=3, respect_robots=False)
    client.fetch(SITE + "/busy")
    assert client.site_delay(SITE + "/") == 6


def test_gives_up_when_asked_to_wait_too_long(
    site: FakeSite, clock: FakeClock, make_client: MakeClient
) -> None:
    site.add("/busy", status=503, headers={"retry-after": "3600"})
    response = make_client(max_retry_after=120, respect_robots=False).fetch(SITE + "/busy")
    assert response.status == 503
    assert site.hits("/busy") == 1
    assert clock.sleeps == []


def test_network_errors_are_retried(site: FakeSite, make_client: MakeClient) -> None:
    site.fail("/page", httpx.ReadTimeout("timed out"))
    site.add("/page", "<title>Recovered</title>")
    assert make_client().get(SITE + "/page").metadata["title"] == "Recovered"


def test_network_errors_become_fetch_errors(site: FakeSite, make_client: MakeClient) -> None:
    site.fail("/page", httpx.ConnectError("connection refused"))
    with pytest.raises(FetchError, match="connection refused") as raised:
        make_client(retries=2, respect_robots=False).fetch(SITE + "/page")
    assert raised.value.url == SITE + "/page"
    assert site.hits("/page") == 3


def test_parse_retry_after() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    later = format_datetime(now + timedelta(seconds=90), usegmt=True)
    earlier = format_datetime(now - timedelta(seconds=90), usegmt=True)
    assert parse_retry_after("120") == 120
    assert parse_retry_after(later, now=now) == 90
    assert parse_retry_after(earlier, now=now) == 0
    assert parse_retry_after(None) is None
    assert parse_retry_after("  ") is None
    assert parse_retry_after("soon") is None


# ------------------------------------------------------------------- redirects


def test_redirects_are_followed(site: FakeSite, make_client: MakeClient) -> None:
    site.add("/old", status=301, headers={"location": "/new"})
    site.add("/new", "<title>New home</title>")
    page = make_client().get(SITE + "/old")
    assert page.url == SITE + "/new"
    assert page.requested_url == SITE + "/old"
    assert page.metadata["title"] == "New home"


def test_a_redirect_to_a_disallowed_address_is_refused(
    site: FakeSite, make_client: MakeClient
) -> None:
    site.add("/robots.txt", "User-agent: *\nDisallow: /private/\n", content_type="text/plain")
    site.add("/go", status=302, headers={"location": "/private/target"})
    with pytest.raises(RobotsDisallowed):
        make_client().get(SITE + "/go")
    assert site.hits("/private/target") == 0


def test_a_redirect_to_another_site_checks_that_sites_robots_txt(
    site: FakeSite, make_client: MakeClient
) -> None:
    site.add("/go", status=302, headers={"location": "https://other.test/landing"})
    site.add(
        "https://other.test/robots.txt", "User-agent: *\nDisallow: /\n", content_type="text/plain"
    )
    with pytest.raises(RobotsDisallowed):
        make_client().get(SITE + "/go")


def test_redirect_loops_end_in_an_error(site: FakeSite, make_client: MakeClient) -> None:
    site.add("/loop", status=302, headers={"location": "/loop"})
    with pytest.raises(FetchError, match="redirects"):
        make_client().get(SITE + "/loop")


def test_redirects_to_other_schemes_are_refused(site: FakeSite, make_client: MakeClient) -> None:
    site.add("/go", status=302, headers={"location": "ftp://example.test/file"})
    with pytest.raises(FetchError, match="unsupported"):
        make_client().get(SITE + "/go")


# ------------------------------------------------------------------ size limit


def test_large_responses_are_refused_by_their_declared_size(
    site: FakeSite, make_client: MakeClient
) -> None:
    site.add("/big", b"x" * 5000)
    with pytest.raises(ResponseTooLarge) as raised:
        make_client(max_bytes=1000, respect_robots=False).fetch(SITE + "/big")
    assert raised.value.limit == 1000


def test_large_responses_are_cut_off_while_streaming(
    site: FakeSite, make_client: MakeClient
) -> None:
    def endless(request: httpx.Request) -> httpx.Response:
        # No Content-Length, so the size is only known while reading.
        return httpx.Response(200, content=(b"x" * 400 for _ in range(100)))

    site.add_handler("/stream", endless)
    with pytest.raises(ResponseTooLarge):
        make_client(max_bytes=1000, respect_robots=False).fetch(SITE + "/stream")


def test_an_oversized_robots_txt_is_read_up_to_the_limit(
    site: FakeSite, make_client: MakeClient
) -> None:
    rules = "User-agent: *\nDisallow: /x\n" + "# padding\n" * 100_000
    site.add("/robots.txt", rules, content_type="text/plain")
    assert not make_client().allowed(SITE + "/x")


# ---------------------------------------------------------------------- caching


def test_cache_revalidates_with_etag(
    site: FakeSite, make_client: MakeClient, tmp_path: Path
) -> None:
    def page(request: httpx.Request) -> httpx.Response:
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304, headers={"etag": '"v1"'})
        return httpx.Response(
            200,
            headers={"etag": '"v1"', "content-type": "text/html"},
            content=b"<title>Cached</title>",
        )

    site.add_handler("/page", page)
    client = make_client(cache_dir=tmp_path, respect_robots=False)

    first = client.get(SITE + "/page")
    second = client.get(SITE + "/page")

    assert not first.from_cache
    assert second.from_cache
    assert second.status == 200
    assert second.metadata["title"] == "Cached"
    assert site.requests[-1].headers["if-none-match"] == '"v1"'


def test_cache_revalidates_with_last_modified(
    site: FakeSite, make_client: MakeClient, tmp_path: Path
) -> None:
    stamp = "Wed, 01 Jan 2025 00:00:00 GMT"
    site.add("/page", "<title>Dated</title>", headers={"last-modified": stamp})
    site.add("/page", status=304)
    client = make_client(cache_dir=tmp_path, respect_robots=False)
    client.get(SITE + "/page")
    assert client.get(SITE + "/page").from_cache
    assert site.requests[-1].headers["if-modified-since"] == stamp


def test_cache_is_replaced_when_the_page_changes(
    site: FakeSite, make_client: MakeClient, tmp_path: Path
) -> None:
    site.add("/page", "<title>One</title>", headers={"etag": '"1"'})
    site.add("/page", "<title>Two</title>", headers={"etag": '"2"'})
    client = make_client(cache_dir=tmp_path, respect_robots=False)
    assert client.get(SITE + "/page").metadata["title"] == "One"
    changed = client.get(SITE + "/page")
    assert changed.metadata["title"] == "Two"
    assert not changed.from_cache


def test_fresh_cache_entries_skip_the_network(
    site: FakeSite, make_client: MakeClient, tmp_path: Path
) -> None:
    site.add("/page", "<title>Kept</title>")
    client = make_client(cache_dir=tmp_path, cache_ttl=3600, respect_robots=False)
    client.get(SITE + "/page")
    again = client.get(SITE + "/page")
    assert again.from_cache
    assert again.metadata["title"] == "Kept"
    assert site.hits("/page") == 1


def test_cache_survives_a_new_client(
    site: FakeSite, make_client: MakeClient, tmp_path: Path
) -> None:
    site.add("/page", "<title>Kept</title>")
    make_client(cache_dir=tmp_path, cache_ttl=3600, respect_robots=False).get(SITE + "/page")
    again = make_client(cache_dir=tmp_path, cache_ttl=3600, respect_robots=False).get(
        SITE + "/page"
    )
    assert again.from_cache
    assert site.hits("/page") == 1


def test_no_store_responses_and_errors_are_not_cached(
    site: FakeSite, make_client: MakeClient, tmp_path: Path
) -> None:
    site.add("/private", "<title>Secret</title>", headers={"cache-control": "no-store"})
    site.add("/missing", status=404)
    client = make_client(cache_dir=tmp_path, cache_ttl=3600, respect_robots=False)
    for path in ("/private", "/private", "/missing", "/missing"):
        client.fetch(SITE + path)
    assert site.hits("/private") == 2
    assert site.hits("/missing") == 2


# -------------------------------------------------------------------- decoding


def test_decodes_using_the_declared_charset() -> None:
    curly_quotes = chr(0x201C) + "tea" + chr(0x201D)
    # Pages labelled Latin-1 are really Windows-1252, as browsers assume.
    assert decode_body(b"\x93tea\x94", "text/html; charset=ISO-8859-1") == curly_quotes
    assert decode_body(curly_quotes.encode("utf-8"), 'text/html; charset="utf-8"') == curly_quotes


def test_decodes_using_a_meta_charset() -> None:
    hello = "".join(chr(code) for code in (0x41F, 0x440, 0x438, 0x432, 0x435, 0x442))
    body = b'<html><head><meta charset="windows-1251"></head><body>' + hello.encode("cp1251")
    assert hello in decode_body(body, "text/html")


def test_decoding_falls_back_gracefully() -> None:
    assert decode_body(b"\xef\xbb\xbfplain", "") == "plain"
    assert decode_body("caf\xe9".encode("utf-16"), "") == "caf\xe9"
    assert decode_body(b"caf\xe9", "") == "caf\xe9"  # not UTF-8, read as Windows-1252
    assert decode_body(b"abc", "text/html; charset=no-such-charset") == "abc"


def test_context_manager_closes_the_client(site: FakeSite) -> None:
    transport = httpx.MockTransport(site.handle)
    with Client(transport=transport, delay=0) as client:
        client.fetch(SITE + "/")
    with pytest.raises(RuntimeError):
        client.fetch(SITE + "/again")
