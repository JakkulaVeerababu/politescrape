"""HTML tables as rows of text, with merged cells expanded."""

from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

from politescrape._grid import own_rows, read_grid
from politescrape._util import attr, only_tags, visible_text


@dataclass
class Table:
    """One table from a page."""

    headers: list[str]
    """Column headings, or an empty list when the table has no header row."""
    rows: list[list[str]]
    """The data rows. Every row has the same number of cells."""
    caption: str | None = None

    @property
    def columns(self) -> list[str]:
        """A unique, non-empty name for every column."""
        width = max([len(self.headers), *(len(row) for row in self.rows)], default=0)
        names: list[str] = []
        used: dict[str, int] = {}
        for index in range(width):
            name = self.headers[index].strip() if index < len(self.headers) else ""
            name = name or f"column_{index + 1}"
            used[name] = used.get(name, 0) + 1
            if used[name] > 1:
                name = f"{name}_{used[name]}"
            names.append(name)
        return names

    def records(self) -> list[dict[str, str]]:
        """The rows as dictionaries keyed by column name."""
        columns = self.columns
        return [dict(zip(columns, row, strict=False)) for row in self.rows]

    def to_csv(self) -> str:
        """The table as CSV text, with a header line."""
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(self.columns)
        writer.writerows(self.rows)
        return buffer.getvalue()

    def save_csv(self, path: str | os.PathLike[str]) -> None:
        """Write the table to a CSV file (UTF-8)."""
        Path(path).write_text(self.to_csv(), encoding="utf-8", newline="")

    def to_dict(self) -> dict[str, Any]:
        return {"caption": self.caption, "headers": self.headers, "rows": self.rows}


def _merge_headers(header_rows: list[list[str]], width: int) -> list[str]:
    """Join stacked header rows column by column ("Population" + "2024")."""
    headers = []
    for column in range(width):
        parts: list[str] = []
        for row in header_rows:
            value = row[column]
            if value and value not in parts:
                parts.append(value)
        headers.append(" ".join(parts))
    return headers


def extract_tables(soup: BeautifulSoup) -> list[Table]:
    """Return the data tables on a page, in document order.

    Cells that span rows or columns are repeated so that every row lines up
    with the headings. Tables used only for layout (``role="presentation"``,
    or tables that contain other tables) are skipped; the tables inside them
    are still read.
    """
    tables: list[Table] = []
    for element in only_tags(soup.find_all("table")):
        if attr(element, "role").strip().lower() in ("presentation", "none"):
            continue
        if element.find("table") is not None:
            continue
        grid, header_flags = read_grid(own_rows(element), visible_text)
        if not grid:
            continue
        width = len(grid[0])

        header_count = 0
        while header_count < len(grid) and header_flags[header_count]:
            header_count += 1
        if header_count == len(grid):
            # Every row looks like a header: treat only the first one as headings.
            header_count = 1
        headers = _merge_headers(grid[:header_count], width) if header_count else []
        rows = [line for line in grid[header_count:] if any(line)]
        if not rows and not any(headers):
            continue

        caption_tag = element.find("caption")
        caption = visible_text(caption_tag) if isinstance(caption_tag, Tag) else ""
        tables.append(Table(headers=headers, rows=rows, caption=caption or None))
    return tables
