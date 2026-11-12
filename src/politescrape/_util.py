"""Small helpers shared by the extractors."""

from __future__ import annotations

import warnings
from collections.abc import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning, XMLParsedAsHTMLWarning
from bs4.element import NavigableString, PreformattedString, Tag

NO_BASE = "about:blank"

# Elements whose content is never shown to a reader.
SKIP_TAGS = frozenset(
    {
        "area", "audio", "button", "canvas", "datalist", "dialog", "embed", "head", "iframe",
        "input", "link", "map", "meta", "noscript", "object", "optgroup", "option", "script",
        "select", "source", "style", "svg", "template", "textarea", "title", "track", "video",
    }
)  # fmt: skip

# Elements that start on a new line when a browser shows them.
BLOCK_TAGS = frozenset(
    {
        "address", "article", "aside", "blockquote", "body", "caption", "center", "dd",
        "details", "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form",
        "h1", "h2", "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "html", "li", "main",
        "menu", "nav", "ol", "p", "pre", "section", "summary", "table", "tbody", "td", "tfoot",
        "th", "thead", "tr", "ul",
    }
)  # fmt: skip


def collapse(text: str) -> str:
    """Collapse every run of whitespace (including non-breaking spaces) to one space."""
    return " ".join(text.split())


def attr(tag: Tag | None, name: str) -> str:
    """Return an attribute as a string; ``""`` when the tag or attribute is missing."""
    if tag is None:
        return ""
    value = tag.get(name)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return " ".join(value)


def attr_list(tag: Tag, name: str) -> list[str]:
    """Return a space-separated attribute (``class``, ``rel``) as a list of tokens."""
    value = tag.get(name)
    if value is None:
        return []
    if isinstance(value, str):
        return value.split()
    return [str(item) for item in value]


def absolute(base_url: str, href: str) -> str:
    """Resolve ``href`` against ``base_url``; leave it alone when there is no base."""
    href = href.strip()
    if not base_url or base_url == NO_BASE:
        return href
    return urljoin(base_url, href)


def only_tags(elements: Iterable[object]) -> list[Tag]:
    """Keep the elements that are tags (drops strings and comments)."""
    return [element for element in elements if isinstance(element, Tag)]


def _gather_text(tag: Tag, parts: list[str]) -> None:
    for child in tag.children:
        if isinstance(child, NavigableString):
            if not isinstance(child, PreformattedString):
                parts.append(str(child))
        elif isinstance(child, Tag):
            if child.name in SKIP_TAGS:
                continue
            if child.name == "br":
                parts.append(" ")
            elif child.name in BLOCK_TAGS:
                parts.append(" ")
                _gather_text(child, parts)
                parts.append(" ")
            else:
                _gather_text(child, parts)


def visible_text(tag: Tag) -> str:
    """The text a reader would see in ``tag``, on one line.

    Unlike ``tag.get_text(" ")`` this keeps ``H<sub>2</sub>O`` as ``H2O`` while
    still separating paragraphs and line breaks, and it leaves out scripts,
    styles and comments.
    """
    parts: list[str] = []
    _gather_text(tag, parts)
    return collapse("".join(parts))


def parse_html(markup: str, parser: str = "html.parser") -> BeautifulSoup:
    """Parse HTML without Beautiful Soup's warnings about odd-looking input."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", MarkupResemblesLocatorWarning)
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        return BeautifulSoup(markup, parser)
