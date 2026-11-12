"""Tables: headers, merged cells, nesting and CSV output."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from politescrape import Page, Table
from politescrape._util import parse_html
from politescrape.extract import extract_tables


def tables(html: str) -> list[Table]:
    return extract_tables(parse_html(html))


def test_header_row_in_thead() -> None:
    html = """
    <table>
      <caption> Caffeine   per cup </caption>
      <thead><tr><th>Kind</th><th>mg</th></tr></thead>
      <tbody><tr><td>Green</td><td>28</td></tr><tr><td>Black</td><td>47</td></tr></tbody>
    </table>
    """
    (table,) = tables(html)
    assert table.caption == "Caffeine per cup"
    assert table.headers == ["Kind", "mg"]
    assert table.rows == [["Green", "28"], ["Black", "47"]]
    assert table.records() == [{"Kind": "Green", "mg": "28"}, {"Kind": "Black", "mg": "47"}]
    assert table.to_dict() == {
        "caption": "Caffeine per cup",
        "headers": ["Kind", "mg"],
        "rows": [["Green", "28"], ["Black", "47"]],
    }


def test_header_row_made_of_th_cells() -> None:
    (table,) = tables("<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>")
    assert table.headers == ["A", "B"]
    assert table.rows == [["1", "2"]]


def test_row_headings_are_data_not_headers() -> None:
    html = "<table><tr><th>Green</th><td>28</td></tr><tr><th>Black</th><td>47</td></tr></table>"
    (table,) = tables(html)
    assert table.headers == []
    assert table.rows == [["Green", "28"], ["Black", "47"]]
    assert table.columns == ["column_1", "column_2"]
    assert table.records()[0] == {"column_1": "Green", "column_2": "28"}


def test_cells_that_span_rows_and_columns_are_repeated() -> None:
    html = """
    <table>
      <tr><th>Region</th><th>City</th><th>2023</th><th>2024</th></tr>
      <tr><td rowspan="2">North</td><td>Alpha</td><td>1</td><td>2</td></tr>
      <tr><td>Beta</td><td colspan="2">n/a</td></tr>
      <tr><td>South</td><td>Gamma</td><td rowspan="2">5</td><td>6</td></tr>
      <tr><td>South</td><td>Delta</td><td>8</td></tr>
    </table>
    """
    (table,) = tables(html)
    assert table.rows == [
        ["North", "Alpha", "1", "2"],
        ["North", "Beta", "n/a", "n/a"],
        ["South", "Gamma", "5", "6"],
        ["South", "Delta", "5", "8"],
    ]


def test_a_cell_carried_past_the_end_of_a_short_row() -> None:
    html = """
    <table>
      <tr><td>a</td><td>b</td><td rowspan="2">c</td></tr>
      <tr><td>d</td></tr>
    </table>
    """
    (table,) = tables(html)
    assert table.rows == [["a", "b", "c"], ["d", "", "c"]]


def test_stacked_header_rows_are_merged() -> None:
    html = """
    <table>
      <thead>
        <tr><th rowspan="2">Country</th><th colspan="2">Population</th></tr>
        <tr><th>2023</th><th>2024</th></tr>
      </thead>
      <tbody><tr><td>Freedonia</td><td>10</td><td>11</td></tr></tbody>
    </table>
    """
    (table,) = tables(html)
    assert table.headers == ["Country", "Population 2023", "Population 2024"]
    assert table.rows == [["Freedonia", "10", "11"]]


def test_a_table_of_only_header_cells_keeps_its_first_row_as_headings() -> None:
    (table,) = tables("<table><tr><th>A</th><th>B</th></tr><tr><th>1</th><th>2</th></tr></table>")
    assert table.headers == ["A", "B"]
    assert table.rows == [["1", "2"]]


def test_column_names_are_unique_and_never_empty() -> None:
    html = (
        "<table><tr><th>Name</th><th></th><th>Name</th><th>Name</th></tr>"
        "<tr><td>a</td><td>b</td><td>c</td><td>d</td></tr></table>"
    )
    (table,) = tables(html)
    assert table.columns == ["Name", "column_2", "Name_2", "Name_3"]
    assert table.records() == [{"Name": "a", "column_2": "b", "Name_2": "c", "Name_3": "d"}]


def test_ragged_rows_are_padded_and_empty_rows_dropped() -> None:
    html = """
    <table>
      <tr><th>A</th><th>B</th><th>C</th></tr>
      <tr><td>1</td></tr>
      <tr><td></td><td> </td><td></td></tr>
      <tr></tr>
      <tr><td>2</td><td>3</td><td>4</td></tr>
    </table>
    """
    (table,) = tables(html)
    assert table.rows == [["1", "", ""], ["2", "3", "4"]]


def test_cell_text_reads_the_way_a_person_would() -> None:
    html = """
    <table><tr>
      <td>H<sub>2</sub>O</td>
      <td>line one<br>line two</td>
      <td><p>first</p><p>second</p></td>
      <td>kept<script>dropped()</script><!-- and this --></td>
      <td><a href="/x">  linked&nbsp;text </a></td>
    </tr></table>
    """
    (table,) = tables(html)
    assert table.rows == [["H2O", "line one line two", "first second", "kept", "linked text"]]


def test_layout_tables_are_skipped_but_tables_inside_them_are_read() -> None:
    html = """
    <table id="layout"><tr><td>
      <table id="data"><tr><th>A</th></tr><tr><td>1</td></tr></table>
    </td><td>Side</td></tr></table>
    <table role="presentation"><tr><td>Just layout</td></tr></table>
    <table></table>
    <table><tr><td></td></tr></table>
    """
    found = tables(html)
    assert len(found) == 1
    assert found[0].headers == ["A"]
    assert found[0].rows == [["1"]]


def test_tables_come_back_in_document_order() -> None:
    html = (
        "<table><tr><td>first</td></tr></table><p>between</p>"
        "<table><tr><td>second</td></tr></table>"
    )
    assert [table.rows[0][0] for table in tables(html)] == ["first", "second"]


def test_csv_output(tmp_path: Path) -> None:
    html = (
        "<table><tr><th>Name</th><th>Note</th></tr>"
        '<tr><td>Tea, green</td><td>says "hello"</td></tr></table>'
    )
    (table,) = tables(html)
    assert table.to_csv() == 'Name,Note\n"Tea, green","says ""hello"""\n'

    target = tmp_path / "table.csv"
    table.save_csv(target)
    assert target.read_bytes() == table.to_csv().encode("utf-8")
    assert list(csv.reader(io.StringIO(table.to_csv()))) == [
        ["Name", "Note"],
        ["Tea, green", 'says "hello"'],
    ]


def test_csv_of_a_table_without_headers_uses_column_names() -> None:
    (table,) = tables("<table><tr><td>1</td><td>2</td></tr></table>")
    assert table.to_csv() == "column_1,column_2\n1,2\n"


def test_page_tables() -> None:
    page = Page.from_html("<table><tr><th>A</th></tr><tr><td>1</td></tr></table>")
    assert page.tables[0].records() == [{"A": "1"}]
    assert page.tables is page.tables  # computed once
