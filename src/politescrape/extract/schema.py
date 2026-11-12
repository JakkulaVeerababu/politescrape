"""Declarative extraction: describe the fields you want, get JSON back.

A schema is plain data, so it can live in a JSON file next to your project::

    {
      "items": "article.product_pod",
      "fields": {
        "title": "h3 a@title",
        "price": {"selector": ".price_color", "type": "number"},
        "url": {"selector": "h3 a", "attr": "href", "type": "url"}
      }
    }

``items`` is a CSS selector for the repeated element (one result per match);
leave it out to get a single object for the whole page. See
``docs/extraction-schema.md`` for every option.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import soupsieve
from bs4.element import Tag

from politescrape._util import absolute, attr, visible_text
from politescrape.errors import SchemaError
from politescrape.markdown import to_markdown

TYPES = frozenset({"string", "number", "integer", "url", "boolean"})
_SCHEMA_KEYS = frozenset({"items", "fields", "description"})
_FIELD_KEYS = frozenset({"selector", "attr", "all", "type", "pattern", "default", "fields"})
_SHORTHAND_ATTR = re.compile(r"^(.*)@([A-Za-z_][\w:.-]*)$", re.DOTALL)
_NUMBER = re.compile(r"[-+]?(?:\d[\d,]*(?:\.\d+)?|\.\d+)")


@dataclass(frozen=True)
class Field:
    name: str
    selector: str | None
    """CSS selector, or ``None`` to read from the current element itself."""
    attr: str = "text"
    many: bool = False
    type: str = "string"
    pattern: re.Pattern[str] | None = None
    default: Any = None
    fields: tuple[Field, ...] | None = None


@dataclass(frozen=True)
class Schema:
    """A validated extraction schema. Build one with :func:`compile_schema`."""

    fields: tuple[Field, ...]
    items: str | None = None

    def apply(self, root: Tag, base_url: str = "") -> Any:
        """Extract from ``root``: a list of objects with ``items``, otherwise one object."""
        if self.items is None:
            return _record(self.fields, root, base_url)
        return [_record(self.fields, element, base_url) for element in root.select(self.items)]


def compile_schema(spec: Mapping[str, Any] | Schema) -> Schema:
    """Validate a schema and prepare it for use.

    Raises:
        SchemaError: with a message that names the offending field.
    """
    if isinstance(spec, Schema):
        return spec
    if not isinstance(spec, Mapping):
        raise SchemaError("a schema must be an object with a 'fields' entry")
    unknown = set(spec) - _SCHEMA_KEYS
    if unknown:
        raise SchemaError(f"unknown schema entries: {', '.join(sorted(map(str, unknown)))}")
    items = spec.get("items")
    if items is not None:
        items = _selector(items, "items")
    return Schema(fields=_fields(spec.get("fields"), "fields"), items=items)


def load_schema(path: str | os.PathLike[str]) -> Schema:
    """Read a schema from a JSON file."""
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise SchemaError(f"cannot read schema file {path}: {error.strerror or error}") from error
    except ValueError as error:
        raise SchemaError(f"schema file {path} is not valid JSON: {error}") from error
    return compile_schema(spec)


def apply_schema(root: Tag, schema: Mapping[str, Any] | Schema, base_url: str = "") -> Any:
    """Compile ``schema`` if needed and extract from ``root``."""
    return compile_schema(schema).apply(root, base_url)


# ------------------------------------------------------------------- compiling


def _selector(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{where}: a CSS selector must be a non-empty string")
    try:
        soupsieve.compile(value)
    except Exception as error:  # soupsieve raises several unrelated exception types
        raise SchemaError(f"{where}: invalid CSS selector {value!r}: {error}") from error
    return value.strip()


def _fields(spec: Any, where: str) -> tuple[Field, ...]:
    if not isinstance(spec, Mapping) or not spec:
        raise SchemaError(f"{where}: expected an object with at least one field")
    return tuple(_field(str(name), value, f"{where}.{name}") for name, value in spec.items())


def _field(name: str, spec: Any, where: str) -> Field:
    if isinstance(spec, str):
        # Shorthand: "selector", "selector@attribute" or "@attribute".
        match = _SHORTHAND_ATTR.match(spec)
        selector, attribute = (match.group(1), match.group(2)) if match else (spec, "text")
        selector = selector.strip()
        return Field(name, _selector(selector, where) if selector else None, attribute)
    if not isinstance(spec, Mapping):
        raise SchemaError(f"{where}: a field must be a selector string or an object")
    unknown = set(spec) - _FIELD_KEYS
    if unknown:
        raise SchemaError(f"{where}: unknown options: {', '.join(sorted(map(str, unknown)))}")

    selector = spec.get("selector")
    if selector is not None:
        selector = _selector(selector, where)
    attribute = spec.get("attr", "text")
    if not isinstance(attribute, str) or not attribute:
        raise SchemaError(f"{where}: 'attr' must be a non-empty string")
    many = spec.get("all", False)
    if not isinstance(many, bool):
        raise SchemaError(f"{where}: 'all' must be true or false")
    kind = spec.get("type", "string")
    if kind not in TYPES:
        raise SchemaError(f"{where}: 'type' must be one of {', '.join(sorted(TYPES))}")
    pattern = spec.get("pattern")
    compiled: re.Pattern[str] | None = None
    if pattern is not None:
        if not isinstance(pattern, str):
            raise SchemaError(f"{where}: 'pattern' must be a string")
        try:
            compiled = re.compile(pattern)
        except re.error as error:
            raise SchemaError(f"{where}: invalid pattern {pattern!r}: {error}") from error
    nested = spec.get("fields")
    if many and selector is None:
        raise SchemaError(f"{where}: 'all' needs a 'selector' to match more than one element")
    return Field(
        name=name,
        selector=selector,
        attr=attribute,
        many=many,
        type=kind,
        pattern=compiled,
        default=spec.get("default"),
        fields=_fields(nested, f"{where}.fields") if nested is not None else None,
    )


# ------------------------------------------------------------------ extracting


def _record(fields: tuple[Field, ...], element: Tag, base_url: str) -> dict[str, Any]:
    return {field.name: _value(field, element, base_url) for field in fields}


def _value(field: Field, element: Tag, base_url: str) -> Any:
    targets: list[Tag]
    if field.selector is None:
        targets = [element]
    elif field.many:
        targets = list(element.select(field.selector))
    else:
        found = element.select_one(field.selector)
        targets = [found] if found is not None else []

    if field.type == "boolean":
        return bool(targets)
    if field.fields is not None:
        records = [_record(field.fields, target, base_url) for target in targets]
        if field.many:
            return records
        return records[0] if records else field.default

    values = [
        value for value in (_convert(field, t, base_url) for t in targets) if value is not None
    ]
    if field.many:
        return values if values or field.default is None else field.default
    return values[0] if values else field.default


def _raw(field: Field, element: Tag, base_url: str) -> str | None:
    if field.attr == "text":
        return visible_text(element)
    if field.attr == "html":
        return element.decode_contents().strip()
    if field.attr == "markdown":
        return to_markdown(element, base_url)
    return attr(element, field.attr).strip() if element.has_attr(field.attr) else None


def _convert(field: Field, element: Tag, base_url: str) -> Any:
    raw = _raw(field, element, base_url)
    if raw is None:
        return None
    if field.pattern is not None:
        match = field.pattern.search(raw)
        if match is None:
            return None
        raw = (match.group(1) if match.groups() else match.group(0)) or ""
        raw = raw.strip()
    if raw == "":
        return None
    if field.type == "url":
        return absolute(base_url, raw)
    if field.type in ("number", "integer"):
        return _number(raw, whole=field.type == "integer")
    return raw


def _number(text: str, *, whole: bool) -> int | float | None:
    """Read the first number in ``text``: "$1,234.50" is 1234.5 and "12 reviews" is 12."""
    match = _NUMBER.search(text)
    if match is None:
        return None
    digits = match.group(0).replace(",", "")
    try:
        value = float(digits)
    except ValueError:
        return None
    if whole or "." not in digits:
        return int(value)
    return value
