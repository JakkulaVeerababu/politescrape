"""A fetched page and everything that can be read from it."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from functools import cached_property
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

from politescrape._util import NO_BASE, absolute, attr, parse_html
from politescrape.errors import HTTPStatusError
from politescrape.extract.content import Content, extract_content
from politescrape.extract.links import Link, extract_links
from politescrape.extract.metadata import extract_metadata
from politescrape.extract.schema import Schema, apply_schema
from politescrape.extract.structured import extract_json_ld, find_json_ld
from politescrape.extract.tables import Table, extract_tables
from politescrape.response import Response

PARTS = ("metadata", "json_ld", "tables", "links", "content")
"""The parts of a page that :meth:`Page.to_dict` can include."""

HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})


class Page:
    """One page, with its data extracted on demand.

    Nothing is parsed until you ask for it, and every result is computed once
    and then remembered, so reading ``page.tables`` twice costs nothing extra.

    You normally get pages from :meth:`Client.get` or :func:`crawl`. To work
    with HTML you already have, use :meth:`Page.from_html`.
    """

    def __init__(self, response: Response, *, parser: str = "html.parser") -> None:
        self.response = response
        self.parser = parser

    @classmethod
    def from_html(
        cls, html: str | bytes, url: str = NO_BASE, *, parser: str = "html.parser"
    ) -> Page:
        """Build a page from HTML you already have (a saved file, a test fixture).

        Pass the ``url`` the HTML came from so that relative links can be
        resolved; without it they are left as they are.
        """
        if isinstance(html, str):
            content, content_type = html.encode("utf-8"), "text/html; charset=utf-8"
        else:
            content, content_type = html, "text/html"
        response = Response(
            url=url,
            final_url=url,
            status=200,
            headers={"content-type": content_type},
            content=content,
        )
        return cls(response, parser=parser)

    # ------------------------------------------------------------ the response

    @property
    def url(self) -> str:
        """The address of the page, after any redirects."""
        return self.response.final_url

    @property
    def requested_url(self) -> str:
        """The address that was asked for, before any redirects."""
        return self.response.url

    @property
    def status(self) -> int:
        return self.response.status

    @property
    def headers(self) -> dict[str, str]:
        return self.response.headers

    @property
    def ok(self) -> bool:
        """True for 2xx responses."""
        return self.response.ok

    @property
    def from_cache(self) -> bool:
        return self.response.from_cache

    @property
    def content_type(self) -> str:
        return self.response.content_type

    @property
    def is_html(self) -> bool:
        """True when the response is an HTML document."""
        content_type = self.content_type
        if content_type:
            return content_type in HTML_TYPES
        head = self.response.content[:1024].lstrip().lower()
        return head.startswith((b"<!doctype html", b"<html")) or b"<html" in head

    def raise_for_status(self) -> Page:
        """Raise :class:`HTTPStatusError` for 4xx and 5xx responses; otherwise return self."""
        if self.status >= 400:
            raise HTTPStatusError(self.url, self.status)
        return self

    # ------------------------------------------------------------- the content

    @cached_property
    def html(self) -> str:
        """The body decoded to text."""
        return self.response.text

    @cached_property
    def soup(self) -> BeautifulSoup:
        """The parsed document, for when you want to query it yourself.

        Responses that are not HTML give an empty document, so the extractors
        return empty results instead of nonsense.
        """
        return parse_html(self.html if self.is_html else "", self.parser)

    @cached_property
    def base_url(self) -> str:
        """The address that relative links on the page are resolved against."""
        base = self.soup.find("base", href=True)
        if isinstance(base, Tag):
            href = attr(base, "href").strip()
            if href:
                return absolute(self.url, href)
        return self.url

    @cached_property
    def metadata(self) -> dict[str, Any]:
        """Title, description, canonical URL, language, Open Graph data, feeds and more."""
        return extract_metadata(self.soup, self.base_url)

    @cached_property
    def json_ld(self) -> list[dict[str, Any]]:
        """Structured data embedded as JSON-LD (products, articles, events, job postings)."""
        return extract_json_ld(self.soup)

    @cached_property
    def tables(self) -> list[Table]:
        """The data tables on the page."""
        return extract_tables(self.soup)

    @cached_property
    def links(self) -> list[Link]:
        """The links on the page, absolute and de-duplicated."""
        return extract_links(self.soup, self.base_url, self.url)

    @cached_property
    def content(self) -> Content:
        """The main content of the page, without navigation, ads and footers."""
        if not self.is_html:
            return Content(markdown="", text="")
        return extract_content(self.html, self.base_url, parser=self.parser)

    @property
    def markdown(self) -> str:
        """The main content as Markdown."""
        return self.content.markdown

    @property
    def text(self) -> str:
        """The main content as plain text."""
        return self.content.text

    # ---------------------------------------------------------------- querying

    def css(self, selector: str) -> list[Tag]:
        """Return the elements matching a CSS selector."""
        return list(self.soup.select(selector))

    def extract(self, schema: Mapping[str, Any] | Schema) -> Any:
        """Extract the fields described by ``schema`` (see ``docs/extraction-schema.md``).

        Returns a list of objects when the schema has ``items``, otherwise one object.
        """
        return apply_schema(self.soup, schema, self.base_url)

    def find_json_ld(self, type_name: str) -> list[dict[str, Any]]:
        """Return the JSON-LD objects of one type, for example ``"Product"``."""
        return find_json_ld(self.json_ld, type_name)

    def json(self) -> Any:
        """Parse the body as JSON (for API responses)."""
        return json.loads(self.html)

    def to_dict(self, include: Iterable[str] = PARTS) -> dict[str, Any]:
        """Everything about the page as plain data, ready for ``json.dumps``.

        ``include`` chooses the parts to compute: any of ``"metadata"``,
        ``"json_ld"``, ``"tables"``, ``"links"`` and ``"content"``.
        """
        parts = list(include)
        unknown = [part for part in parts if part not in PARTS]
        if unknown:
            raise ValueError(
                f"unknown parts: {', '.join(unknown)} (choose from {', '.join(PARTS)})"
            )
        data: dict[str, Any] = {
            "url": self.url,
            "status": self.status,
            "content_type": self.content_type or None,
            "fetched_at": self.response.fetched_at.isoformat(timespec="seconds"),
            "from_cache": self.from_cache,
        }
        if "metadata" in parts:
            data["metadata"] = self.metadata
        if "json_ld" in parts:
            data["json_ld"] = self.json_ld
        if "tables" in parts:
            data["tables"] = [table.to_dict() for table in self.tables]
        if "links" in parts:
            data["links"] = [link.to_dict() for link in self.links]
        if "content" in parts:
            data["content"] = self.content.to_dict()
        return data

    def __repr__(self) -> str:
        return f"<Page {self.status} {self.url}>"
