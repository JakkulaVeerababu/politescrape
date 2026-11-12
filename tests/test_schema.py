"""Declarative extraction with schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from politescrape import Page, SchemaError, compile_schema, load_schema
from politescrape.extract import Schema
from politescrape.extract.schema import _number

URL = "https://shop.example.test/catalogue/"

SHOP = """
<html><body>
<h1>Tea   shop</h1>
<p class="total">Showing 2 of 1,204 products</p>
<article class="product" data-sku="T-100">
  <h3><a href="green-tea.html" title="Green tea, 100 g">Green tea...</a></h3>
  <p class="price">Rs. 1,250.50</p>
  <p class="stock in">In stock (12 available)</p>
  <p class="rating four">Rated</p>
  <ul><li class="tag">loose</li><li class="tag">organic</li></ul>
  <div class="seller"><span class="name">Hill Estate</span><a href="/sellers/hill">profile</a></div>
  <div class="blurb">Fresh <b>spring</b> harvest.</div>
</article>
<article class="product" data-sku="T-200">
  <h3><a href="/catalogue/black-tea.html" title="Black tea, 250 g">Black tea...</a></h3>
  <p class="price">Rs. 480</p>
  <p class="rating two">Rated</p>
  <ul></ul>
</article>
</body></html>
"""


@pytest.fixture
def page() -> Page:
    return Page.from_html(SHOP, URL)


def test_a_list_of_items(page: Page) -> None:
    schema = {
        "items": "article.product",
        "fields": {
            "sku": "@data-sku",
            "title": "h3 a@title",
            "label": "h3 a",
            "price": {"selector": ".price", "type": "number"},
            "available": {"selector": ".stock", "type": "integer", "default": 0},
            "in_stock": {"selector": ".stock.in", "type": "boolean"},
            "rating": {"selector": ".rating", "attr": "class", "pattern": r"rating (\w+)"},
            "url": {"selector": "h3 a", "attr": "href", "type": "url"},
            "tags": {"selector": ".tag", "all": True},
        },
    }
    assert page.extract(schema) == [
        {
            "sku": "T-100",
            "title": "Green tea, 100 g",
            "label": "Green tea...",
            "price": 1250.5,
            "available": 12,
            "in_stock": True,
            "rating": "four",
            "url": "https://shop.example.test/catalogue/green-tea.html",
            "tags": ["loose", "organic"],
        },
        {
            "sku": "T-200",
            "title": "Black tea, 250 g",
            "label": "Black tea...",
            "price": 480,
            "available": 0,
            "in_stock": False,
            "rating": "two",
            "url": "https://shop.example.test/catalogue/black-tea.html",
            "tags": [],
        },
    ]


def test_a_single_object_for_the_whole_page(page: Page) -> None:
    schema = {
        "fields": {
            "heading": "h1",
            "total": {"selector": ".total", "pattern": r"of ([\d,]+)", "type": "integer"},
            "first_price": ".price",
            "missing": ".does-not-exist",
            "missing_with_default": {"selector": ".does-not-exist", "default": "n/a"},
        }
    }
    assert page.extract(schema) == {
        "heading": "Tea shop",
        "total": 1204,
        "first_price": "Rs. 1,250.50",
        "missing": None,
        "missing_with_default": "n/a",
    }


def test_nested_fields(page: Page) -> None:
    schema = {
        "items": ".product",
        "fields": {
            "seller": {
                "selector": ".seller",
                "fields": {
                    "name": ".name",
                    "url": {"selector": "a", "attr": "href", "type": "url"},
                },
            },
            "tags": {"selector": ".tag", "all": True, "fields": {"label": {"attr": "text"}}},
        },
    }
    first, second = page.extract(schema)
    assert first == {
        "seller": {"name": "Hill Estate", "url": "https://shop.example.test/sellers/hill"},
        "tags": [{"label": "loose"}, {"label": "organic"}],
    }
    assert second == {"seller": None, "tags": []}


def test_html_and_markdown_values(page: Page) -> None:
    schema = {
        "fields": {
            "html": {"selector": ".blurb", "attr": "html"},
            "markdown": {"selector": ".blurb", "attr": "markdown"},
            "link": {"selector": ".seller", "attr": "markdown"},
        }
    }
    assert page.extract(schema) == {
        "html": "Fresh <b>spring</b> harvest.",
        "markdown": "Fresh **spring** harvest.",
        "link": "Hill Estate[profile](https://shop.example.test/sellers/hill)",
    }


def test_patterns(page: Page) -> None:
    schema = {
        "fields": {
            "whole_match": {"selector": ".total", "pattern": r"\d+ of"},
            "group": {"selector": ".total", "pattern": r"Showing (\d+)"},
            "no_match": {"selector": ".total", "pattern": r"(\d+) pages", "default": "none"},
            "all_matches": {"selector": ".price", "all": True, "pattern": r"[\d,.]+$"},
        }
    }
    assert page.extract(schema) == {
        "whole_match": "2 of",
        "group": "2",
        "no_match": "none",
        "all_matches": ["1,250.50", "480"],
    }


def test_list_defaults_and_missing_attributes(page: Page) -> None:
    schema = {
        "fields": {
            "none": {"selector": ".nope", "all": True},
            "fallback": {"selector": ".nope", "all": True, "default": ["empty"]},
            "skus": {"selector": "article, h1", "attr": "data-sku", "all": True},
            "empty_text": {"selector": "ul:empty", "default": "nothing"},
        }
    }
    assert page.extract(schema) == {
        "none": [],
        "fallback": ["empty"],
        "skus": ["T-100", "T-200"],
        "empty_text": "nothing",
    }


@pytest.mark.parametrize(
    ("text", "whole", "expected"),
    [
        ("Rs. 1,250.50", False, 1250.5),
        ("$51.77", False, 51.77),
        ("12 reviews", False, 12),
        ("about 1,234,567 results", False, 1234567),
        ("-4.5 degrees", False, -4.5),
        (".75 off", False, 0.75),
        ("4.9 out of 5", True, 4),
        ("free", False, None),
    ],
)
def test_numbers(text: str, whole: bool, expected: float | None) -> None:
    result = _number(text, whole=whole)
    assert result == expected
    assert type(result) is type(expected)


@pytest.mark.parametrize(
    ("schema", "message"),
    [
        ("not a mapping", "must be an object"),
        ({"fields": {}}, "at least one field"),
        ({"items": ".x"}, "at least one field"),
        ({"fields": {"a": "h1"}, "item": ".x"}, "unknown schema entries: item"),
        ({"items": "", "fields": {"a": "h1"}}, "items: a CSS selector"),
        ({"items": "div[", "fields": {"a": "h1"}}, "items: invalid CSS selector"),
        ({"fields": {"a": 5}}, "fields.a: a field must be"),
        ({"fields": {"a": "h1 >> b"}}, "fields.a: invalid CSS selector"),
        ({"fields": {"a": {"selector": "h1", "atr": "x"}}}, "fields.a: unknown options: atr"),
        ({"fields": {"a": {"selector": "h1", "attr": ""}}}, "'attr' must be"),
        ({"fields": {"a": {"selector": "h1", "all": "yes"}}}, "'all' must be true or false"),
        ({"fields": {"a": {"selector": "h1", "type": "date"}}}, "'type' must be one of"),
        ({"fields": {"a": {"selector": "h1", "pattern": "("}}}, "invalid pattern"),
        ({"fields": {"a": {"selector": "h1", "pattern": 5}}}, "'pattern' must be a string"),
        ({"fields": {"a": {"all": True}}}, "'all' needs a 'selector'"),
        ({"fields": {"a": {"selector": "h1", "fields": {}}}}, "fields.a.fields: expected"),
    ],
)
def test_schema_mistakes_are_reported_clearly(schema: Any, message: str) -> None:
    with pytest.raises(SchemaError, match=message):
        compile_schema(schema)


def test_a_compiled_schema_can_be_reused(page: Page) -> None:
    schema = compile_schema({"description": "Just the heading", "fields": {"heading": "h1"}})
    assert isinstance(schema, Schema)
    assert compile_schema(schema) is schema
    assert page.extract(schema) == {"heading": "Tea shop"}
    assert schema.apply(page.soup) == {"heading": "Tea shop"}


def test_load_schema(tmp_path: Path, page: Page) -> None:
    path = tmp_path / "schema.json"
    path.write_text(json.dumps({"items": ".product", "fields": {"sku": "@data-sku"}}), "utf-8")
    assert page.extract(load_schema(path)) == [{"sku": "T-100"}, {"sku": "T-200"}]


def test_load_schema_errors(tmp_path: Path) -> None:
    with pytest.raises(SchemaError, match="cannot read schema file"):
        load_schema(tmp_path / "missing.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", "utf-8")
    with pytest.raises(SchemaError, match="not valid JSON"):
        load_schema(broken)
    wrong = tmp_path / "wrong.json"
    wrong.write_text("[1, 2, 3]", "utf-8")
    with pytest.raises(SchemaError, match="must be an object"):
        load_schema(wrong)
