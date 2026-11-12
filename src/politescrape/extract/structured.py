"""Structured data that pages embed as JSON-LD (schema.org and similar)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

from bs4 import BeautifulSoup

from politescrape._util import attr, only_tags

# Some sites wrap the JSON in an HTML comment or a CDATA section.
_WRAPPERS = re.compile(r"^\s*(?:<!--|//\s*<!\[CDATA\[|<!\[CDATA\[)|(?:-->|//\s*\]\]>|\]\]>)\s*$")
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def _loads(raw: str) -> Any:
    """Parse JSON-LD leniently; return ``None`` when it cannot be read at all."""
    text = _WRAPPERS.sub("", raw.strip()).strip()
    if not text:
        return None
    # Second try: raw line breaks inside strings are invalid JSON but very common.
    # Third try: so are trailing commas.
    attempts = ((text, True), (text, False), (_TRAILING_COMMA.sub(r"\1", text), False))
    for candidate, strict in attempts:
        try:
            return json.loads(candidate, strict=strict)
        except ValueError:
            continue
    return None


def extract_json_ld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Return every JSON-LD object on the page.

    ``@graph`` containers are flattened, so the result is one flat list of
    objects such as ``Product``, ``Article`` or ``JobPosting``. Blocks that
    are not valid JSON are skipped.
    """
    items: list[dict[str, Any]] = []
    for script in only_tags(soup.find_all("script")):
        if attr(script, "type").split(";")[0].strip().lower() != "application/ld+json":
            continue
        data = _loads(script.string if script.string is not None else script.get_text())
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if not isinstance(graph, list):
                items.append(item)
                continue
            context = item.get("@context")
            for node in graph:
                if isinstance(node, dict):
                    if context is not None and "@context" not in node:
                        node = {"@context": context, **node}
                    items.append(node)
    return items


def json_ld_types(item: dict[str, Any]) -> list[str]:
    """The ``@type`` of an object as a list (it may be a string, a list or missing)."""
    kind = item.get("@type")
    if isinstance(kind, str):
        return [kind]
    if isinstance(kind, list):
        return [value for value in kind if isinstance(value, str)]
    return []


def _walk(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def find_json_ld(items: list[dict[str, Any]], type_name: str) -> list[dict[str, Any]]:
    """Find objects of one type, including ones nested inside other objects.

    ``type_name`` is compared without regard to case and matches both
    ``"Product"`` and ``"https://schema.org/Product"``.
    """
    wanted = type_name.lower()
    found = []
    for candidate in _walk(items):
        for kind in json_ld_types(candidate):
            name = kind.lower()
            if name == wanted or name.endswith(("/" + wanted, ":" + wanted, "#" + wanted)):
                found.append(candidate)
                break
    return found
