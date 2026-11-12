"""The links on a page."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urldefrag, urlsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

from politescrape._util import absolute, attr, attr_list, collapse, only_tags, visible_text
from politescrape.urls import is_http_url, same_site


@dataclass(frozen=True)
class Link:
    """One link: where it goes and what it says."""

    url: str
    text: str
    rel: tuple[str, ...] = ()
    internal: bool = False
    """True when the link stays on the same site as the page."""

    @property
    def nofollow(self) -> bool:
        """True when the page asks crawlers not to follow this link."""
        return "nofollow" in self.rel

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "text": self.text,
            "rel": list(self.rel),
            "internal": self.internal,
        }


def extract_links(soup: BeautifulSoup, base_url: str = "", page_url: str = "") -> list[Link]:
    """Return the web links on a page, absolute and without duplicates.

    Links are resolved against ``base_url``; when no base address is known,
    relative links are kept as they are. Fragments are removed, and links
    that do not lead to a web page (``mailto:``, ``tel:``, ``javascript:``)
    are left out. The first link to each address wins.
    """
    links: list[Link] = []
    seen: set[str] = set()
    for anchor in only_tags(soup.find_all(["a", "area"], href=True)):
        href = attr(anchor, "href").strip()
        if not href or href.startswith("#"):
            continue
        url = urldefrag(absolute(base_url, href)).url
        relative = _is_relative(url)
        if not (relative or is_http_url(url)) or url in seen:
            continue
        seen.add(url)
        links.append(
            Link(
                url=url,
                text=_label(anchor),
                rel=tuple(value.lower() for value in attr_list(anchor, "rel")),
                internal=relative or same_site(url, page_url or base_url),
            )
        )
    return links


def _label(anchor: Tag) -> str:
    """What a link says: its text, or else the label a screen reader would use."""
    text = visible_text(anchor)
    if text:
        return text
    for name in ("aria-label", "title", "alt"):
        label = collapse(attr(anchor, name))
        if label:
            return label
    image = anchor.find("img", alt=True)
    return collapse(attr(image, "alt")) if isinstance(image, Tag) else ""


def _is_relative(url: str) -> bool:
    """True for an address without scheme and host, such as ``/about``."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return bool(url) and not parts.scheme and not parts.netloc
