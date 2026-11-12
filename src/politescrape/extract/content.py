"""Find the main content of a page and return it as Markdown and plain text.

The approach is deliberately simple and predictable:

1. remove what is clearly not content (scripts, navigation, footers, cookie
   banners, hidden elements);
2. pick the element that holds the content: the page's ``<article>`` or
   ``<main>`` if it has one, otherwise the element with the most paragraph
   text;
3. convert that element to Markdown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

from politescrape._util import attr, attr_list, only_tags, parse_html
from politescrape.markdown import to_markdown, to_text

_REMOVE_TAGS = [
    "aside", "button", "canvas", "dialog", "embed", "iframe", "input", "nav", "noscript",
    "object", "script", "select", "style", "svg", "template", "textarea",
]  # fmt: skip
_REMOVE_ROLES = frozenset(
    {"alertdialog", "banner", "complementary", "contentinfo", "dialog", "navigation", "search"}
)
_BOILERPLATE = re.compile(
    r"(?:^|[\s_-])"
    r"(?:ad|ads|advert|advertisement|breadcrumb|breadcrumbs|comment|comments|consent|cookie"
    r"|cookies|footer|gdpr|menu|modal|nav|navbar|navigation|newsletter|popup|promo|related"
    r"|share|sharing|sidebar|social|sponsored|subscribe)"
    r"(?:$|[\s_-])",
    re.IGNORECASE,
)
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.IGNORECASE)
_CONTENT_ROOTS = ["article", "main"]
_NEVER_REMOVE = frozenset({"html", "body", "article", "main"})
# An element holding more than this share of the page's text is not boilerplate,
# whatever its class name says.
_MAX_BOILERPLATE_SHARE = 0.5
_MIN_PARAGRAPH = 25
_MIN_SCORE = 140


@dataclass(frozen=True)
class Content:
    """The main content of a page."""

    markdown: str
    text: str

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    def to_dict(self) -> dict[str, Any]:
        return {"markdown": self.markdown, "text": self.text, "word_count": self.word_count}


def extract_content(html: str, base_url: str = "", *, parser: str = "html.parser") -> Content:
    """Extract the main content of an HTML document.

    The document is parsed afresh because finding the content removes
    elements, and the caller's own parsed copy should stay intact.
    """
    soup = parse_html(html, parser)
    _strip_boilerplate(soup)
    root = _pick_root(soup)
    return Content(markdown=to_markdown(root, base_url), text=to_text(root, base_url))


def _text_length(tag: Tag) -> int:
    return len(tag.get_text(" ", strip=True))


def _holds_content_root(tag: Tag) -> bool:
    return tag.name in _NEVER_REMOVE or tag.find(_CONTENT_ROOTS) is not None


def _strip_boilerplate(soup: BeautifulSoup) -> None:
    for tag in only_tags(soup.find_all(_REMOVE_TAGS)):
        if not tag.decomposed:
            tag.decompose()

    # Site-wide headers and footers go; an article's own header (its title) stays.
    for tag in only_tags(soup.find_all(["header", "footer"])):
        if tag.decomposed or tag.find_parent(_CONTENT_ROOTS) is not None:
            continue
        if tag.find(_CONTENT_ROOTS) is None:
            tag.decompose()

    body = soup.body if soup.body is not None else soup
    page_length = max(_text_length(body), 1)
    for tag in only_tags(soup.find_all(True)):
        if tag.decomposed or _holds_content_root(tag):
            continue
        hidden = tag.has_attr("hidden") or bool(_HIDDEN_STYLE.search(attr(tag, "style")))
        # Search boxes and sign-up forms are boilerplate, but some sites wrap the
        # whole page in one <form>, so a form only goes when it holds little text.
        labelled = (
            tag.name == "form"
            or attr(tag, "aria-hidden").strip().lower() == "true"
            or attr(tag, "role").strip().lower() in _REMOVE_ROLES
            or bool(_BOILERPLATE.search(" ".join([*attr_list(tag, "class"), attr(tag, "id")])))
        )
        if hidden or (labelled and _text_length(tag) <= page_length * _MAX_BOILERPLATE_SHARE):
            tag.decompose()


def _pick_root(soup: BeautifulSoup) -> Tag:
    body: Tag = soup.body if soup.body is not None else soup

    articles = [
        tag for tag in only_tags(body.find_all("article")) if not tag.find_parent("article")
    ]
    if len(articles) == 1 and _text_length(articles[0]) > 0:
        return articles[0]
    if len(articles) > 1:
        # Several articles: one long one is the story, many similar ones are a listing.
        lengths = [_text_length(article) for article in articles]
        longest = max(lengths)
        if longest >= 0.6 * max(sum(lengths), 1):
            return articles[lengths.index(longest)]

    main = body.select_one('main, [role="main"]')
    if main is not None:
        return main
    if articles:
        return body

    # No landmarks: score each element by the paragraph text directly inside it
    # (and, at half weight, inside its children).
    scores: dict[int, tuple[float, Tag]] = {}
    for paragraph in only_tags(body.find_all(["p", "pre"])):
        length = _text_length(paragraph)
        if length < _MIN_PARAGRAPH:
            continue
        parent = paragraph.parent
        grandparent = parent.parent if parent is not None else None
        for weight, ancestor in ((1.0, parent), (0.5, grandparent)):
            if isinstance(ancestor, Tag) and not isinstance(ancestor, BeautifulSoup):
                score = scores.get(id(ancestor), (0.0, ancestor))[0]
                scores[id(ancestor)] = (score + weight * length, ancestor)
    if scores:
        score, best = max(scores.values(), key=lambda entry: entry[0])
        if score >= _MIN_SCORE and best.name != "html":
            return best
    return body
