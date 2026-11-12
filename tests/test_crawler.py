"""Crawling: order, limits, rules and politeness."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from politescrape import Client, Crawler, crawl

from .conftest import SITE, FakeSite

MakeClient = Callable[..., Client]


def links(*hrefs: str) -> str:
    return "<title>t</title>" + "".join(f'<a href="{href}">link</a>' for href in hrefs)


@pytest.fixture
def small_site(site: FakeSite) -> FakeSite:
    """/ -> /a, /b ... ; /a -> /c ; /b -> /a ; /c -> /d"""
    site.add("/robots.txt", "User-agent: *\nDisallow: /private/\n", content_type="text/plain")
    site.add(
        "/",
        links(
            "/a",
            "/b",
            "/a#section",
            "/a?utm_source=newsletter",
            "/private/x",
            "https://other.test/page",
            "/files/report.pdf",
            "mailto:someone@example.test",
        )
        + '<a rel="nofollow" href="/login">Log in</a>',
    )
    site.add("/a", links("/c", "/"))
    site.add("/b", links("/a"))
    site.add("/c", links("/d"))
    site.add("/d", links())
    site.add("/login", links())
    site.add("https://other.test/page", links())
    return site


def paths(crawler: Crawler) -> list[str]:
    return [page.url.removeprefix(SITE) for page in crawler]


def test_breadth_first_without_repeats(small_site: FakeSite, make_client: MakeClient) -> None:
    crawler = Crawler(SITE + "/", client=make_client())
    assert paths(crawler) == ["/", "/a", "/b", "/c", "/d"]
    assert small_site.hits("/a") == 1
    assert crawler.stats.to_dict() == {"pages": 5, "errors": 0, "blocked": 1, "skipped": 2}
    # Never requested: the disallowed page, the other site, the PDF and the nofollow link.
    for path in ("/private/x", "/page", "/files/report.pdf", "/login"):
        assert small_site.hits(path) == 0


def test_max_pages(small_site: FakeSite, make_client: MakeClient) -> None:
    crawler = Crawler(SITE + "/", client=make_client(), max_pages=2)
    assert paths(crawler) == ["/", "/a"]
    assert small_site.hits("/b") == 0


@pytest.mark.parametrize(
    ("max_depth", "expected"),
    [
        (0, ["/"]),
        (1, ["/", "/a", "/b"]),
        (2, ["/", "/a", "/b", "/c"]),
        (None, ["/", "/a", "/b", "/c", "/d"]),
    ],
)
def test_max_depth(
    max_depth: int | None, expected: list[str], small_site: FakeSite, make_client: MakeClient
) -> None:
    assert paths(Crawler(SITE + "/", client=make_client(), max_depth=max_depth)) == expected


def test_include_and_exclude_patterns(small_site: FakeSite, make_client: MakeClient) -> None:
    only_a_and_c = Crawler(SITE + "/", client=make_client(), include=[r"/a$", r"/c$"])
    assert paths(only_a_and_c) == ["/", "/a", "/c"]
    no_a = Crawler(SITE + "/", client=make_client(), exclude=r"/a$")
    assert paths(no_a) == ["/", "/b"]


def test_nofollow_links_can_be_followed_on_request(
    small_site: FakeSite, make_client: MakeClient
) -> None:
    crawler = Crawler(SITE + "/", client=make_client(), follow_nofollow=True, max_depth=1)
    assert paths(crawler) == ["/", "/a", "/b", "/login"]


def test_other_sites_are_followed_only_when_allowed(
    small_site: FakeSite, make_client: MakeClient
) -> None:
    urls = [page.url for page in Crawler(SITE + "/", client=make_client(), stay_on_site=False)]
    assert "https://other.test/page" in urls

    domains = Crawler(SITE + "/", client=make_client(), allowed_domains=["other.test"])
    assert [page.url for page in domains] == [SITE + "/", "https://other.test/page"]


def test_subdomains_of_allowed_domains_are_followed(
    site: FakeSite, make_client: MakeClient
) -> None:
    site.add("/", links("https://blog.example.test/post", "https://notexample.test/x"))
    site.add("https://blog.example.test/post", links())
    crawler = Crawler(SITE + "/", client=make_client(), allowed_domains=["Example.test."])
    assert [page.url for page in crawler] == [SITE + "/", "https://blog.example.test/post"]


def test_page_wide_nofollow_is_honoured(site: FakeSite, make_client: MakeClient) -> None:
    site.add("/", '<meta name="robots" content="noindex, NOFOLLOW">' + links("/a"))
    site.add("/a", links())
    assert paths(Crawler(SITE + "/", client=make_client())) == ["/"]

    site.add("/header", links("/a"), headers={"x-robots-tag": "none"})
    assert paths(Crawler(SITE + "/header", client=make_client())) == ["/header"]
    assert paths(Crawler(SITE + "/header", client=make_client(), follow_nofollow=True)) == [
        "/header",
        "/a",
    ]


def test_failed_requests_are_counted_and_the_crawl_goes_on(
    site: FakeSite, make_client: MakeClient
) -> None:
    site.add("/", links("/broken", "/missing", "/fine"))
    site.fail("/broken", httpx.ConnectError("connection reset"))
    site.add("/fine", links())
    crawler = Crawler(SITE + "/", client=make_client(retries=0))
    pages = list(crawler)
    assert [(page.url.removeprefix(SITE), page.status) for page in pages] == [
        ("/", 200),
        ("/missing", 404),
        ("/fine", 200),
    ]
    assert crawler.stats.errors == 1


def test_links_are_not_read_from_error_pages_or_other_file_types(
    site: FakeSite, make_client: MakeClient
) -> None:
    site.add("/", links("/data", "/gone"))
    site.add("/data", '{"next": "<a href=\\"/hidden\\">x</a>"}', content_type="application/json")
    site.add("/gone", links("/hidden"), status=410)
    assert paths(Crawler(SITE + "/", client=make_client())) == ["/", "/data", "/gone"]


def test_redirect_targets_are_not_fetched_twice(site: FakeSite, make_client: MakeClient) -> None:
    site.add("/", links("/old", "/older", "/new"))
    site.add("/old", status=301, headers={"location": "/new"})
    site.add("/older", status=302, headers={"location": "/new"})
    site.add("/new", links())
    crawler = Crawler(SITE + "/", client=make_client())
    assert paths(crawler) == ["/", "/new"]
    assert crawler.stats.pages == 2


def test_sitemaps_from_robots_txt(site: FakeSite, make_client: MakeClient) -> None:
    site.add(
        "/robots.txt",
        f"User-agent: *\nDisallow: /secret\nSitemap: {SITE}/sitemap-index.xml\n",
        content_type="text/plain",
    )
    site.add(
        "/sitemap-index.xml",
        f"<sitemapindex><sitemap><loc>{SITE}/sitemap-pages.xml</loc></sitemap>"
        f"<sitemap><loc>{SITE}/sitemap-missing.xml</loc></sitemap>"
        f"<sitemap><loc>{SITE}/sitemap-index.xml</loc></sitemap></sitemapindex>",
        content_type="application/xml",
    )
    site.add(
        "/sitemap-pages.xml",
        f"<urlset><url><loc>{SITE}/deep/page</loc></url><url><loc>{SITE}/secret</loc></url>"
        f"<url><loc>https://other.test/elsewhere</loc></url><url><loc>{SITE}/</loc></url></urlset>",
        content_type="application/xml",
    )
    site.add("/", links())
    site.add("/deep/page", links("/deep/child"))
    site.add("/deep/child", links())

    crawler = Crawler(SITE + "/", client=make_client(), sitemaps=True, max_depth=0)
    assert paths(crawler) == ["/", "/deep/page"]
    assert crawler.stats.blocked == 1  # /secret was listed but is disallowed
    assert site.hits("/sitemap-index.xml") == 1


def test_default_sitemap_location_is_tried(site: FakeSite, make_client: MakeClient) -> None:
    site.add("/sitemap.xml", f"{SITE}/from-sitemap\n", content_type="text/plain")
    site.add("/", links())
    site.add("/from-sitemap", links())
    assert paths(Crawler(SITE + "/", client=make_client(), sitemaps=True)) == ["/", "/from-sitemap"]


def test_several_start_pages_and_duplicates(small_site: FakeSite, make_client: MakeClient) -> None:
    crawler = Crawler([SITE + "/c", SITE + "/b", SITE + "/c#top"], client=make_client())
    assert crawler.start_urls == [SITE + "/c", SITE + "/b"]
    assert paths(crawler) == ["/c", "/b", "/d", "/a", "/"]


def test_crawl_creates_and_closes_its_own_client(small_site: FakeSite) -> None:
    transport = httpx.MockTransport(small_site.handle)
    crawler = crawl(SITE + "/", max_pages=3, transport=transport, delay=0)
    assert isinstance(crawler, Crawler)
    assert paths(crawler) == ["/", "/a", "/b"]
    # Iterating again starts a fresh crawl with fresh statistics.
    assert paths(crawler) == ["/", "/a", "/b"]
    assert crawler.stats.pages == 3


@pytest.mark.parametrize(
    ("arguments", "error", "message"),
    [
        (([],), ValueError, "at least one start URL"),
        (("ftp://example.test/",), ValueError, "not an http"),
        ((["https://example.test/", "/relative"],), ValueError, "not an http"),
    ],
)
def test_invalid_start_pages(
    arguments: tuple[object, ...], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        Crawler(*arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("options", "error", "message"),
    [
        ({"max_pages": 0}, ValueError, "max_pages"),
        ({"max_depth": -1}, ValueError, "max_depth"),
        ({"include": "("}, ValueError, "include: invalid pattern"),
        ({"exclude": ["ok", "["]}, ValueError, "exclude: invalid pattern"),
    ],
)
def test_invalid_options(options: dict[str, object], error: type[Exception], message: str) -> None:
    with pytest.raises(error, match=message):
        Crawler(SITE + "/", **options)  # type: ignore[arg-type]


def test_a_client_and_client_options_cannot_be_combined(make_client: MakeClient) -> None:
    with pytest.raises(TypeError, match="either a client or client options"):
        Crawler(SITE + "/", client=make_client(), delay=5)
