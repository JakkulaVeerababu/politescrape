"""Reading sitemaps: XML sitemaps, sitemap indexes, feeds and plain lists of URLs."""

from __future__ import annotations

import gzip
import io
import re
import zlib
from xml.etree import ElementTree

from politescrape.urls import is_http_url

MAX_SITEMAP_BYTES = 50 * 1024 * 1024
"""The sitemap protocol's own size limit for one (uncompressed) file."""

_ENTITY = re.compile(rb"<!ENTITY", re.IGNORECASE)


def _gunzip(content: bytes) -> bytes:
    """Decompress a ``.gz`` sitemap, never producing more than the size limit."""
    if not content.startswith(b"\x1f\x8b"):
        return content
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(content)) as archive:
            return archive.read(MAX_SITEMAP_BYTES)
    except (OSError, EOFError, zlib.error):
        return b""


def _local(tag: str) -> str:
    """An element's name without its XML namespace."""
    return tag.rsplit("}", 1)[-1].lower()


def _web_urls(candidates: list[str | None]) -> list[str]:
    urls = []
    for candidate in candidates:
        url = (candidate or "").strip()
        if is_http_url(url):
            urls.append(url)
    return urls


def _locations(root: ElementTree.Element, entry_name: str) -> list[str]:
    """The ``<loc>`` directly inside every ``<url>`` or ``<sitemap>`` entry.

    Reading only direct children leaves out the image and video addresses that
    some sitemaps list inside each entry.
    """
    found: list[str | None] = []
    for entry in root:
        if _local(entry.tag) != entry_name:
            continue
        for child in entry:
            if _local(child.tag) == "loc":
                found.append(child.text)
                break
    return _web_urls(found)


def parse_sitemap(content: bytes) -> tuple[list[str], list[str]]:
    """Read one sitemap file.

    Returns ``(pages, sitemaps)``: the page addresses it lists, and the
    addresses of further sitemaps when the file is a sitemap index. Files
    that cannot be read give two empty lists.
    """
    data = _gunzip(content)
    if not data.lstrip().startswith(b"<"):
        lines = data.decode("utf-8", errors="replace").splitlines()
        return _web_urls(list(lines)), []
    if _ENTITY.search(data):
        # Sitemaps never need custom entities; refusing them rules out
        # entity-expansion attacks whatever XML library is underneath.
        return [], []
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return [], []
    kind = _local(root.tag)
    if kind == "sitemapindex":
        return [], _locations(root, "sitemap")
    if kind == "urlset":
        return _locations(root, "url"), []
    if kind == "rss":
        return _web_urls([el.text for el in root.iter() if _local(el.tag) == "link"]), []
    if kind == "feed":
        links = [
            el.get("href")
            for el in root.iter()
            if _local(el.tag) == "link" and el.get("rel", "alternate") == "alternate"
        ]
        return _web_urls(links), []
    return [], []
