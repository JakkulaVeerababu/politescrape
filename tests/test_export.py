"""Saving records as JSON Lines and CSV."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from politescrape.export import flatten, write_csv, write_jsonl

RECORDS = [
    {"name": "Green tea", "price": 4.5, "tags": ["loose", "organic"], "seller": {"name": "Hill"}},
    {"name": "Teapot", "price": None, "tags": [], "sizes": [{"ml": 500}, {"ml": 900}]},
]


def test_flatten() -> None:
    record = {
        "a": 1,
        "b": {"c": "x", "d": {"e": True}},
        "tags": ["one", None, 3],
        "pairs": [[1, 2], [3, 4]],
        "items": [{"n": 1}],
        "empty": [],
    }
    assert flatten(record) == {
        "a": 1,
        "b.c": "x",
        "b.d.e": True,
        "tags": "one |  | 3",
        "pairs": "[[1, 2], [3, 4]]",
        "items": '[{"n": 1}]',
        "empty": "",
    }


def test_write_jsonl_to_a_path(tmp_path: Path) -> None:
    target = tmp_path / "out.jsonl"
    snowman = {"name": "caf" + chr(0xE9)}
    assert write_jsonl([*RECORDS, snowman], target) == 3
    lines = target.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [*RECORDS, snowman]
    assert "caf" + chr(0xE9) in lines[2]  # written as text, not as an escape


def test_write_jsonl_to_an_open_file() -> None:
    buffer = io.StringIO()
    assert write_jsonl(iter(RECORDS), buffer) == 2
    assert buffer.getvalue().count("\n") == 2


def test_write_csv_uses_every_field_seen(tmp_path: Path) -> None:
    target = tmp_path / "out.csv"
    assert write_csv(RECORDS, target) == 2
    with target.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == ["name", "price", "tags", "seller.name", "sizes"]
    assert rows[0] == {
        "name": "Green tea",
        "price": "4.5",
        "tags": "loose | organic",
        "seller.name": "Hill",
        "sizes": "",
    }
    assert rows[1]["sizes"] == '[{"ml": 500}, {"ml": 900}]'
    assert rows[1]["price"] == ""
    assert b"\r" not in target.read_bytes()


def test_write_csv_to_an_open_file_and_with_no_records() -> None:
    buffer = io.StringIO()
    assert write_csv([{"a": 1}], buffer) == 1
    assert buffer.getvalue() == "a\n1\n"
    empty = io.StringIO()
    assert write_csv([], empty) == 0
