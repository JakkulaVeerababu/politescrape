"""Laying the cells of an HTML table out on a grid.

Cells can span several rows and columns. Reading a table row by row without
accounting for that shifts every later value into the wrong column, so both
the table extractor and the Markdown converter go through this module.
"""

from __future__ import annotations

from collections.abc import Callable

from bs4.element import Tag

from politescrape._util import attr, only_tags

MAX_SPAN = 1000

# Cells that span several rows are "carried" into the rows below them:
# column -> (rows still to fill, text).
_Carried = dict[int, tuple[int, str]]


def span(cell: Tag, name: str) -> int:
    """Read ``rowspan`` or ``colspan``; anything unreadable counts as 1."""
    value = attr(cell, name).strip()
    return min(max(int(value), 1), MAX_SPAN) if value.isdigit() else 1


def own_rows(table: Tag) -> list[Tag]:
    """The rows of this table, leaving out rows of tables nested inside it."""
    return [row for row in only_tags(table.find_all("tr")) if row.find_parent("table") is table]


def row_cells(row: Tag) -> list[Tag]:
    return only_tags(row.find_all(["td", "th"], recursive=False))


def _take(carried: _Carried, column: int) -> str | None:
    """Use up one row of the cell carried into ``column`` and return its text."""
    entry = carried.get(column)
    if entry is None:
        return None
    remaining, text = entry
    if remaining <= 1:
        del carried[column]
    else:
        carried[column] = (remaining - 1, text)
    return text


def _fill_carried(line: list[str], carried: _Carried) -> None:
    """Append every carried cell that sits at the current end of the row."""
    while True:
        text = _take(carried, len(line))
        if text is None:
            return
        line.append(text)


def read_grid(
    rows: list[Tag], cell_text: Callable[[Tag], str]
) -> tuple[list[list[str]], list[bool]]:
    """Lay the cells out on a grid, repeating cells that span rows or columns.

    Returns the grid, padded so that every row has the same width, and for
    every row whether it is a header row (inside ``<thead>``, or made only of
    ``<th>`` cells). Rows without cells are left out.
    """
    grid: list[list[str]] = []
    header_flags: list[bool] = []
    carried: _Carried = {}
    for row in rows:
        cells = row_cells(row)
        if not cells:
            continue
        line: list[str] = []
        for cell in cells:
            _fill_carried(line, carried)
            text = cell_text(cell)
            rowspan = span(cell, "rowspan")
            for _ in range(span(cell, "colspan")):
                column = len(line)
                _take(carried, column)  # an overlapped cell still uses up one of its rows
                if rowspan > 1:
                    carried[column] = (rowspan - 1, text)
                line.append(text)
        _fill_carried(line, carried)
        # Cells carried into columns further right than this row reaches.
        while any(column > len(line) for column in carried):
            line.append("")
            _fill_carried(line, carried)
        grid.append(line)
        in_head = row.find_parent("thead") is not None
        header_flags.append(in_head or all(cell.name == "th" for cell in cells))
    width = max((len(line) for line in grid), default=0)
    return [line + [""] * (width - len(line)) for line in grid], header_flags
