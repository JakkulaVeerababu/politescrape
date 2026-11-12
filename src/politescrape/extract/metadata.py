"""Page metadata: title, description, Open Graph, feeds and friends."""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

from politescrape._util import absolute, attr, attr_list, collapse, only_tags

FEED_TYPES = {
    "application/rss+xml": "rss",
    "application/atom+xml": "atom",
    "application/feed+json": "json",
}
_PUBLISHED_KEYS = (
    "article:published_time",
    "og:published_time",
    "datepublished",
    "date",
    "dc.date",
    "dcterms.created",
    "pubdate",
    "publishdate",
)
_MODIFIED_KEYS = ("article:modified_time", "og:updated_time", "datemodified", "dcterms.modified")


def _first(meta: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = meta.get(key)
        if value:
            return value
    return None


def extract_metadata(soup: BeautifulSoup, base_url: str = "") -> dict[str, Any]:
    """Collect what a page says about itself.

    The result always has the same keys. Values that the page does not state
    are ``None`` (or empty lists and dictionaries). URLs are made absolute.
    """
    meta: dict[str, str] = {}
    for tag in only_tags(soup.find_all("meta")):
        key = (
            attr(tag, "property")
            or attr(tag, "name")
            or attr(tag, "itemprop")
            or attr(tag, "http-equiv")
        )
        key = key.strip().lower()
        content = tag.get("content")
        if key and isinstance(content, str) and content.strip():
            meta.setdefault(key, collapse(content))

    links = only_tags(soup.find_all("link", href=True))

    def link(*relations: str) -> str | None:
        for candidate in links:
            rel = [value.lower() for value in attr_list(candidate, "rel")]
            if any(relation in rel for relation in relations):
                return absolute(base_url, attr(candidate, "href"))
        return None

    feeds = []
    for candidate in links:
        rel = [value.lower() for value in attr_list(candidate, "rel")]
        kind = FEED_TYPES.get(attr(candidate, "type").strip().lower())
        if "alternate" in rel and kind:
            feeds.append(
                {
                    "url": absolute(base_url, attr(candidate, "href")),
                    "type": kind,
                    "title": collapse(attr(candidate, "title")) or None,
                }
            )

    title_tag = soup.find("title")
    title = collapse(title_tag.get_text()) if isinstance(title_tag, Tag) else ""
    html_tag = soup.find("html")
    language = attr(html_tag, "lang").strip() if isinstance(html_tag, Tag) else ""
    image = _first(meta, "og:image", "og:image:url", "og:image:secure_url", "twitter:image")
    canonical = link("canonical")
    if canonical is None and meta.get("og:url"):
        canonical = absolute(base_url, meta["og:url"])

    return {
        "title": title or _first(meta, "og:title", "twitter:title"),
        "description": _first(meta, "description", "og:description", "twitter:description"),
        "canonical_url": canonical,
        "language": language or _first(meta, "content-language", "og:locale"),
        "author": _first(meta, "author", "article:author", "twitter:creator"),
        "published_at": _first(meta, *_PUBLISHED_KEYS),
        "modified_at": _first(meta, *_MODIFIED_KEYS),
        "site_name": _first(meta, "og:site_name", "application-name"),
        "type": meta.get("og:type"),
        "image": absolute(base_url, image) if image else None,
        "favicon": link("icon", "apple-touch-icon"),
        "keywords": [word.strip() for word in meta.get("keywords", "").split(",") if word.strip()],
        "robots": meta.get("robots"),
        "feeds": feeds,
        "open_graph": {key[3:]: value for key, value in meta.items() if key.startswith("og:")},
        "twitter": {key[8:]: value for key, value in meta.items() if key.startswith("twitter:")},
    }
