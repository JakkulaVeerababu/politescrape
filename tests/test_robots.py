"""robots.txt behaviour, following the rules and examples of RFC 9309."""

from __future__ import annotations

import pytest

from politescrape.robots import RobotsTxt, product_token

BOT = "politescrape/0.1 (+https://example.org/bot)"

ROBOTS = """
# Rules for everyone
User-agent: *
Disallow: /private/
Allow: /private/annual-report.html
Disallow: /*.pdf$
Crawl-delay: 2

User-agent: PoliteScrape
User-agent: otherbot
Disallow: /named-only/
Crawl-delay: 5

Sitemap: https://example.test/sitemap.xml
Sitemap: https://example.test/news-sitemap.xml
"""


@pytest.mark.parametrize(
    ("user_agent", "token"),
    [
        ("politescrape/0.1 (+https://example.org)", "politescrape"),
        ("My-Bot/2.0", "my-bot"),
        ("  Research_Crawler  ", "research_crawler"),
        ("Mozilla/5.0 (compatible; x)", "mozilla"),
    ],
)
def test_product_token(user_agent: str, token: str) -> None:
    assert product_token(user_agent) == token


def test_star_group_applies_to_agents_without_their_own_group() -> None:
    robots = RobotsTxt.parse(ROBOTS)
    assert not robots.can_fetch("somebot/1.0", "/private/notes.html")
    assert robots.can_fetch("somebot/1.0", "/public/notes.html")
    assert robots.crawl_delay("somebot/1.0") == 2


def test_own_group_replaces_the_star_group() -> None:
    robots = RobotsTxt.parse(ROBOTS)
    # Matching is case-insensitive and ignores the version.
    assert robots.can_fetch(BOT, "/private/notes.html")
    assert not robots.can_fetch(BOT, "/named-only/page")
    assert not robots.can_fetch("OtherBot", "/named-only/page")
    assert robots.crawl_delay(BOT) == 5


def test_most_specific_rule_wins() -> None:
    robots = RobotsTxt.parse(ROBOTS)
    assert robots.can_fetch("somebot", "/private/annual-report.html")
    assert not robots.can_fetch("somebot", "/private/annual-report-draft.html")


def test_allow_wins_when_rules_are_equally_specific() -> None:
    robots = RobotsTxt.parse("User-agent: *\nDisallow: /page\nAllow: /page\n")
    assert robots.can_fetch("anybot", "/page")
    robots = RobotsTxt.parse("User-agent: *\nAllow: /page\nDisallow: /page\n")
    assert robots.can_fetch("anybot", "/page")


def test_wildcard_and_end_anchor() -> None:
    robots = RobotsTxt.parse(ROBOTS)
    assert not robots.can_fetch("somebot", "/files/report.pdf")
    assert robots.can_fetch("somebot", "/files/report.pdf?download=1")
    assert robots.can_fetch("somebot", "/files/report.pdf.html")

    robots = RobotsTxt.parse("User-agent: *\nDisallow: /search*sort=\nDisallow: /exact$\n")
    assert not robots.can_fetch("b", "/search?q=tea&sort=price")
    assert robots.can_fetch("b", "/search?q=tea")
    assert not robots.can_fetch("b", "/exact")
    assert robots.can_fetch("b", "/exact/more")


def test_groups_for_the_same_agent_are_merged() -> None:
    text = """
User-agent: ExampleBot
Disallow: /foo
Disallow: /bar

User-agent: ExampleBot
Disallow: /baz
"""
    robots = RobotsTxt.parse(text)
    for path in ("/foo", "/bar", "/baz"):
        assert not robots.can_fetch("examplebot/1.0", path)
    assert robots.can_fetch("examplebot/1.0", "/other")


def test_no_matching_group_and_no_star_group_allows_everything() -> None:
    robots = RobotsTxt.parse("User-agent: examplebot\nDisallow: /\n")
    assert robots.can_fetch("politescrape", "/anything")
    assert robots.crawl_delay("politescrape") is None


def test_empty_disallow_allows_everything() -> None:
    robots = RobotsTxt.parse("User-agent: *\nDisallow:\n")
    assert robots.can_fetch("anybot", "/anything")


def test_rules_before_any_user_agent_line_are_ignored() -> None:
    robots = RobotsTxt.parse("Disallow: /\nUser-agent: *\nDisallow: /x\n")
    assert robots.can_fetch("anybot", "/y")
    assert not robots.can_fetch("anybot", "/x")


def test_robots_txt_itself_may_always_be_fetched() -> None:
    assert RobotsTxt.disallow_all().can_fetch("anybot", "/robots.txt")
    assert RobotsTxt.disallow_all().can_fetch("anybot", "https://example.test/robots.txt")


def test_percent_encoded_paths_compare_equal() -> None:
    cafe = "/caf" + chr(0xE9)
    robots = RobotsTxt.parse("User-agent: *\nDisallow: /caf%C3%A9\nDisallow: /a%7Eb\n")
    assert not robots.can_fetch("b", cafe)
    assert not robots.can_fetch("b", "/caf%c3%a9/menu")
    assert not robots.can_fetch("b", "/a~b")
    # An encoded slash is not the same as a real one.
    robots = RobotsTxt.parse("User-agent: *\nDisallow: /a/b\n")
    assert robots.can_fetch("b", "/a%2Fb")


def test_full_urls_are_matched_on_path_and_query() -> None:
    robots = RobotsTxt.parse("User-agent: *\nDisallow: /search?\n")
    assert not robots.can_fetch("b", "https://example.test/search?q=1")
    assert robots.can_fetch("b", "https://example.test/search")
    assert robots.can_fetch("b", "https://example.test")


def test_sitemaps_and_comments() -> None:
    robots = RobotsTxt.parse(ROBOTS)
    assert robots.sitemaps == [
        "https://example.test/sitemap.xml",
        "https://example.test/news-sitemap.xml",
    ]
    robots = RobotsTxt.parse("User-agent: * # everyone\nDisallow: /x # not this\n")
    assert not robots.can_fetch("b", "/x")


@pytest.mark.parametrize("value", ["soon", "-1", "inf", "nan", ""])
def test_unreadable_crawl_delay_is_ignored(value: str) -> None:
    robots = RobotsTxt.parse(f"User-agent: *\nCrawl-delay: {value}\n")
    assert robots.crawl_delay("b") is None


def test_parses_bytes_with_a_byte_order_mark() -> None:
    robots = RobotsTxt.parse(b"\xef\xbb\xbfUser-agent: *\r\nDisallow: /x\r\n")
    assert not robots.can_fetch("b", "/x")


def test_allow_all_and_disallow_all() -> None:
    assert RobotsTxt.allow_all().can_fetch("b", "/anything")
    assert not RobotsTxt.disallow_all().can_fetch("b", "/anything")
    assert not RobotsTxt.disallow_all().can_fetch("politescrape", "/")
