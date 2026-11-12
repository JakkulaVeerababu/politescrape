"""The Page object."""

from __future__ import annotations

import json

import pytest

from politescrape import HTTPStatusError, Page, Response
from politescrape.page import PARTS

URL = "https://example.test/articles/tea"
HTML = """
<html><head><title>Tea</title></head><body>
<article><h1>Tea</h1><p>A page about tea.</p></article>
<table><tr><th>A</th></tr><tr><td>1</td></tr></table>
<a href="/more">More</a>
<script type="application/ld+json">{"@type": "Article"}</script>
</body></html>
"""


def response(body: bytes, content_type: str | None, status: int = 200) -> Response:
    headers = {"content-type": content_type} if content_type else {}
    return Response(url=URL, final_url=URL, status=status, headers=headers, content=body)


def test_from_html_text() -> None:
    page = Page.from_html(HTML, URL)
    assert page.url == URL
    assert page.requested_url == URL
    assert page.status == 200
    assert page.ok
    assert page.is_html
    assert not page.from_cache
    assert page.content_type == "text/html"
    assert page.headers == {"content-type": "text/html; charset=utf-8"}
    assert page.metadata["title"] == "Tea"
    assert page.markdown == "# Tea\n\nA page about tea."
    assert page.text == "Tea\n\nA page about tea."
    assert [element.get_text() for element in page.css("h1, th")] == ["Tea", "A"]
    assert repr(page) == f"<Page 200 {URL}>"


def test_from_html_bytes_uses_the_documents_own_charset() -> None:
    cafe = "caf" + chr(0xE9)
    body = b'<meta charset="iso-8859-1"><title>caf\xe9</title>'
    assert Page.from_html(body).metadata["title"] == cafe


def test_results_are_computed_once() -> None:
    page = Page.from_html(HTML, URL)
    for name in ("html", "soup", "metadata", "json_ld", "tables", "links", "content", "base_url"):
        assert getattr(page, name) is getattr(page, name)


def test_to_dict() -> None:
    page = Page.from_html(HTML, URL)
    data = page.to_dict()
    assert list(data) == [
        "url",
        "status",
        "content_type",
        "fetched_at",
        "from_cache",
        *PARTS,
    ]
    assert data["url"] == URL
    assert data["metadata"]["title"] == "Tea"
    assert data["json_ld"] == [{"@type": "Article"}]
    assert data["tables"] == [{"caption": None, "headers": ["A"], "rows": [["1"]]}]
    assert data["links"][0]["url"] == "https://example.test/more"
    assert data["content"]["word_count"] == 5
    json.dumps(data)  # everything is plain data

    assert list(page.to_dict(["links"])) == [
        "url",
        "status",
        "content_type",
        "fetched_at",
        "from_cache",
        "links",
    ]
    with pytest.raises(ValueError, match="unknown parts: images"):
        page.to_dict(["links", "images"])


def test_pages_that_are_not_html_give_empty_results() -> None:
    page = Page(response(b'{"name": "tea", "html": "<a href=\\"/x\\">x</a>"}', "application/json"))
    assert not page.is_html
    assert page.json() == {"name": "tea", "html": '<a href="/x">x</a>'}
    assert page.links == []
    assert page.tables == []
    assert page.json_ld == []
    assert page.markdown == ""
    assert page.metadata["title"] is None
    assert page.to_dict()["content"] == {"markdown": "", "text": "", "word_count": 0}


@pytest.mark.parametrize(
    ("body", "content_type", "expected"),
    [
        (b"<p>x</p>", "text/html; charset=utf-8", True),
        (b"<p>x</p>", "application/xhtml+xml", True),
        (b"<p>x</p>", "text/plain", False),
        (b"%PDF-1.7", "application/pdf", False),
        (b"  <!DOCTYPE html><title>x</title>", None, True),
        (b"<?xml version='1.0'?>\n<html><body>x</body></html>", None, True),
        (b"just some text", None, False),
    ],
)
def test_is_html(body: bytes, content_type: str | None, expected: bool) -> None:
    assert Page(response(body, content_type)).is_html is expected


def test_raise_for_status() -> None:
    page = Page(response(b"<p>fine</p>", "text/html"))
    assert page.raise_for_status() is page

    missing = Page(response(b"<p>gone</p>", "text/html", status=404))
    assert not missing.ok
    with pytest.raises(HTTPStatusError, match="HTTP 404") as raised:
        missing.raise_for_status()
    assert raised.value.status == 404
    assert raised.value.url == URL


def test_redirected_pages_report_both_addresses() -> None:
    page = Page(
        Response(
            url="https://example.test/old",
            final_url="https://example.test/new/",
            status=200,
            headers={"content-type": "text/html"},
            content=b'<a href="page">Next</a>',
        )
    )
    assert page.requested_url == "https://example.test/old"
    assert page.url == "https://example.test/new/"
    assert page.links[0].url == "https://example.test/new/page"
