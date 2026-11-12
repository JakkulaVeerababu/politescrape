"""Extractors that turn parsed HTML into data.

Each function works on its own, so you can use them on HTML you already have::

    from bs4 import BeautifulSoup
    from politescrape.extract import extract_tables

    tables = extract_tables(BeautifulSoup(html, "html.parser"))
"""

from politescrape.extract.content import Content, extract_content
from politescrape.extract.links import Link, extract_links
from politescrape.extract.metadata import extract_metadata
from politescrape.extract.schema import Schema, apply_schema, compile_schema, load_schema
from politescrape.extract.structured import extract_json_ld, find_json_ld, json_ld_types
from politescrape.extract.tables import Table, extract_tables

__all__ = [
    "Content",
    "Link",
    "Schema",
    "Table",
    "apply_schema",
    "compile_schema",
    "extract_content",
    "extract_json_ld",
    "extract_links",
    "extract_metadata",
    "extract_tables",
    "find_json_ld",
    "json_ld_types",
    "load_schema",
]
