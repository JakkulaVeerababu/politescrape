"""Reading sitemaps."""

from __future__ import annotations

import gzip

from politescrape.sitemaps import parse_sitemap

URLSET = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
  <url>
    <loc> https://example.test/a </loc>
    <lastmod>2026-01-01</lastmod>
    <image:image><image:loc>https://example.test/a.jpg</image:loc></image:image>
  </url>
  <url><loc>https://example.test/b?x=1&amp;y=2</loc></url>
  <url><loc>not a url</loc></url>
  <url><lastmod>2026-01-01</lastmod></url>
</urlset>
"""

INDEX = b"""<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.test/sitemap-1.xml</loc></sitemap>
  <sitemap><loc>https://example.test/sitemap-2.xml.gz</loc></sitemap>
</sitemapindex>
"""


def test_urlset_lists_pages_and_ignores_image_addresses() -> None:
    assert parse_sitemap(URLSET) == (
        ["https://example.test/a", "https://example.test/b?x=1&y=2"],
        [],
    )


def test_sitemap_index_lists_further_sitemaps() -> None:
    assert parse_sitemap(INDEX) == (
        [],
        ["https://example.test/sitemap-1.xml", "https://example.test/sitemap-2.xml.gz"],
    )


def test_urlset_without_a_namespace() -> None:
    assert parse_sitemap(b"<urlset><url><loc>https://example.test/a</loc></url></urlset>") == (
        ["https://example.test/a"],
        [],
    )


def test_gzipped_sitemaps_are_decompressed() -> None:
    assert parse_sitemap(gzip.compress(URLSET))[0][0] == "https://example.test/a"
    assert parse_sitemap(b"\x1f\x8b not really gzip") == ([], [])


def test_plain_text_sitemap() -> None:
    text = b"https://example.test/a\n\n  https://example.test/b  \nnot a url\n"
    assert parse_sitemap(text) == (["https://example.test/a", "https://example.test/b"], [])


def test_feeds_can_serve_as_sitemaps() -> None:
    rss = b"""<rss version="2.0"><channel><link>https://example.test/</link>
    <item><title>One</title><link>https://example.test/one</link></item></channel></rss>"""
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom">
    <link rel="self" href="https://example.test/feed"/>
    <entry><link href="https://example.test/entry"/></entry></feed>"""
    assert parse_sitemap(rss) == (["https://example.test/", "https://example.test/one"], [])
    assert parse_sitemap(atom) == (["https://example.test/entry"], [])


def test_unreadable_documents_give_nothing() -> None:
    assert parse_sitemap(b"") == ([], [])
    assert parse_sitemap(b"<urlset><url><loc>https://example.test/a</loc>") == ([], [])
    assert parse_sitemap(b"<html><body>Not found</body></html>") == ([], [])


def test_documents_that_define_entities_are_refused() -> None:
    bomb = b"""<?xml version="1.0"?>
    <!DOCTYPE urlset [<!ENTITY a "https://example.test/a">]>
    <urlset><url><loc>&a;</loc></url></urlset>"""
    assert parse_sitemap(bomb) == ([], [])
