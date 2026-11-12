"""Links: absolute addresses, de-duplication and what gets left out."""

from __future__ import annotations

from politescrape import Link, Page

URL = "https://example.test/articles/tea"


def test_links() -> None:
    html = """
    <a href="/about">About   <b>us</b></a>
    <a href="more?page=2#comments">More</a>
    <a href="https://www.example.test/shop">Shop</a>
    <a href="https://other.test/x" rel="NoFollow sponsored">Partner</a>
    <a href="//cdn.other.test/file">Protocol-relative</a>
    <a href="/icon" title="Icon only"><img src="/i.png"></a>
    <a href="/logo"><img src="/logo.png" alt="Example  Mag"></a>
    <a href="/menu" aria-label="Open menu"><svg></svg></a>
    <a href="/nothing"><img src="/spacer.gif"></a>
    <map><area href="/map-region" alt="Region"></map>
    """
    assert Page.from_html(html, URL).links == [
        Link("https://example.test/about", "About us", (), True),
        Link("https://example.test/articles/more?page=2", "More", (), True),
        Link("https://www.example.test/shop", "Shop", (), True),
        Link("https://other.test/x", "Partner", ("nofollow", "sponsored"), False),
        Link("https://cdn.other.test/file", "Protocol-relative", (), False),
        Link("https://example.test/icon", "Icon only", (), True),
        Link("https://example.test/logo", "Example Mag", (), True),
        Link("https://example.test/menu", "Open menu", (), True),
        Link("https://example.test/nothing", "", (), True),
        Link("https://example.test/map-region", "Region", (), True),
    ]


def test_links_that_are_not_web_pages_are_left_out() -> None:
    html = """
    <a href="#top">Top</a>
    <a href="">Empty</a>
    <a>No address</a>
    <a href="mailto:someone@example.test">Mail</a>
    <a href="tel:+15550100">Call</a>
    <a href="javascript:void(0)">Script</a>
    <a href="data:text/plain,hello">Data</a>
    <a href="ftp://example.test/file">FTP</a>
    <a href="/real">Real</a>
    """
    assert [link.url for link in Page.from_html(html, URL).links] == ["https://example.test/real"]


def test_the_first_link_to_an_address_wins() -> None:
    html = '<a href="/a">First</a><a href="/a#part">Second</a><a href="/a?x=1">Different</a>'
    links = Page.from_html(html, URL).links
    assert [(link.url, link.text) for link in links] == [
        ("https://example.test/a", "First"),
        ("https://example.test/a?x=1", "Different"),
    ]


def test_base_href_is_respected() -> None:
    html = '<head><base href="https://cdn.example.test/v2/"></head><a href="page">Page</a>'
    page = Page.from_html(html, URL)
    assert page.base_url == "https://cdn.example.test/v2/"
    assert page.links == [Link("https://cdn.example.test/v2/page", "Page", (), False)]


def test_relative_base_href() -> None:
    page = Page.from_html('<base href="/docs/"><a href="intro">Intro</a>', URL)
    assert page.links[0].url == "https://example.test/docs/intro"


def test_links_stay_relative_when_the_page_address_is_unknown() -> None:
    html = (
        '<a href="/about">About</a><a href="https://other.test/">Other</a>'
        '<a href="mailto:x@y.z">M</a>'
    )
    assert Page.from_html(html).links == [
        Link("/about", "About", (), True),
        Link("https://other.test/", "Other", (), False),
    ]


def test_nofollow_and_to_dict() -> None:
    link = Link("https://other.test/x", "Partner", ("nofollow",), False)
    assert link.nofollow
    assert not Link("https://example.test/", "Home").nofollow
    assert link.to_dict() == {
        "url": "https://other.test/x",
        "text": "Partner",
        "rel": ["nofollow"],
        "internal": False,
    }
