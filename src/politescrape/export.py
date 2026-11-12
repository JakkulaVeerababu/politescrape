"""Saving scraped records as JSON Lines or CSV."""

from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any, TextIO


@contextmanager
def _writable(target: str | os.PathLike[str] | TextIO) -> Iterator[TextIO]:
    if isinstance(target, (str, os.PathLike)):
        with open(target, "w", encoding="utf-8", newline="") as handle:
            yield handle
    else:
        yield target


def flatten(record: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested data into one level for CSV.

    Nested objects become dotted names (``{"a": {"b": 1}}`` gives ``a.b``),
    lists of simple values are joined with ``" | "`` and anything more
    complicated is written as JSON.
    """
    flat: dict[str, Any] = {}
    for key, value in record.items():
        name = f"{prefix}{key}"
        if isinstance(value, Mapping):
            flat.update(flatten(value, name + "."))
        elif isinstance(value, (list, tuple)):
            if any(isinstance(item, (Mapping, list, tuple)) for item in value):
                flat[name] = json.dumps(value, ensure_ascii=False)
            else:
                flat[name] = " | ".join("" if item is None else str(item) for item in value)
        else:
            flat[name] = value
    return flat


def write_jsonl(
    records: Iterable[Mapping[str, Any]], target: str | os.PathLike[str] | TextIO
) -> int:
    """Write one JSON object per line. Returns the number of records written."""
    count = 0
    with _writable(target) as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def write_csv(records: Iterable[Mapping[str, Any]], target: str | os.PathLike[str] | TextIO) -> int:
    """Write records as CSV, flattening nested values. Returns the number of rows.

    The columns are every field seen in any record, in order of first
    appearance, so records do not all need the same fields.
    """
    rows = [flatten(record) for record in records]
    columns: dict[str, None] = {}
    for row in rows:
        columns.update(dict.fromkeys(row))
    with _writable(target) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
