"""Page metadata and embedded JSON-LD."""

from __future__ import annotations

from politescrape import Page
from politescrape._util import parse_html
from politescrape.extract import extract_json_ld, extract_metadata, find_json_ld, json_ld_types

URL = "https://example.test/articles/tea"

HEAD = """
<html lang="en-GB"><head>
  <title>  All about tea
     | Example Mag </title>
  <meta name="description" content="Short facts   about tea.">
  <meta name="Author" content="A. Writer">
  <meta name="keywords" content="tea, drinks, , caffeine">
  <meta name="robots" content="index, nofollow">
  <meta property="og:title" content="All about tea">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="Example Mag">
  <meta property="og:image" content="/img/tea.jpg">
  <meta property="og:image" content="/img/second.jpg">
  <meta property="article:published_time" content="2026-03-01T08:00:00Z">
  <meta property="article:modified_time" content="2026-03-02T09:30:00Z">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:empty" content="">
  <link rel="canonical" href="/articles/tea">
  <link rel="shortcut icon" href="/favicon.ico">
  <link rel="alternate" type="application/rss+xml" title="News feed" href="/feed.xml">
  <link rel="alternate" type="application/atom+xml" href="https://feeds.example.test/atom">
  <link rel="alternate" hreflang="fr" href="/fr/articles/the">
  <link rel="stylesheet" href="/style.css">
</head><body></body></html>
"""


def test_metadata() -> None:
    assert Page.from_html(HEAD, URL).metadata == {
        "title": "All about tea | Example Mag",
        "description": "Short facts about tea.",
        "canonical_url": "https://example.test/articles/tea",
        "language": "en-GB",
        "author": "A. Writer",
        "published_at": "2026-03-01T08:00:00Z",
        "modified_at": "2026-03-02T09:30:00Z",
        "site_name": "Example Mag",
        "type": "article",
        "image": "https://example.test/img/tea.jpg",
        "favicon": "https://example.test/favicon.ico",
        "keywords": ["tea", "drinks", "caffeine"],
        "robots": "index, nofollow",
        "feeds": [
            {"url": "https://example.test/feed.xml", "type": "rss", "title": "News feed"},
            {"url": "https://feeds.example.test/atom", "type": "atom", "title": None},
        ],
        "open_graph": {
            "title": "All about tea",
            "type": "article",
            "site_name": "Example Mag",
            "image": "/img/tea.jpg",
        },
        "twitter": {"card": "summary_large_image"},
    }


def test_metadata_falls_back_to_open_graph_and_twitter() -> None:
    html = """
    <head>
      <meta property="og:title" content="From Open Graph">
      <meta name="twitter:description" content="From Twitter">
      <meta property="og:url" content="https://example.test/canonical">
      <meta property="og:locale" content="en_IN">
      <meta name="twitter:image" content="https://cdn.example.test/card.png">
    </head>
    """
    metadata = extract_metadata(parse_html(html), URL)
    assert metadata["title"] == "From Open Graph"
    assert metadata["description"] == "From Twitter"
    assert metadata["canonical_url"] == "https://example.test/canonical"
    assert metadata["language"] == "en_IN"
    assert metadata["image"] == "https://cdn.example.test/card.png"


def test_metadata_of_an_empty_page_has_every_key() -> None:
    metadata = extract_metadata(parse_html(""))
    assert set(metadata) == set(Page.from_html(HEAD, URL).metadata)
    assert metadata["title"] is None
    assert metadata["keywords"] == []
    assert metadata["feeds"] == []
    assert metadata["open_graph"] == {}


def json_ld(*blocks: str, kind: str = "application/ld+json") -> list[dict[str, object]]:
    scripts = "".join(f'<script type="{kind}">{block}</script>' for block in blocks)
    return extract_json_ld(parse_html(f"<head>{scripts}</head>"))


def test_json_ld_objects_and_arrays() -> None:
    items = json_ld(
        '{"@context": "https://schema.org", "@type": "Product", "name": "Teapot"}',
        '[{"@type": "Organization", "name": "Example"}, {"@type": "WebSite"}, "stray text"]',
    )
    assert [item["@type"] for item in items] == ["Product", "Organization", "WebSite"]
    assert items[0]["name"] == "Teapot"


def test_json_ld_graphs_are_flattened_and_keep_their_context() -> None:
    items = json_ld(
        '{"@context": "https://schema.org", "@graph": ['
        '{"@type": "Article", "headline": "Tea"},'
        '{"@context": "https://example.test/ns", "@type": "Person", "name": "A. Writer"}]}'
    )
    assert items == [
        {"@context": "https://schema.org", "@type": "Article", "headline": "Tea"},
        {"@context": "https://example.test/ns", "@type": "Person", "name": "A. Writer"},
    ]


def test_json_ld_with_common_mistakes_is_still_read() -> None:
    items = json_ld(
        '<!-- {"@type": "Commented"} -->',
        '//<![CDATA[\n{"@type": "Wrapped"}\n//]]>',
        '{"@type": "TrailingComma", "tags": ["a", "b",],}',
        '{"@type": "RawNewline", "text": "line one\nline two"}',
        kind="application/ld+json; charset=utf-8",
    )
    assert [item["@type"] for item in items] == [
        "Commented",
        "Wrapped",
        "TrailingComma",
        "RawNewline",
    ]


def test_unreadable_json_ld_and_other_scripts_are_skipped() -> None:
    html = """
    <script type="application/ld+json">{not json at all</script>
    <script type="application/ld+json">   </script>
    <script type="application/json">{"@type": "NotLinkedData"}</script>
    <script>var x = {"@type": "Script"};</script>
    <script type="application/ld+json">{"@type": "Good"}</script>
    """
    assert extract_json_ld(parse_html(html)) == [{"@type": "Good"}]


def test_find_json_ld_by_type() -> None:
    items = [
        {"@type": "ItemList", "itemListElement": [{"@type": "Product", "name": "Nested"}]},
        {"@type": ["Product", "Thing"], "name": "Listed"},
        {"@type": "https://schema.org/Product", "name": "Full address"},
        {"@type": "schema:Product", "name": "Prefixed"},
        {"@type": "ProductGroup", "name": "Different type"},
        {"name": "No type", "@type": 5},
    ]
    names = [item["name"] for item in find_json_ld(items, "product")]
    assert names == ["Nested", "Listed", "Full address", "Prefixed"]
    assert json_ld_types(items[1]) == ["Product", "Thing"]
    assert json_ld_types(items[5]) == []


def test_page_find_json_ld() -> None:
    html = '<script type="application/ld+json">{"@type": "JobPosting", "title": "Chemist"}</script>'
    page = Page.from_html(html)
    assert page.find_json_ld("JobPosting") == [{"@type": "JobPosting", "title": "Chemist"}]
    assert page.find_json_ld("Product") == []
